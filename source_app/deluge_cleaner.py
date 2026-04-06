#!/usr/bin/env python3
import sys
import os
import argparse
import logging
import time
import json
from deluge_client import DelugeRPCClient

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

TARGET_LABELS = {"tv", "movies", "music"}

def load_creds_file(path):
    if not path:
        return {}
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception as e:
        logger.error(f"Failed to read creds file '{path}': {e}")
        return {}

def _decode_value(value):
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value

def _get_torrent_field(data, field_name):
    value = data.get(field_name)
    if value is None:
        value = data.get(field_name.encode("utf-8"))
    return _decode_value(value)

def get_auth_from_config():
    """Attempts to read the Deluge auth file for local credentials."""
    auth_path = os.path.expanduser("~/.config/deluge/auth")
    if not os.path.exists(auth_path):
        return None, None

    try:
        with open(auth_path, 'r') as f:
            for line in f:
                if line.strip() and not line.startswith('#'):
                    parts = line.split(':')
                    if len(parts) >= 2 and parts[0] == "localclient":
                        return parts[0], parts[1].strip()
    except Exception as e:
        logger.error(f"Failed to read auth file: {e}")
    
    return None, None

def main():
    parser = argparse.ArgumentParser(description="Move and cleanup Deluge torrents.")
    parser.add_argument("--host", default="127.0.0.1", help="Deluge daemon host")
    parser.add_argument("--port", type=int, default=58846, help="Deluge daemon port")
    parser.add_argument("--username", help="Deluge username")
    parser.add_argument("--password", help="Deluge password")
    parser.add_argument("--creds-file", help="Path to JSON file containing host/port/username/password")
    parser.add_argument("--dest", required=True, help="Destination directory for completed torrents")
    parser.add_argument("--max-seed-time", type=float, default=14.0, help="Maximum seeding time in days")
    parser.add_argument("--max-seed-ratio", type=float, default=2.0, help="Maximum seeding ratio")
    parser.add_argument("--dry-run", action="store_true", help="Simulate moves without executing")

    args = parser.parse_args()

    file_creds = load_creds_file(args.creds_file)
    host = args.host if args.host != "127.0.0.1" else file_creds.get("host", args.host)
    port = args.port if args.port != 58846 else int(file_creds.get("port", args.port))
    username = args.username or file_creds.get("username")
    password = args.password or file_creds.get("password")

    if not username or not password:
        local_user, local_pass = get_auth_from_config()
        if local_user and local_pass:
            username = local_user
            password = local_pass
        else:
            logger.error("Could not find credentials.")
            sys.exit(1)

    max_age_seconds = args.max_seed_time * 86400
    max_ratio = args.max_seed_ratio

    try:
        client = DelugeRPCClient(host, port, username, password)
        client.connect()
        logger.info("Connected to Deluge daemon.")
        logger.info(f"Seeding limits: {args.max_seed_time} days or {max_ratio} ratio")
    except Exception as e:
        logger.error(f"Failed to connect to Deluge: {e}")
        sys.exit(1)

    try:
        keys = ["name", "label", "save_path", "state", "progress", "time_added", "ratio"]
        torrents = client.core.get_torrents_status({}, keys)

        count = 0
        had_errors = False
        for torrent_id, data in torrents.items():
            label = str(_get_torrent_field(data, "label") or "").strip().lower()
            name = str(_get_torrent_field(data, "name") or "")
            current_path = str(_get_torrent_field(data, "save_path") or "")
            state = str(_get_torrent_field(data, "state") or "")
            
            # Deletion logic
            current_time = time.time()
            time_added = _get_torrent_field(data, "time_added")
            try:
                time_added = float(time_added)
            except:
                time_added = 0
            
            age_seconds = current_time - time_added if time_added > 0 else 0
            
            ratio = _get_torrent_field(data, "ratio")
            try:
                ratio = float(ratio)
            except:
                ratio = 0.0

            time_limit_met = age_seconds > max_age_seconds
            ratio_limit_met = ratio >= max_ratio
            
            # Only delete if it's seeding or completed
            if (time_limit_met or ratio_limit_met) and state in ["Seeding", "Paused", "Queued"]:
                reason = f"age ({age_seconds/86400:.2f} days > {args.max_seed_time} days)" if time_limit_met else f"ratio ({ratio:.2f} >= {max_ratio})"
                logger.warning(f"Torrent {name} met cleanup limit: {reason}. Deleting torrent AND data.")
                
                if args.dry_run:
                    logger.info(f"[DRY-RUN] Would DELETE {name} and DATA.")
                else:
                    try:
                        client.core.remove_torrent(_decode_value(torrent_id), True)
                        logger.info(f"Deleted {name} and its data.")
                    except Exception as e:
                        logger.error(f"Failed to delete {name}: {e}")
                        had_errors = True
                count += 1
                continue

            if label not in TARGET_LABELS:
                continue

            target_dir = os.path.normpath(os.path.join(args.dest, label))
            current_path_norm = os.path.normpath(current_path)
            
            if current_path_norm == target_dir:
                 continue

            logger.info(f"Found candidate to move: {name} [{label}] in {current_path}")
            
            if args.dry_run:
                logger.info(f"[DRY-RUN] Would move {name} to {target_dir}")
            else:
                try:
                    torrent_id_str = _decode_value(torrent_id)
                    client.core.move_storage([torrent_id_str], target_dir)
                    logger.info(f"Moved {name} to {target_dir}")
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
