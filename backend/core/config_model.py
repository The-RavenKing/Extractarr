from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class WebAuthSettings(BaseModel):
    auth_enabled: bool = True
    username: str = "admin"
    password_hash: str = ""
    secret_key: str = Field(default_factory=lambda: "")
    host: str = "127.0.0.1"
    port: int = 0


class TorrentClientSettings(BaseModel):
    client_type: str = "Deluge"  # Deluge, qBittorrent
    deluge_host: str = ""
    deluge_port: str = ""
    qbit_url: str = ""
    qbit_user: str = ""
    qbit_pass: str = ""
    max_seed_time: int = 14  # days
    max_seed_ratio: float = 2.0


class MediaAppServer(BaseModel):
    url: str = ""
    api_key: str = ""
    enabled: bool = True


class MediaPaths(BaseModel):
    tv_source: str = ""
    tv_import: str = ""
    movies_source: str = ""
    movies_import: str = ""
    music_source: str = ""
    music_import: str = ""


class ExtractarrConfig(BaseModel):
    sftp_host: str = ""
    sftp_port: int = 22
    sftp_user: str = ""
    sftp_pass: str = ""
    remote_path: str = "/downloads"
    sftp_host_key: str = ""

    local_download_path: str = ""
    smb_user: str = ""
    smb_pass: str = ""

    paths: MediaPaths = Field(default_factory=MediaPaths)

    winscp_path: str = "C:\\Program Files (x86)\\WinSCP\\WinSCP.com"
    unrar_path: str = "C:\\Program Files\\WinRAR\\UnRAR.exe"

    torrent_client: TorrentClientSettings = Field(default_factory=TorrentClientSettings)

    sonarr: MediaAppServer = Field(default_factory=MediaAppServer)
    radarr: MediaAppServer = Field(default_factory=MediaAppServer)
    lidarr: MediaAppServer = Field(default_factory=MediaAppServer)

    enable_scheduling: bool = False
    schedule_time: str = "01:00"
    task_name: str = "DailyExtractarr"

    web: WebAuthSettings = Field(default_factory=WebAuthSettings)
