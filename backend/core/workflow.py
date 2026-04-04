import os
import shutil
import logging
import time
import requests
import paramiko
import re
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
            client = paramiko.SSHClient()
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            client.connect(host, port=port, username=user, password=password, timeout=30)
            sftp = client.open_sftp()
            
            self._log(f"Connected to SFTP {host}")
            
            def download_dir(remote_dir, local_dir):
                if not os.path.exists(local_dir):
                    os.makedirs(local_dir)
                for entry in sftp.listdir_attr(remote_dir):
                    rempath = remote_dir + "/" + entry.filename
                    locpath = os.path.join(local_dir, entry.filename)
                    if paramiko.SAttribute(entry.st_mode).is_dir():
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
                if paramiko.SAttribute(entry.st_mode).is_dir():
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
            client = paramiko.SSHClient()
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            client.connect(host, port=port, username=user, password=password)
            sftp = client.open_sftp()

            # Determine seeding path
            seeding_path = remote_path.replace("/main", "/seeding").replace("/downloaded", "/seeding")
            if "/seeding" not in seeding_path:
                 seeding_path = "/home31/arikitty13/downloads/seeding" # Hardcoded fallback from v1
            
            # Derived from v1: Scripts path
            remote_base = remote_path.rsplit('/', 1)[0] if '/' in remote_path else "/home31/arikitty13/downloads"
            remote_scripts_path = f"{remote_base}/scripts"
            
            try:
                sftp.mkdir(remote_scripts_path)
            except IOError:
                pass # Already exists
            
            client_type = self.config.torrent_client.client_type
            cleaner_script = "deluge_cleaner.py" if client_type == "Deluge" else "qbittorrent_cleaner.py"
            local_cleaner_path = os.path.join("source_app", "Users", "AriKi", "Documents", "Extractor", cleaner_script)
            
            # If not in the source_app (e.g. deployed), look in current dir or similar
            if not os.path.exists(local_cleaner_path):
                local_cleaner_path = cleaner_script

            remote_cleaner_path = f"{remote_scripts_path}/{cleaner_script}"
            
            if os.path.exists(local_cleaner_path):
                self._log(f"Uploading {cleaner_script} to remote")
                sftp.put(local_cleaner_path, remote_cleaner_path)
            else:
                self._log(f"Local cleaner script not found at {local_cleaner_path}, skipping upload", "warn")

            if client_type == "Deluge":
                # Ensure deluge-client is installed
                client.exec_command("pip3 install --user deluge-client")
                deluge_host = self.config.torrent_client.deluge_host or "169.150.223.207"
                deluge_port = self.config.torrent_client.deluge_port or "25256"
                deluge_time = self.config.torrent_client.max_seed_time
                deluge_ratio = self.config.torrent_client.max_seed_ratio
                cmd = f"python3 {remote_cleaner_path} --host {deluge_host} --port {deluge_port} --dest {seeding_path} --max-seed-time {deluge_time} --max-seed-ratio {deluge_ratio}"
            else:
                # qBittorrent
                client.exec_command("pip3 install --user qbittorrent-api")
                qbit_pass = decrypt_secret(self.config.torrent_client.qbit_pass)
                qbit_time = self.config.torrent_client.max_seed_time
                qbit_ratio = self.config.torrent_client.max_seed_ratio
                cmd = f"python3 {remote_cleaner_path} --host {self.config.torrent_client.qbit_url} --username {self.config.torrent_client.qbit_user} --password {qbit_pass} --dest {seeding_path} --max-seed-time {qbit_time} --max-seed-ratio {qbit_ratio}"

            self._log(f"Executing remote cleanup: {cmd}")
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

        # 1. Extraction (Recursive in staging areas)
        extraction_targets = [
            ("tv", staging_tv),
            ("movies", staging_movies),
            ("music", staging_music)
        ]
        
        for media_type, folder in extraction_targets:
            if not os.path.exists(folder): continue
            self._log(f"Scanning {media_type} staging for archives: {folder}")
            for root, _, files in os.walk(folder):
                for file in files:
                    if file.lower().endswith((".rar", ".zip")):
                        archive_path = os.path.join(root, file)
                        self._log(f"Extracting {archive_path} to {root}")
                        try:
                            if file.lower().endswith(".rar"):
                                subprocess.run([unrar_path, "x", "-o-", archive_path, root + os.sep, "-y"], check=True, capture_output=True)
                            else: # zip
                                shutil.unpack_archive(archive_path, root)
                        except Exception as e:
                            self._log(f"Failed to extract {archive_path}: {str(e)}", "error")

        # 2. Sample Removal (V1 new_archive_extract.ps1 Step 2)
        for _, folder in extraction_targets:
            self._remove_samples(folder)

        # 3. Sorting loose items in the root of LocalDownloadPath (if any)
        for item in os.listdir(local_path):
            item_path = os.path.join(local_path, item)
            if item in ["TV", "Movies", "Music"] or item_path in [staging_tv, staging_movies, staging_music]:
                continue
            
            target = None
            if os.path.isdir(item_path):
                # Heuristic
                if re.search(r"S\d{1,2}E\d{1,2}|S\d{1,2}|[0-9]{1,2}x[0-9]{1,2}", item, re.I):
                    target = staging_tv
                else:
                    target = staging_movies
            elif os.path.isfile(item_path):
                ext = os.path.splitext(item)[1].lower()
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
        
        # Mapping: (type, source_staging, target_import, extensions, app_name, app_cfg, command)
        configs = [
            ("tv", self.config.paths.tv_source, self.config.paths.tv_import, [".mp4", ".mkv", ".avi"], "Sonarr", self.config.sonarr, "DownloadedEpisodesScan"),
            ("movies", self.config.paths.movies_source, self.config.paths.movies_import, [".mp4", ".mkv", ".avi"], "Radarr", self.config.radarr, "DownloadedMoviesScan"),
            ("music", self.config.paths.music_source, self.config.paths.music_import, [".mp3", ".flac", ".m4a", ".wav"], "Lidarr", self.config.lidarr, "DownloadedAlbumsScan"),
        ]

        for media_type, source, target, exts, app_name, app_cfg, command in configs:
            if not source or not target or not os.path.exists(source):
                continue
            
            os.makedirs(target, exist_ok=True)
            self._sweep_stale_rejects(target, media_type)
            
            self._log(f"Processing {media_type} moves to {target}")
            
            # Step 1: Move media files from staging to import
            current_moved = set()
            for root, _, files in os.walk(source):
                for f in files:
                    if any(f.lower().endswith(ext) for ext in exts):
                        src_file = os.path.join(root, f)
                        
                        # V1: Check sample tag
                        if self._should_quarantine(f):
                            self._quarantine(src_file, media_type, "Filter tag detected (sample/trailer)")
                            continue
                        
                        # Move loose file to its own folder in import area
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

            # Step 2: Quarantine filters on the moved folders
            filtered_paths = set()
            for path in current_moved:
                leaf = os.path.basename(path)
                if media_type == "tv" and self._is_tv_season_pack_no_episode(leaf):
                    self._quarantine(path, media_type, "Season pack without episode")
                elif media_type == "movies" and self._is_movie_unparseable(path):
                    self._quarantine(path, media_type, "Likely unparseable movie name")
                else:
                    filtered_paths.add(path)

            # Step 3: Trigger App Import and WAIT
            if app_cfg.enabled and app_cfg.url and app_cfg.api_key and filtered_paths:
                api_key = decrypt_secret(app_cfg.api_key)
                for path in filtered_paths:
                    self._trigger_and_wait(app_name, app_cfg.url, api_key, command, path, media_type)
            
            # Step 4: Cleanup staging
            self._cleanup_staging(source)

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
        # Quarantine root relative to TV import
        base_import = os.path.dirname(self.config.paths.tv_import) if self.config.paths.tv_import else "C:\\Downloads\\Quarantine"
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
        endpoint = f"{url}/api/{api_ver}/command"
        
        payload = {"name": command, "path": path, "importMode": "Move"}
        try:
            self._log(f"Triggering {app_name} for {path}")
            resp = requests.post(endpoint, json=payload, headers=headers, timeout=15)
            if resp.status_code not in [200, 201, 202]:
                self._log(f"{app_name} trigger failed: {resp.text}", "error")
                return

            task_id = resp.json().get("id")
            if not task_id: return

            # Wait loop (up to 5 mins)
            for _ in range(60):
                time.sleep(5)
                t_resp = requests.get(f"{endpoint}/{task_id}", headers=headers, timeout=10)
                if t_resp.status_code == 200:
                    status = t_resp.json().get("status")
                    if status == "completed":
                        self._log(f"{app_name} import completed for {os.path.basename(path)}")
                        return
                    if status == "failed":
                        self._log(f"{app_name} import FAILED for {os.path.basename(path)}: {t_resp.json().get('message')}", "error")
                        # Quarantine on failure as in V1
                        self._quarantine(path, media_type, f"{app_name} scan failed")
                        return
                else:
                    break
            self._log(f"{app_name} wait timeout for {os.path.basename(path)}", "warn")
        except Exception as e:
            self._log(f"Error triggering {app_name}: {str(e)}", "error")

    def _cleanup_staging(self, folder: str):
        try:
            for item in os.listdir(folder):
                path = os.path.join(folder, item)
                if os.path.isdir(path): shutil.rmtree(path)
                else: os.remove(path)
        except Exception as e:
            self._log(f"Staging cleanup warning for {folder}: {str(e)}", "warn")

