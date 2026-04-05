#!/usr/bin/env python3
import sys
import os
import argparse
import logging
import time
import json
import qbittorrentapi

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

TARGET_CATEGORIES = {"tv", "movies", "music"}

def load_creds_file(path):
    if not path:
        return {}
    try:
        # Accept UTF-8 files with or without BOM (PowerShell 5 UTF8 adds BOM).
        with open(path, "r", encoding="utf-8-sig") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return {}
        return data
    except Exception as e:
        logger.error(f"Failed to read creds file '{path}': {e}")
        return {}

def main():
    parser = argparse.ArgumentParser(description="Move and cleanup qBittorrent torrents.")
    parser.add_argument("--host", help="qBittorrent host URL (e.g., http://localhost:8080)")
    parser.add_argument("--username", help="qBittorrent username")
    parser.add_argument("--password", help="qBittorrent password")
    parser.add_argument("--creds-file", help="Path to JSON file containing host/username/password")
    parser.add_argument("--dest", required=True, help="Destination directory for completed torrents")
    parser.add_argument("--max-seed-time", type=float, default=14.0, help="Maximum seeding time in days")
    parser.add_argument("--max-seed-ratio", type=float, default=2.0, help="Maximum seeding ratio")
    parser.add_argument("--dry-run", action="store_true", help="Simulate moves without executing")

    args = parser.parse_args()
    file_creds = load_creds_file(args.creds_file)
    host = args.host or file_creds.get("host") or os.environ.get("QBIT_HOST")
    username = args.username or file_creds.get("username") or os.environ.get("QBIT_USERNAME")
    password = args.password or file_creds.get("password") or os.environ.get("QBIT_PASSWORD")

    if not host or not username or not password:
        logger.error("Missing qBittorrent credentials (host/username/password).")
        sys.exit(1)

    max_age_seconds = args.max_seed_time * 86400
    max_ratio = args.max_seed_ratio

    # Instantiate the Client
    try:
        qbt_client = qbittorrentapi.Client(
            host=host,
            username=username,
            password=password
        )
        qbt_client.auth_log_in()
        logger.info(f"Connected to qBittorrent: {qbt_client.app.version}")
        logger.info(f"Seeding limits: {args.max_seed_time} days or {max_ratio} ratio")
    except Exception as e:
        logger.error(f"Failed to connect/login to qBittorrent: {e}")
        sys.exit(1)

    try:
        # qBittorrent categories map to our labels (tv, movies, music).
        # We want torrents that are 'completed' basically. 
        # qBit filter 'completed' includes seeding.
        torrents = qbt_client.torrents_info(status_filter='completed')
        
        count = 0
        had_errors = False
        for torrent in torrents:
            category = (torrent.category or "").strip().lower()
            name = torrent.name
            current_path = torrent.save_path or ""
            
            # Check for Deletion based on time or ratio
            current_time = time.time()
            
            # Use completion time if available, fallback to added_on
            completion_time = torrent.completion_on if torrent.completion_on > 0 else torrent.added_on
            age_seconds = current_time - completion_time if completion_time > 0 else 0
            ratio = torrent.ratio
            
            time_limit_met = age_seconds > max_age_seconds
            ratio_limit_met = ratio >= max_ratio
            
            if time_limit_met or ratio_limit_met:
                reason = f"age ({age_seconds/86400:.2f} days > {args.max_seed_time} days)" if time_limit_met else f"ratio ({ratio:.2f} >= {max_ratio})"
                logger.warning(f"Torrent {name} met cleanup limit: {reason}. Deleting torrent AND data.")
                
                if args.dry_run:
                    logger.info(f"[DRY-RUN] Would DELETE {name} and DATA.")
                else:
                    try:
                        torrent.delete(hash=torrent.hash, delete_files=True)
                        logger.info(f"Deleted {name} and its data.")
                    except Exception as e:
                        logger.error(f"Failed to delete {name}: {e}")
                        had_errors = True
                
                count += 1
                continue

            # Filter by our target categories for moving to seeding area
            if category not in TARGET_CATEGORIES:
                continue

            # Normalize paths
            current_path_norm = os.path.normpath(current_path)
            dest_base_norm = os.path.normpath(args.dest)
            
            # Construct target path: dest/category (e.g., /media/seeding/tv)
            target_path = os.path.join(dest_base_norm, category)
            
            # Check if already there
            try:
                if os.path.commonpath([current_path_norm, target_path]) == target_path:
                    continue
            except ValueError:
                pass
            
            if current_path_norm == target_path or current_path_norm.startswith(target_path + os.sep):
                continue

            logger.info(f"Found candidate to move: {name} [{category}] in {current_path}")

            if args.dry_run:
                logger.info(f"[DRY-RUN] Would move {name} to {target_path}")
            else:
                try:
                    # qBittorrent set_location moves the files
                    logger.info(f"Moving {name} to {target_path}...")
                    torrent.set_location(location=target_path)
                    logger.info(f"Successfully initiated move for {name}")
                except Exception as e:
                    logger.error(f"Failed to move {name}: {e}")
                    had_errors = True
            
            count += 1

        logger.info(f"Processing complete. {count} torrents processed.")
        if had_errors:
            sys.exit(2)

    except Exception as e:
        logger.error(f"Error during processing: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
