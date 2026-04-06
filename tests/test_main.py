import importlib
import json
import sys
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = ROOT / "backend"

if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def load_main(monkeypatch, tmp_path):
    monkeypatch.setenv("EXTRACTARR_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("EXTRACTARR_CONFIG_PATH", str(tmp_path / "config.json"))
    sys.modules.pop("main", None)
    return importlib.import_module("main")


def test_auth_flow_requires_password_change(monkeypatch, tmp_path):
    main = load_main(monkeypatch, tmp_path)

    with TestClient(main.app) as client:
        assert client.get("/api/config").status_code == 401

        login = client.post("/api/auth/login", json={"username": "admin", "password": "admin"})
        assert login.status_code == 200
        assert login.json()["require_password_change"] is True

        blocked = client.get("/api/status")
        assert blocked.status_code == 403

        change = client.post(
            "/api/auth/change-password",
            json={"current_password": "admin", "new_password": "strongpass1"},
        )
        assert change.status_code == 200

        ready = client.get("/api/status")
        assert ready.status_code == 200


def test_config_updates_encrypt_and_preserve_masked_secrets(monkeypatch, tmp_path):
    main = load_main(monkeypatch, tmp_path)
    config_path = Path(main.CONFIG_PATH)

    with TestClient(main.app) as client:
        client.post("/api/auth/login", json={"username": "admin", "password": "admin"})
        client.post(
            "/api/auth/change-password",
            json={"current_password": "admin", "new_password": "strongpass1"},
        )

        update = {
            "sftp_pass": "secret-pass",
            "sonarr": {"api_key": "sonarr-key", "url": "http://sonarr.local", "enabled": True},
            "web": {"host": "127.0.0.1", "port": 29441},
        }
        assert client.post("/api/config", json=update).status_code == 200

        saved = json.loads(config_path.read_text())
        assert saved["sftp_pass"].startswith("enc::")
        assert saved["sonarr"]["api_key"].startswith("enc::")

        masked = client.get("/api/config").json()
        assert masked["sftp_pass"] == "********"
        assert masked["sonarr"]["api_key"] == "********"

        original_sftp = saved["sftp_pass"]
        original_api_key = saved["sonarr"]["api_key"]

        assert (
            client.post(
                "/api/config",
                json={"sftp_pass": "********", "sonarr": {"api_key": "********"}},
            ).status_code
            == 200
        )

        saved_again = json.loads(config_path.read_text())
        assert saved_again["sftp_pass"] == original_sftp
        assert saved_again["sonarr"]["api_key"] == original_api_key


def test_resolve_bind_host_port(monkeypatch, tmp_path):
    main = load_main(monkeypatch, tmp_path)

    cfg = main.ExtractarrConfig()
    assert main.resolve_bind_host_port(cfg) == ("127.0.0.1", 29441)

    cfg.web.host = "0.0.0.0"
    cfg.web.port = 3000
    assert main.resolve_bind_host_port(cfg) == ("0.0.0.0", 3000)
