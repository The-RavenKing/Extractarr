# Extractarr Workflow Documentation

This document outlines the end-to-end process that occurs when the Extractarr workflow is triggered (either manually via the Dashboard or automatically via the Scheduler).

## Phase 0: Initialization & Environment Setup
1.  **Configuration Loading**: The engine loads the latest settings from `data/config.json`.
2.  **Secret Decryption**: Encrypted secrets (SFTP passwords, API keys, SMB passwords) are decrypted in memory using Windows DPAPI (or mock decryption on Linux).
3.  **SMB Authentication (Windows Only)**: 
    - If the local paths (Staging or Import) are UNC network shares (e.g., `\\192.168.1.228\Video`), the engine executes `net use` commands.
    - This ensures the background service has authenticated access to your NAS or file server.

---

## Phase 1: SFTP Download
1.  **Remote Connection**: A secure SFTP connection is established to your seedbox/remote server.
2.  **Recursive Sync**: 
    - The engine scans the **Remote Root Path** (e.g., `/downloads/main`).
    - It performs a recursive download of all files and directories into your **Initial Download Area**.
    - Folder structures (like `TV/`, `Movies/`) are preserved exactly as they appear on the remote server.

---

## Phase 2: Remote Torrent Cleanup
1.  **Cleaner Deployment**: The engine uploads the latest version of `deluge_cleaner.py` or `qbittorrent_cleaner.py` to a `scripts/` folder on your remote server.
2.  **Dependency Check**: It ensures the remote server has the necessary Python libraries (`deluge-client` or `qbittorrent-api`) installed.
3.  **Cleanup Execution**: The script runs on the remote server with your configured limits:
    - **Move to Seeding**: Torrents that are not yet eligible for deletion are moved to a remote `/seeding` directory to keep the main download folder clean.
    - **Auto-Deletion**: Torrents (and their data) are permanently deleted if:
        - They have been seeded longer than the **Max Seed Time** (default 14 days).
        - **OR** they have reached the **Max Seed Ratio** (default 2.0).

---

## Phase 3: Extraction & Internal Sorting
1.  **Recursive Extraction**:
    - The engine scans the local staging areas for `.rar` and `.zip` files.
    - Archives are extracted in-place using `unrar` or internal zip libraries.
2.  **Sample Removal**:
    - The engine identifies "sample" files (e.g., `movie-sample.mkv`).
    - If a non-sample version of the same file exists in the folder, the sample is automatically deleted to save space and prevent import errors.
3.  **Heuristic Sorting**:
    - If files are found in the root of the download area, the engine analyzes the filenames.
    - Items with "S01E01" style patterns are moved to **TV Staging**.
    - Most other video files are moved to **Movies Staging**.

---

## Phase 4: Final Move & App Triggers
1.  **Stale Reject Sweep**: Before moving new files, the engine cleans up the Import folders of any old items that were previously rejected or quarantined.
2.  **Re-Folding (Loose Files)**:
    - Sonarr/Radarr prefer movies and episodes to be in their own folders.
    - Any "loose" files (e.g., `Movie.Name.2024.mkv` sitting directly in staging) are moved into a new subfolder named after the file.
3.  **Quarantine Filters**:
    - Folders are scanned for "Sample" or "Trailer" tags.
    - TV items that look like "Season Packs" (no specific episode number) are moved to **Quarantine** to prevent Sonarr from becoming confused.
    - Movies with unparseable names (all-caps, no year) are also quarantined for manual review.
4.  **App API Scans**:
    - The engine sends a `DownloadedMoviesScan` (Radarr) or `DownloadedEpisodesScan` (Sonarr) command to the respective media app.
    - **Wait for Completion**: The engine waits for the app to acknowledge that the import is finished before proceeding.
    - If an import fails, the item is moved to **Quarantine** and logged.

---

## Phase 5: Cleanup & Finalization
1.  **Staging Cleanup**: Once files are successfully moved to the Import area and scanned, the engine wipes the Staging folders to prepare for the next run.
2.  **SMB Disconnection**: Active network share connections are closed.
3.  **State Reporting**: The final status (Exit Code 0 for success) and a complete log of every action are saved and displayed on the Dashboard.
