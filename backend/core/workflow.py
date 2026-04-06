import os
import base64
import json
import sys
import shutil
import logging
import time
import stat
import requests
import paramiko
import re
import shlex
import subprocess
from typing import List, Dict, Any, Optional, Callable, Set, Tuple
from pydantic import BaseModel
from datetime import datetime

from .config_model import ExtractarrConfig
from .utils import decrypt_secret, is_windows

logger = logging.getLogger(__name__)

class WorkflowState(BaseModel):
    running: bool = False
    status: str = "Idle"
    percent: int = 0
    message: str = "Waiting to start"
    start_time: Optional[float] = None
    end_time: Optional[float] = None
    exit_code: Optional[int] = None
    logs: List[Dict[str, Any]] = []

class WorkflowEngine:
    def __init__(self, config: ExtractarrConfig):
        self.config = config
        self.state = WorkflowState()
        self._on_progress: Optional[Callable[[WorkflowState], None]] = None
        self.moved_paths: Dict[str, Set[str]] = {"tv": set(), "movies": set(), "music": set()}
        self._smb_connections: List[str] = []

    def set_on_progress(self, callback: Callable[[WorkflowState], None]):
        self._on_progress = callback

    def _log(self, message: str, level: str = "info"):
        entry = {"ts": time.time(), "msg": message, "level": level}
        self.state.logs.append(entry)
        if level == "error":
            logger.error(message)
        elif level == "warn":
            logger.warning(message)
        else:
            logger.info(message)
        if self._on_progress:
            self._on_progress(self.state)

    def _update_progress(self, percent: int, message: str):
        self.state.percent = percent
        self.state.message = message
        self._log(f"[{percent}%] {message}")

    def _create_ssh_client(self) -> paramiko.SSHClient:
        client = paramiko.SSHClient()
        client.load_system_host_keys()

        host_key = (self.config.sftp_host_key or "").strip()
        if host_key:
            host_keys = client.get_host_keys()
            host = self.config.sftp_host

            parts = host_key.split()
            key_types = {
                "ssh-ed25519": paramiko.Ed25519Key,
                "ssh-rsa": paramiko.RSAKey,
                "ecdsa-sha2-nistp256": paramiko.ECDSAKey,
                "ecdsa-sha2-nistp384": paramiko.ECDSAKey,
                "ecdsa-sha2-nistp521": paramiko.ECDSAKey,
            }

            key_type = None
            key_data = None
            key_cls = None

            # Try to find a known key type among the parts
            for i, part in enumerate(parts):
                if part in key_types:
                    key_type = part
                    key_cls = key_types[part]
                    # The next part that looks like base64 is likely the data
                    for j in range(i + 1, len(parts)):
                        if len(parts[j]) > 20:
                            key_data = parts[j]
                            break
                    break

            # Fallback for simple "type data" if no known type found yet
            if not key_type and len(parts) >= 2:
                key_type, key_data = parts[0], parts[1]
                key_cls = key_types.get(key_type)

            if not key_cls:
                raise RuntimeError(f"Unsupported SFTP host key type: {key_type or 'unknown'}")
            if not key_data:
                raise RuntimeError("Invalid SFTP host key format: missing key data")

            try:
                # Add padding if missing (base64 length must be multiple of 4)
                padded_data = key_data
                missing_padding = len(padded_data) % 4
                if missing_padding:
                    padded_data += "=" * (4 - missing_padding)

                decoded = base64.b64decode(padded_data.encode("ascii"))
                key_obj = key_cls(data=decoded)
                host_keys.add(host, key_type, key_obj)
                host_keys.add(f"[{host}]:{self.config.sftp_port}", key_type, key_obj)
            except Exception as e:
                raise RuntimeError(f"Failed to parse SFTP host key: {str(e)}")

        client.set_missing_host_key_policy(paramiko.RejectPolicy())
        return client

    def run(self):
        if self.state.running:
            self._log("Workflow already running", "error")
            return
        
        self.state.running = True
        self.state.start_time = time.time()
        self.state.percent = 0
        self.state.message = "Starting workflow"
        self.state.exit_code = None
        self.state.logs = []
        self.moved_paths = {"tv": set(), "movies": set(), "music": set()}
        self._smb_connections = []

        try:
            self._execute_workflow()
            self._update_progress(100, "Workflow completed successfully")
            self.state.exit_code = 0
        except Exception as e:
            self._log(f"Workflow failed: {str(e)}", "error")
            self.state.exit_code = 1
            self.state.message = f"Error: {str(e)}"
        finally:
            self._disconnect_smb_shares()
            self.state.running = False
            self.state.end_time = time.time()
            if self._on_progress:
                self._on_progress(self.state)

    def _execute_workflow(self):
        # Step 0: Connect SMB Shares (Windows only)
        self._connect_smb_shares()

        # Step 1: SFTP Download
        self._step_download()

        # Step 2: Remote Cleanup
        self._step_remote_cleanup()

        # Step 3: Extraction & Sorting
        self._step_extraction_and_sorting()

        # Step 4: Final Move & Import Triggers
        self._step_import_triggers()

    def _connect_smb_shares(self):
        if not is_windows():
            return

        self._update_progress(2, "Connecting SMB shares")
        user = self.config.smb_user
        password = decrypt_secret(self.config.smb_pass)
        
        if not user or not password:
            self._log("SMB credentials not set; relying on existing Windows access", "warn")
            return

        paths = [
            self.config.local_download_path,
            self.config.paths.tv_source,
            self.config.paths.tv_import,
            self.config.paths.movies_source,
            self.config.paths.movies_import,
            self.config.paths.music_source,
            self.config.paths.music_import,
        ]
        
        share_roots = set()
        for p in paths:
            if p and p.startswith("\\\\"):
                parts = p.split("\\")
                if len(parts) >= 4:
                    share_roots.add(f"\\\\{parts[2]}\\{parts[3]}")

        for root in share_roots:
            try:
                self._log(f"Connecting to SMB share: {root}")
                # Try to connect
                cmd = ["net", "use", root, password, f"/user:{user}", "/persistent:no"]
                result = subprocess.run(cmd, capture_output=True, text=True)
                if result.returncode == 0:
                    self._smb_connections.append(root)
                elif "1219" in result.stderr or "multiple connections" in result.stderr.lower():
                    # Conflict, delete and retry
                    subprocess.run(["net", "use", root, "/delete", "/y"], capture_output=True)
                    result = subprocess.run(cmd, capture_output=True, text=True)
                    if result.returncode == 0:
                        self._smb_connections.append(root)
                    else:
                        self._log(f"Failed to connect to SMB {root}: {result.stderr}", "error")
                else:
                    self._log(f"Failed to connect to SMB {root}: {result.stderr}", "error")
            except Exception as e:
                self._log(f"SMB connection error for {root}: {str(e)}", "error")

    def _disconnect_smb_shares(self):
        if not is_windows() or not self._smb_connections:
            return
        
        for root in self._smb_connections:
            try:
                subprocess.run(["net", "use", root, "/delete", "/y"], capture_output=True)
                self._log(f"Disconnected SMB share: {root}")
            except:
                pass
        self._smb_connections = []

    def _step_download(self):
        self._update_progress(5, "Connecting to SFTP")
        host = self.config.sftp_host
        port = self.config.sftp_port
        user = self.config.sftp_user
        password = decrypt_secret(self.config.sftp_pass)
        remote_path = self.config.remote_path
        local_path = self.config.local_download_path

        if not host or not user or not password:
            raise ValueError("SFTP credentials missing")

        if not os.path.exists(local_path):
            try:
                os.makedirs(local_path, exist_ok=True)
            except Exception as e:
                 raise RuntimeError(f"Failed to create LocalDownloadPath {local_path}: {str(e)}")

        try:
            client = self._create_ssh_client()
            client.connect(host, port=port, username=user, password=password, timeout=30)
            sftp = client.open_sftp()
            
            self._log(f"Connected to SFTP {host}")
            
            def download_dir(remote_dir, local_dir):
                if not os.path.exists(local_dir):
                    os.makedirs(local_dir)
                for entry in sftp.listdir_attr(remote_dir):
                    rempath = remote_dir + "/" + entry.filename
                    locpath = os.path.join(local_dir, entry.filename)
                    if stat.S_ISDIR(entry.st_mode):
                        download_dir(rempath, locpath)
                    else:
                        self._log(f"Downloading {entry.filename}...")
                        sftp.get(rempath, locpath)

            # In V1, we get everything from the remotePath root
            try:
                entries = sftp.listdir_attr(remote_path)
            except IOError:
                self._log(f"Remote path {remote_path} not found", "error")
                return

            total = len(entries)
            if total == 0:
                 self._log("No files to download on remote")
                 return

            for i, entry in enumerate(entries):
                rempath = remote_path + "/" + entry.filename
                locpath = os.path.join(local_path, entry.filename)
                
                self._update_progress(5 + int((i / total) * 30), f"Downloading {entry.filename}")
                if stat.S_ISDIR(entry.st_mode):
                    download_dir(rempath, locpath)
                else:
                    sftp.get(rempath, locpath)

            sftp.close()
            client.close()
        except Exception as e:
            raise RuntimeError(f"SFTP Download failed: {str(e)}")

    def _step_remote_cleanup(self):
        self._update_progress(40, "Running remote cleanup")
        host = self.config.sftp_host
        port = self.config.sftp_port
        user = self.config.sftp_user
        password = decrypt_secret(self.config.sftp_pass)
        remote_path = self.config.remote_path
        
        try:
            client = self._create_ssh_client()
            client.connect(host, port=port, username=user, password=password)
            sftp = client.open_sftp()

            # Determine seeding path
            seeding_path = remote_path.replace("/main", "/seeding").replace("/downloaded", "/seeding")
            if "/seeding" not in seeding_path:
                seeding_path = remote_path + "/seeding"

            # Derived from remote path: Scripts path
            remote_base = remote_path.rsplit('/', 1)[0] if '/' in remote_path else remote_path
            remote_scripts_path = f"{remote_base}/scripts"
            
            try:
                sftp.mkdir(remote_scripts_path)
            except IOError:
                pass # Already exists
            
            client_type = self.config.torrent_client.client_type
            cleaner_script = "deluge_cleaner.py" if client_type == "Deluge" else "qbittorrent_cleaner.py"
            if getattr(sys, 'frozen', False):
                base_dir = sys._MEIPASS
            else:
                base_dir = os.path.join(os.path.dirname(__file__), "..", "..")
            local_cleaner_path = os.path.join(base_dir, "source_app", cleaner_script)

            remote_cleaner_path = f"{remote_scripts_path}/{cleaner_script}"
            remote_creds_path = f"{remote_scripts_path}/{client_type.lower()}_creds.json"
            
            if os.path.exists(local_cleaner_path):
                self._log(f"Uploading {cleaner_script} to remote")
                sftp.put(local_cleaner_path, remote_cleaner_path)
            else:
                self._log(f"Local cleaner script not found at {local_cleaner_path}, skipping upload", "warn")

            if client_type == "Deluge":
                deluge_host = self.config.torrent_client.deluge_host
                deluge_port = self.config.torrent_client.deluge_port
                deluge_time = self.config.torrent_client.max_seed_time
                deluge_ratio = self.config.torrent_client.max_seed_ratio
                deluge_creds = json.dumps(
                    {
                        "host": deluge_host,
                        "port": deluge_port,
                    }
                )
                with sftp.file(remote_creds_path, "w") as remote_creds_file:
                    remote_creds_file.write(deluge_creds)
                cmd = " ".join(
                    [
                        "python3",
                        shlex.quote(remote_cleaner_path),
                        "--creds-file",
                        shlex.quote(remote_creds_path),
                        "--dest",
                        shlex.quote(seeding_path),
                        "--max-seed-time",
                        shlex.quote(str(deluge_time)),
                        "--max-seed-ratio",
                        shlex.quote(str(deluge_ratio)),
                    ]
                )
            else:
                qbit_pass = decrypt_secret(self.config.torrent_client.qbit_pass)
                qbit_time = self.config.torrent_client.max_seed_time
                qbit_ratio = self.config.torrent_client.max_seed_ratio
                qbit_creds = json.dumps(
                    {
                        "host": self.config.torrent_client.qbit_url,
                        "username": self.config.torrent_client.qbit_user,
                        "password": qbit_pass,
                    }
                )
                with sftp.file(remote_creds_path, "w") as remote_creds_file:
                    remote_creds_file.write(qbit_creds)
                cmd = " ".join(
                    [
                        "python3",
                        shlex.quote(remote_cleaner_path),
                        "--creds-file",
                        shlex.quote(remote_creds_path),
                        "--dest",
                        shlex.quote(seeding_path),
                        "--max-seed-time",
                        shlex.quote(str(qbit_time)),
                        "--max-seed-ratio",
                        shlex.quote(str(qbit_ratio)),
                    ]
                )

            self._log(f"Executing remote cleanup for {client_type}")
            try:
                stdin, stdout, stderr = client.exec_command(cmd)
                exit_status = stdout.channel.recv_exit_status()
                
                out_str = stdout.read().decode()
                err_str = stderr.read().decode()
                
                if exit_status != 0:
                    self._log(f"Remote cleanup failed (Exit {exit_status})", "error")
                    self._log(f"STDOUT: {out_str}")
                    self._log(f"STDERR: {err_str}", "error")
                else:
                    self._log("Remote cleanup successful")
                    self._log(out_str)
            finally:
                try:
                    sftp.remove(remote_creds_path)
                except Exception:
                    pass
                sftp.close()
                client.close()
        except Exception as e:
            self._log(f"Remote cleanup failed: {str(e)}", "warn")

    def _step_extraction_and_sorting(self):
        self._update_progress(50, "Extracting and sorting archives")
        local_path = self.config.local_download_path
        unrar_path = self.config.unrar_path
        
        # Subfolders as in V1
        staging_tv = self.config.paths.tv_source or os.path.join(local_path, "TV")
        staging_movies = self.config.paths.movies_source or os.path.join(local_path, "Movies")
        staging_music = self.config.paths.music_source or os.path.join(local_path, "Music")
        
        for p in [staging_tv, staging_movies, staging_music]:
            os.makedirs(p, exist_ok=True)

        extraction_targets = [("tv", staging_tv), ("movies", staging_movies), ("music", staging_music)]

        # 1. Sorting loose items in the root of LocalDownloadPath (if any)
        # Category directory names used by torrent clients (e.g. qBittorrent save-path categories)
        _CATEGORY_TV     = {"tv", "television", "shows", "series", "episodes"}
        _CATEGORY_MOVIES = {"movies", "movie", "films", "film"}
        _CATEGORY_MUSIC  = {"music", "audio"}

        staging_paths = {staging_tv, staging_movies, staging_music}

        for item in os.listdir(local_path):
            item_path = os.path.join(local_path, item)

            # Skip items that ARE a staging directory (compare case-insensitively for Windows)
            if any(item_path.lower() == p.lower() for p in staging_paths):
                continue

            name_lower = item.lower()

            # Category-named subdirectory: unpack contents directly into the right staging area
            if os.path.isdir(item_path):
                if name_lower in _CATEGORY_TV:
                    cat_target = staging_tv
                elif name_lower in _CATEGORY_MOVIES:
                    cat_target = staging_movies
                elif name_lower in _CATEGORY_MUSIC:
                    cat_target = staging_music
                else:
                    cat_target = None

                if cat_target:
                    for sub in os.listdir(item_path):
                        src = os.path.join(item_path, sub)
                        dst = os.path.join(cat_target, sub)
                        try:
                            self._log(f"Sorting {sub} → {cat_target} (via category folder '{item}')")
                            shutil.move(src, dst)
                        except Exception as e:
                            self._log(f"Failed to sort {sub}: {str(e)}", "error")
                    try:
                        os.rmdir(item_path)
                    except Exception:
                        pass
                    continue

                # Unknown directory — fall back to name heuristic
                if re.search(r"S\d{1,2}E\d{1,2}|S\d{1,2}|[0-9]{1,2}x[0-9]{1,2}", item, re.I):
                    target = staging_tv
                else:
                    target = staging_movies
                try:
                    self._log(f"Sorting {item} to {target}")
                    shutil.move(item_path, os.path.join(target, item))
                except Exception as e:
                    self._log(f"Failed to sort {item}: {str(e)}", "error")

            elif os.path.isfile(item_path):
                ext = os.path.splitext(item)[1].lower()
                target = None
                if ext in [".mp4", ".mkv", ".avi"]:
                    if re.search(r"S\d{1,2}E\d{1,2}|S\d{1,2}|[0-9]{1,2}x[0-9]{1,2}", item, re.I):
                        target = staging_tv
                    else:
                        target = staging_movies
                elif ext in [".mp3", ".flac", ".m4a"]:
                    target = staging_music
                if target:
                    try:
                        self._log(f"Sorting {item} to {target}")
                        shutil.move(item_path, os.path.join(target, item))
                    except Exception as e:
                        self._log(f"Failed to sort {item}: {str(e)}", "error")

        # 2. Extraction (Recursive in staging areas after sorting)
        for media_type, folder in extraction_targets:
            if not os.path.exists(folder):
                continue
            self._log(f"Scanning {media_type} staging for archives: {folder}")
            for root, _, files in os.walk(folder):
                for file in files:
                    if file.lower().endswith((".rar", ".zip")):
                        archive_path = os.path.join(root, file)
                        self._log(f"Extracting {archive_path} to {root}")
                        try:
                            if file.lower().endswith(".rar"):
                                subprocess.run([unrar_path, "x", "-o-", archive_path, root + os.sep, "-y"], check=True, capture_output=True)
                            else:
                                shutil.unpack_archive(archive_path, root)
                        except Exception as e:
                            self._log(f"Failed to extract {archive_path}: {str(e)}", "error")

        # 3. Sample Removal (V1 new_archive_extract.ps1 Step 2)
        for _, folder in extraction_targets:
            self._remove_samples(folder)

    def _remove_samples(self, folder: str):
        for root, _, files in os.walk(folder):
            for file in files:
                if "sample" in file.lower():
                    # Check if a non-sample version exists
                    clean_name = re.sub(r'[-._ ]?sample', '', file, flags=re.I)
                    if clean_name != file and os.path.exists(os.path.join(root, clean_name)):
                        self._log(f"Removing redundant sample: {file}")
                        try:
                            os.remove(os.path.join(root, file))
                        except:
                            pass

    def _step_import_triggers(self):
        self._update_progress(70, "Processing final moves and import triggers")

        # Mapping: (type, source_staging, target_import, extensions)
        configs = [
            ("tv",     self.config.paths.tv_source,     self.config.paths.tv_import,     [".mp4", ".mkv", ".avi"]),
            ("movies", self.config.paths.movies_source, self.config.paths.movies_import, [".mp4", ".mkv", ".avi"]),
            ("music",  self.config.paths.music_source,  self.config.paths.music_import,  [".mp3", ".flac", ".m4a", ".wav"]),
        ]

        for media_type, source, target, exts in configs:
            if not target:
                continue

            os.makedirs(target, exist_ok=True)
            self._sweep_stale_rejects(target, media_type)

            if source and os.path.exists(source):
                self._log(f"Processing {media_type} moves to {target}")

                current_moved = set()
                for root, _, files in os.walk(source):
                    for f in files:
                        if any(f.lower().endswith(ext) for ext in exts):
                            src_file = os.path.join(root, f)

                            if self._should_quarantine(f):
                                self._quarantine(src_file, media_type, "Filter tag detected (sample/trailer)")
                                continue

                            folder_name = os.path.splitext(f)[0]
                            dest_folder = os.path.join(target, folder_name)
                            os.makedirs(dest_folder, exist_ok=True)
                            dest_file = os.path.join(dest_folder, f)
                            try:
                                if os.path.exists(dest_file):
                                    self._log(f"Skipping {f}, already exists in {dest_folder}", "warn")
                                else:
                                    shutil.move(src_file, dest_file)
                                    current_moved.add(dest_folder)
                                    self._log(f"Moved {f} to {dest_folder}")
                            except Exception as e:
                                self._log(f"Failed to move {f}: {str(e)}", "error")

                for path in list(current_moved):
                    leaf = os.path.basename(path)
                    if media_type == "tv" and self._is_tv_season_pack_no_episode(leaf):
                        self._quarantine(path, media_type, "Season pack without episode")
                    elif media_type == "movies" and self._is_movie_unparseable(path):
                        self._quarantine(path, media_type, "Likely unparseable movie name")

                self._cleanup_staging(source)

        # Trigger arr imports for all import dirs that have content
        self._do_arr_triggers()

    def _do_arr_triggers(self):
        """Scan all configured import directories and trigger Sonarr/Radarr/Lidarr."""
        arr_configs = [
            ("tv",     self.config.paths.tv_import,     "Sonarr", self.config.sonarr, "DownloadedEpisodesScan"),
            ("movies", self.config.paths.movies_import, "Radarr", self.config.radarr, "DownloadedMoviesScan"),
            ("music",  self.config.paths.music_import,  "Lidarr", self.config.lidarr, "DownloadedAlbumsScan"),
        ]

        for media_type, import_dir, app_name, app_cfg, command in arr_configs:
            if not import_dir or not app_cfg.enabled or not app_cfg.url or not app_cfg.api_key:
                continue

            if not os.path.isdir(import_dir):
                self._log(f"{app_name}: import dir {import_dir} not found, skipping", "warn")
                continue

            import_subdirs = sorted(
                os.path.join(import_dir, d)
                for d in os.listdir(import_dir)
                if os.path.isdir(os.path.join(import_dir, d))
            )
            if not import_subdirs:
                self._log(f"{app_name}: import dir is empty, skipping trigger")
                continue

            api_key = decrypt_secret(app_cfg.api_key)
            for import_path in import_subdirs:
                self._trigger_and_wait(app_name, app_cfg.url, api_key, command, import_path, media_type)

    def _media_extensions_for_type(self, media_type: str) -> Tuple[str, ...]:
        mapping = {
            "tv": (".mp4", ".mkv", ".avi"),
            "movies": (".mp4", ".mkv", ".avi"),
            "music": (".mp3", ".flac", ".m4a", ".wav"),
        }
        return mapping.get(media_type, ())

    def _path_contains_media_files(self, path: str, media_type: str) -> bool:
        if not os.path.exists(path):
            return False

        exts = self._media_extensions_for_type(media_type)
        if not exts:
            return False

        for root, _, files in os.walk(path):
            for name in files:
                if name.lower().endswith(exts):
                    return True
        return False

    def trigger_arr_imports(self):
        """Public entry point: trigger Sonarr/Radarr/Lidarr without running the full workflow."""
        if self.state.running:
            return

        self.state.running = True
        self.state.start_time = time.time()
        self.state.percent = 0
        self.state.message = "Triggering Arr imports"
        self.state.exit_code = None
        self.state.logs = []
        self._smb_connections = []

        try:
            self._connect_smb_shares()
            self._do_arr_triggers()
            self._update_progress(100, "Arr import triggers completed")
            self.state.exit_code = 0
        except Exception as e:
            self._log(f"Arr trigger failed: {str(e)}", "error")
            self.state.exit_code = 1
            self.state.message = f"Error: {str(e)}"
        finally:
            self._disconnect_smb_shares()
            self.state.running = False
            self.state.end_time = time.time()

    def _sweep_stale_rejects(self, import_root: str, media_type: str):
        if not os.path.exists(import_root): return
        for item in os.listdir(import_root):
            path = os.path.join(import_root, item)
            if os.path.isdir(path):
                if self._should_quarantine(item):
                    self._quarantine(path, media_type, "Stale reject pattern")

    def _should_quarantine(self, name: str) -> bool:
        lower = name.lower()
        # V1 regex equivalents
        if re.search(r'(^|[\s._\-\[\(])sample([\s._\-\]\)]|$)', lower): return True
        if "trailer" in lower: return True
        return False

    def _is_tv_season_pack_no_episode(self, name: str) -> bool:
        has_season = re.search(r'\bS\d{1,2}\b', name, re.I)
        has_episode = re.search(r'\bE\d{1,3}\b', name, re.I)
        return bool(has_season and not has_episode)

    def _is_movie_unparseable(self, path: str) -> bool:
        name = os.path.basename(path)
        if re.search(r'(19|20)\d{2}', name): return False
        
        # Check files inside
        for f in os.listdir(path):
            if re.search(r'(19|20)\d{2}', f): return False
        
        # All caps/no year heuristic
        if re.match(r'^[A-Z0-9 ._\-\(\)\[\]&]+$', name): return True
        return False

    def _quarantine(self, path: str, media_type: str, reason: str):
        import_roots = {
            "tv": self.config.paths.tv_import,
            "movies": self.config.paths.movies_import,
            "music": self.config.paths.music_import,
        }
        preferred_import = import_roots.get(media_type) or self.config.local_download_path or os.getcwd()
        base_import = os.path.dirname(preferred_import.rstrip("\\/")) or preferred_import
        q_root = os.path.join(base_import, "Quarantine", media_type)
        os.makedirs(q_root, exist_ok=True)
        
        self._log(f"Quarantining {path}: {reason}", "warn")
        dest = os.path.join(q_root, os.path.basename(path))
        if os.path.exists(dest):
             dest = dest + "_" + datetime.now().strftime("%Y%m%d_%H%M%S")
        
        try:
            shutil.move(path, dest)
        except Exception as e:
            self._log(f"Failed to quarantine: {str(e)}", "error")

    def _trigger_and_wait(self, app_name: str, url: str, api_key: str, command: str, path: str, media_type: str):
        headers = {"X-Api-Key": api_key}
        api_ver = "v3" if app_name != "Lidarr" else "v1"
        endpoint = f"{url.rstrip('/')}/api/{api_ver}/command"

        payload = {"name": command, "path": path, "importMode": "Move"}
        try:
            self._log(f"Triggering {app_name} for {path}")
            resp = requests.post(endpoint, json=payload, headers=headers, timeout=15)
            if resp.status_code not in [200, 201, 202]:
                self._log(f"{app_name} trigger failed (HTTP {resp.status_code}): {resp.text}", "error")
                if self._path_contains_media_files(path, media_type):
                    self._quarantine(path, media_type, f"{app_name} trigger failed")
                return

            task_id = resp.json().get("id")
            if not task_id:
                if self._path_contains_media_files(path, media_type):
                    self._quarantine(path, media_type, f"{app_name} trigger returned no task id")
                return

            # Wait loop (up to 5 mins)
            for _ in range(60):
                time.sleep(5)
                t_resp = requests.get(f"{endpoint}/{task_id}", headers=headers, timeout=10)
                if t_resp.status_code == 200:
                    status = t_resp.json().get("status")
                    if status == "completed":
                        if self._path_contains_media_files(path, media_type):
                            self._log(
                                f"{app_name} scan completed but files remain in {os.path.basename(path)}; quarantining",
                                "warn",
                            )
                            self._quarantine(path, media_type, f"{app_name} could not import or match files")
                        else:
                            self._log(f"{app_name} import completed for {os.path.basename(path)}")
                        return
                    if status == "failed":
                        self._log(f"{app_name} import FAILED for {os.path.basename(path)}: {t_resp.json().get('message')}", "error")
                        if self._path_contains_media_files(path, media_type):
                            self._quarantine(path, media_type, f"{app_name} import failed")
                        return
                else:
                    break
            self._log(f"{app_name} wait timeout for {os.path.basename(path)}", "warn")
            if self._path_contains_media_files(path, media_type):
                self._quarantine(path, media_type, f"{app_name} import timeout")
        except Exception as e:
            self._log(f"Error triggering {app_name}: {str(e)}", "error")
            if self._path_contains_media_files(path, media_type):
                self._quarantine(path, media_type, f"{app_name} trigger error")

    def _cleanup_staging(self, folder: str):
        try:
            for item in os.listdir(folder):
                path = os.path.join(folder, item)
                if os.path.isdir(path): shutil.rmtree(path)
                else: os.remove(path)
        except Exception as e:
            self._log(f"Staging cleanup warning for {folder}: {str(e)}", "warn")
