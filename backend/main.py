import json
import logging
import os
import secrets
import threading
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Optional

import jwt
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from fastapi import Cookie, Depends, FastAPI, HTTPException, Request, Response, status
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from passlib.context import CryptContext
from pydantic import BaseModel

from core.config_model import ExtractarrConfig
from core.utils import encrypt_secret
from core.workflow import WorkflowEngine

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

import sys

SESSION_COOKIE = "extractarr_session"
SESSION_DURATION_HOURS = 12
MASKED_SECRET = "********"
pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")

if getattr(sys, "frozen", False):
    BASE_DIR = sys._MEIPASS
    if os.name == "nt":
        default_data_dir = os.path.join(os.environ.get("PROGRAMDATA", "C:\\ProgramData"), "Extractarr", "data")
    else:
        default_data_dir = os.path.join(os.path.expanduser("~"), ".config", "extractarr", "data")
else:
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    default_data_dir = os.path.join(BASE_DIR, "data")

DATA_DIR = os.environ.get("EXTRACTARR_DATA_DIR", default_data_dir)
CONFIG_PATH = os.environ.get("EXTRACTARR_CONFIG_PATH", os.path.join(DATA_DIR, "config.json"))


class LoginRequest(BaseModel):
    username: str
    password: str


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


class AuthStatus(BaseModel):
    auth_enabled: bool
    authenticated: bool
    username: str = ""
    require_password_change: bool = False


class GlobalState:
    config: ExtractarrConfig
    workflow: WorkflowEngine
    workflow_thread: Optional[threading.Thread] = None
    scheduler: BackgroundScheduler


state = GlobalState()


def is_secret_field(key: str) -> bool:
    return key.endswith("_pass") or key == "api_key" or key.endswith("_api_key") or key.endswith("host_key")


def ensure_auth_config(cfg: ExtractarrConfig) -> bool:
    changed = False
    if cfg.web.auth_enabled:
        if not cfg.web.secret_key:
            cfg.web.secret_key = secrets.token_urlsafe(32)
            changed = True
        if not cfg.web.password_hash:
            cfg.web.password_hash = pwd_context.hash("admin")
            cfg.web.require_password_change = True
            changed = True
            logger.warning("Web auth bootstrapped with default credentials for user '%s'", cfg.web.username)
    return changed


def resolve_bind_host_port(cfg: ExtractarrConfig) -> tuple[str, int]:
    host = (cfg.web.host or "127.0.0.1").strip() or "127.0.0.1"
    port = cfg.web.port or 29441
    return host, port


def load_config() -> ExtractarrConfig:
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                cfg = ExtractarrConfig(**data)
                if ensure_auth_config(cfg):
                    save_config(cfg)
                return cfg
        except Exception as exc:
            logger.error("Failed to load config: %s", exc)

    cfg = ExtractarrConfig()
    if ensure_auth_config(cfg):
        save_config(cfg)
    return cfg


def save_config(cfg: ExtractarrConfig):
    Path(os.path.dirname(CONFIG_PATH)).mkdir(parents=True, exist_ok=True)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        f.write(cfg.model_dump_json(indent=2))


def create_session_token(username: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": username,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=SESSION_DURATION_HOURS)).timestamp()),
    }
    return jwt.encode(payload, state.config.web.secret_key, algorithm="HS256")


def decode_session_token(token: str) -> Optional[Dict[str, Any]]:
    try:
        return jwt.decode(token, state.config.web.secret_key, algorithms=["HS256"])
    except jwt.PyJWTError:
        return None


def set_session_cookie(response: Response, token: str, secure: bool):
    response.set_cookie(
        key=SESSION_COOKIE,
        value=token,
        httponly=True,
        secure=secure,
        samesite="lax",
        max_age=SESSION_DURATION_HOURS * 60 * 60,
        path="/",
    )


def clear_session_cookie(response: Response):
    response.delete_cookie(key=SESSION_COOKIE, path="/")


def get_current_user(session_token: Optional[str] = Cookie(default=None, alias=SESSION_COOKIE)) -> Optional[str]:
    if not state.config.web.auth_enabled:
        return state.config.web.username
    if not session_token:
        return None
    payload = decode_session_token(session_token)
    if not payload:
        return None
    return str(payload.get("sub") or "")


def require_auth(current_user: Optional[str] = Depends(get_current_user)) -> str:
    if not state.config.web.auth_enabled:
        return state.config.web.username
    if not current_user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
    return current_user


def require_ready_session(current_user: str = Depends(require_auth)) -> str:
    if state.config.web.auth_enabled and state.config.web.require_password_change:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Password change required before using the application",
        )
    return current_user


def public_config_dict() -> Dict[str, Any]:
    cfg_json = state.config.model_dump()
    cfg_json.setdefault("web", {})
    cfg_json["web"]["password"] = ""

    def mask_secrets(obj: Any):
        if isinstance(obj, dict):
            for key, value in obj.items():
                if key in {"password_hash", "secret_key"}:
                    obj[key] = ""
                elif is_secret_field(key):
                    obj[key] = MASKED_SECRET if value else ""
                else:
                    mask_secrets(value)
        elif isinstance(obj, list):
            for item in obj:
                mask_secrets(item)

    mask_secrets(cfg_json)
    return cfg_json


