import sys
import os
import servicemanager
import win32serviceutil
import win32service
import win32event
import threading

# Import the FastAPI app from main
from main import app, load_config, resolve_bind_host_port

class ExtractarrService(win32serviceutil.ServiceFramework):
    _svc_name_ = "Extractarr"
    _svc_display_name_ = "Extractarr Service"
    _svc_description_ = "Runs the Extractarr background workflow engine and web UI."

    def __init__(self, args):
        win32serviceutil.ServiceFramework.__init__(self, args)
        self.hWaitStop = win32event.CreateEvent(None, 0, 0, None)
        self.server = None
        self.server_thread = None

    def SvcStop(self):
        self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
        win32event.SetEvent(self.hWaitStop)
        if self.server:
            self.server.should_exit = True

    def SvcDoRun(self):
        servicemanager.LogMsg(
            servicemanager.EVENTLOG_INFORMATION_TYPE,
            servicemanager.PYS_SERVICE_STARTED,
            (self._svc_name_, '')
        )
        self.main()

    def main(self):
        import uvicorn
        cfg = load_config()
        host, port = resolve_bind_host_port(cfg)
        # Run uvicorn server in a separate thread so we can block on the win32 event
        config = uvicorn.Config(app=app, host=host, port=port, loop="asyncio", log_config=None)
        self.server = uvicorn.Server(config)
        
        self.server_thread = threading.Thread(target=self.server.run)
        self.server_thread.start()
        
        # Wait until stop event is signaled
        win32event.WaitForSingleObject(self.hWaitStop, win32event.INFINITE)
        if self.server_thread:
            self.server_thread.join()

def is_running_as_service():
    """Check if we were launched by the Windows Service Control Manager."""
    import win32api
    import win32con
    try:
        # SCM launches services with a specific desktop; interactive sessions have a different one
        return win32api.GetConsoleTitle() == ''
    except Exception:
        return False


def ensure_service_installed_and_running():
    """Install and/or start the service, then open the UI in a browser."""
    import subprocess
    import webbrowser
    import time
    import ctypes

    # Must be run as admin to install/start a service
    if not ctypes.windll.shell32.IsUserAnAdmin():
        ctypes.windll.shell32.ShellExecuteW(
            None, "runas", sys.executable, " ".join(sys.argv), None, 1
        )
        return

    exe = sys.executable if not getattr(sys, 'frozen', False) else sys.argv[0]

    # Check current service state
    try:
        status = win32serviceutil.QueryServiceStatus(ExtractarrService._svc_name_)
        state = status[1]
    except Exception:
        state = None  # Service not installed

    if state is None:
        print("Installing Extractarr service...")
        subprocess.run([exe, "--startup", "auto", "install"], check=True)

    try:
        state = win32serviceutil.QueryServiceStatus(ExtractarrService._svc_name_)[1]
    except Exception:
        state = None

    if state != win32service.SERVICE_RUNNING:
        print("Starting Extractarr service...")
        win32serviceutil.StartService(ExtractarrService._svc_name_)
        # Wait up to 10s for it to come up
        for _ in range(20):
            time.sleep(0.5)
            try:
                if win32serviceutil.QueryServiceStatus(ExtractarrService._svc_name_)[1] == win32service.SERVICE_RUNNING:
                    break
            except Exception:
                break

    cfg = load_config()
    host, port = resolve_bind_host_port(cfg)
    browser_host = "localhost" if host in {"127.0.0.1", "0.0.0.0"} else host
    print(f"Opening Extractarr at http://{browser_host}:{port} ...")
    webbrowser.open(f"http://{browser_host}:{port}")


if __name__ == '__main__':
    if len(sys.argv) == 1:
        # Determine if SCM launched us (running as a service) or user double-clicked
        try:
            # If SCM launched this, StartServiceCtrlDispatcher will succeed quickly;
            # if not (interactive), it raises an error - we catch that and self-install instead.
            servicemanager.Initialize()
            servicemanager.PrepareToHostSingle(ExtractarrService)
            servicemanager.StartServiceCtrlDispatcher()
        except win32service.error:
            ensure_service_installed_and_running()
    else:
        win32serviceutil.HandleCommandLine(ExtractarrService)
