import os
import json
import logging
import threading
from typing import Dict, Any, Optional
from fastapi import FastAPI, HTTPException, Request, Depends, status
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from contextlib import asynccontextmanager

from core.config_model import ExtractarrConfig, WebAuthSettings
from core.workflow import WorkflowEngine, WorkflowState
from core.utils import encrypt_secret, decrypt_secret

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

import os
import json
import logging
import threading
from typing import Dict, Any, Optional
from fastapi import FastAPI, HTTPException, Request, Depends, status
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from contextlib import asynccontextmanager
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from core.config_model import ExtractarrConfig, WebAuthSettings
from core.workflow import WorkflowEngine, WorkflowState
from core.utils import encrypt_secret, decrypt_secret

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

import sys
from pathlib import Path

if getattr(sys, 'frozen', False):
    BASE_DIR = sys._MEIPASS
    if os.name == 'nt':
        DATA_DIR = os.path.join(os.environ.get('PROGRAMDATA', 'C:\\ProgramData'), 'Extractarr', 'data')
    else:
        DATA_DIR = os.path.join(os.path.expanduser("~"), ".config", "extractarr", "data")
else:
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    DATA_DIR = os.path.join(BASE_DIR, 'data')

CONFIG_PATH = os.path.join(DATA_DIR, "config.json")

class GlobalState:
    config: ExtractarrConfig
    workflow: WorkflowEngine
    workflow_thread: Optional[threading.Thread] = None
    scheduler: BackgroundScheduler

state = GlobalState()

def load_config() -> ExtractarrConfig:
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r") as f:
                data = json.load(f)
                return ExtractarrConfig(**data)
        except Exception as e:
            logger.error(f"Failed to load config: {e}")
    return ExtractarrConfig()

def save_config(cfg: ExtractarrConfig):
    Path(os.path.dirname(CONFIG_PATH)).mkdir(parents=True, exist_ok=True)
    with open(CONFIG_PATH, "w") as f:
        f.write(cfg.model_dump_json(indent=2))

def sync_scheduler():
    # Clear existing jobs
    state.scheduler.remove_all_jobs()
    
    if state.config.enable_scheduling and state.config.schedule_time:
        try:
            hour, minute = state.config.schedule_time.split(":")
            state.scheduler.add_job(
                id="daily_workflow",
                func=run_workflow_internal,
                trigger=CronTrigger(hour=hour, minute=minute),
                name=state.config.task_name
            )
            logger.info(f"Scheduled daily workflow at {state.config.schedule_time}")
        except Exception as e:
            logger.error(f"Failed to schedule workflow: {e}")

def run_workflow_internal():
    if state.workflow.state.running:
        logger.warning("Scheduled workflow skipped: already running")
        return
    
    state.workflow_thread = threading.Thread(target=state.workflow.run)
    state.workflow_thread.start()

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Load config and init workflow engine
    state.config = load_config()
    state.workflow = WorkflowEngine(state.config)
    
    # Init scheduler
    state.scheduler = BackgroundScheduler()
    state.scheduler.start()
    sync_scheduler()
    
    yield
    # Cleanup
    state.scheduler.shutdown()

app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# API Routes
@app.get("/api/config")
async def get_config():
    # Strip sensitive info for frontend
    cfg_json = state.config.model_dump()
    # Mask secrets
    def mask_secrets(obj):
        if isinstance(obj, dict):
            for k, v in obj.items():
                if k.endswith("_pass") or k == "api_key" or k.endswith("_api_key"):
                    obj[k] = "********" if v else ""
                else:
                    mask_secrets(v)
        elif isinstance(obj, list):
            for item in obj:
                mask_secrets(item)
    
    mask_secrets(cfg_json)
    return cfg_json

@app.post("/api/config")
async def update_config(new_cfg: Dict[str, Any]):
    # Merge new config with existing to preserve encrypted secrets if not provided
    current_dict = state.config.model_dump()
    
    def merge_configs(target, source):
        for k, v in source.items():
            if isinstance(v, dict) and k in target and isinstance(target[k], dict):
                merge_configs(target[k], v)
            else:
                is_masked = k.endswith("_pass") or k == "api_key" or k.endswith("_api_key")
                if is_masked and v == "********":
                    # Keep existing value — do not overwrite with the mask placeholder
                    continue
                if k.endswith("_pass") and v:
                    target[k] = encrypt_secret(v)
                else:
                    target[k] = v
    
    merge_configs(current_dict, new_cfg)
    state.config = ExtractarrConfig(**current_dict)
    state.workflow.config = state.config
    sync_scheduler()
    save_config(state.config)
    return {"status": "success"}

@app.get("/api/status")
async def get_status():
    return state.workflow.state

@app.post("/api/run")
async def run_workflow():
    if state.workflow.state.running:
        raise HTTPException(status_code=400, detail="Workflow is already running")
    
    state.workflow_thread = threading.Thread(target=state.workflow.run)
    state.workflow_thread.start()
    return {"status": "started"}

from fastapi.responses import FileResponse

# ... (other routes)

@app.get("/logo.png")
async def get_logo():
    logo_path = os.path.join(BASE_DIR, "logo.png")
    if os.path.exists(logo_path):
        return FileResponse(logo_path)
    raise HTTPException(status_code=404)

# Serve Frontend (if built)
frontend_path = os.path.join(BASE_DIR, "frontend", "dist")
logger.info(f"Serving frontend from: {frontend_path}")
if os.path.exists(frontend_path):
    app.mount("/", StaticFiles(directory=frontend_path, html=True), name="frontend")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=29441)