def sync_scheduler():
    state.scheduler.remove_all_jobs()
    if state.config.enable_scheduling and state.config.schedule_time:
        try:
            hour, minute = state.config.schedule_time.split(":")
            state.scheduler.add_job(
                id="daily_workflow",
                func=run_workflow_internal,
                trigger=CronTrigger(hour=hour, minute=minute),
                name=state.config.task_name,
            )
            logger.info("Scheduled daily workflow at %s", state.config.schedule_time)
        except Exception as exc:
            logger.error("Failed to schedule workflow: %s", exc)


def run_workflow_internal():
    if state.workflow.state.running:
        logger.warning("Scheduled workflow skipped: already running")
        return
    state.workflow_thread = threading.Thread(target=state.workflow.run, daemon=True)
    state.workflow_thread.start()


@asynccontextmanager
async def lifespan(app: FastAPI):
    state.config = load_config()
    state.workflow = WorkflowEngine(state.config)
    state.scheduler = BackgroundScheduler()
    state.scheduler.start()
    sync_scheduler()
    yield
    state.scheduler.shutdown()


app = FastAPI(lifespan=lifespan)


@app.get("/api/auth/status", response_model=AuthStatus)
async def auth_status(current_user: Optional[str] = Depends(get_current_user)):
    return AuthStatus(
        auth_enabled=state.config.web.auth_enabled,
        authenticated=bool(current_user),
        username=current_user or "",
        require_password_change=bool(current_user) and state.config.web.require_password_change,
    )


@app.post("/api/auth/login", response_model=AuthStatus)
async def login(payload: LoginRequest, request: Request, response: Response):
    if not state.config.web.auth_enabled:
        return AuthStatus(
            auth_enabled=False,
            authenticated=True,
            username=state.config.web.username,
            require_password_change=False,
        )

    if payload.username != state.config.web.username or not pwd_context.verify(
        payload.password, state.config.web.password_hash
    ):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid username or password")

    secure_cookie = request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"
    set_session_cookie(response, create_session_token(payload.username), secure=secure_cookie)
    return AuthStatus(
        auth_enabled=True,
        authenticated=True,
        username=payload.username,
        require_password_change=state.config.web.require_password_change,
    )


@app.post("/api/auth/logout")
async def logout(response: Response):
    clear_session_cookie(response)
    return {"status": "logged_out"}


@app.post("/api/auth/change-password")
async def change_password(payload: ChangePasswordRequest, _: str = Depends(require_auth)):
    if state.config.web.auth_enabled and not pwd_context.verify(payload.current_password, state.config.web.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Current password is incorrect")
    if len(payload.new_password) < 8:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="New password must be at least 8 characters")

    state.config.web.password_hash = pwd_context.hash(payload.new_password)
    state.config.web.require_password_change = False
    state.workflow.config = state.config
    save_config(state.config)
    return {"status": "password_updated"}


@app.get("/api/config")
async def get_config(_: str = Depends(require_auth)):
    return public_config_dict()


@app.post("/api/config")
async def update_config(new_cfg: Dict[str, Any], _: str = Depends(require_auth)):
    current_dict = state.config.model_dump()

    def merge_configs(target: Dict[str, Any], source: Dict[str, Any], path: tuple[str, ...] = ()):
        for key, value in source.items():
            current_path = path + (key,)

            if current_path == ("web", "password"):
                if value:
                    target["password_hash"] = pwd_context.hash(value)
                    target["require_password_change"] = False
                continue

            if current_path in {("web", "password_hash"), ("web", "secret_key"), ("web", "require_password_change")}:
                continue

            if isinstance(value, dict) and key in target and isinstance(target[key], dict):
                merge_configs(target[key], value, current_path)
                continue

            if is_secret_field(key):
                if value == MASKED_SECRET:
                    continue
                target[key] = encrypt_secret(value) if value else ""
                continue

            target[key] = value

    merge_configs(current_dict, new_cfg)
    state.config = ExtractarrConfig(**current_dict)
    ensure_auth_config(state.config)
    state.workflow.config = state.config
    sync_scheduler()
    save_config(state.config)
    return {"status": "success"}


@app.get("/api/status")
async def get_status(_: str = Depends(require_ready_session)):
    return state.workflow.state


@app.post("/api/logs/clear")
async def clear_logs(_: str = Depends(require_ready_session)):
    state.workflow.state.logs = []
    return {"status": "cleared"}


@app.post("/api/run")
async def run_workflow(_: str = Depends(require_ready_session)):
    if state.workflow.state.running:
        raise HTTPException(status_code=400, detail="Workflow is already running")
    state.workflow_thread = threading.Thread(target=state.workflow.run, daemon=True)
    state.workflow_thread.start()
    return {"status": "started"}


@app.post("/api/trigger-imports")
async def trigger_imports(_: str = Depends(require_ready_session)):
    if state.workflow.state.running:
        raise HTTPException(status_code=400, detail="Workflow is already running")
    state.workflow_thread = threading.Thread(target=state.workflow.trigger_arr_imports, daemon=True)
    state.workflow_thread.start()
    return {"status": "started"}


@app.get("/logo.png")
async def get_logo():
    logo_path = os.path.join(BASE_DIR, "logo.png")
    if os.path.exists(logo_path):
        return FileResponse(logo_path)
    raise HTTPException(status_code=404)


frontend_path = os.path.join(BASE_DIR, "frontend", "dist")
logger.info("Serving frontend from: %s", frontend_path)
if os.path.exists(frontend_path):
    app.mount("/", StaticFiles(directory=frontend_path, html=True), name="frontend")


if __name__ == "__main__":
    import uvicorn

    config = load_config()
    host, port = resolve_bind_host_port(config)
    uvicorn.run(app, host=host, port=port)
