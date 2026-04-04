import sys
import os
import servicemanager
import win32serviceutil
import win32service
import win32event
import threading

# Import the FastAPI app from main
from main import app

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
        # Run uvicorn server in a separate thread so we can block on the win32 event
        config = uvicorn.Config(app=app, host="0.0.0.0", port=29441, loop="asyncio")
        self.server = uvicorn.Server(config)
        
        self.server_thread = threading.Thread(target=self.server.run)
        self.server_thread.start()
        
        # Wait until stop event is signaled
        win32event.WaitForSingleObject(self.hWaitStop, win32event.INFINITE)
        if self.server_thread:
            self.server_thread.join()

if __name__ == '__main__':
    if len(sys.argv) == 1:
        servicemanager.Initialize()
        servicemanager.PrepareToHostSingle(ExtractarrService)
        servicemanager.StartServiceCtrlDispatcher()
    else:
        win32serviceutil.HandleCommandLine(ExtractarrService)