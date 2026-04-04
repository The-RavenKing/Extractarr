# Extractarr

A modern, stable overhaul of the original Extractarr tool.

## Features
- **Modern Backend:** Built with FastAPI for speed and type safety.
- **Robust Workflow:** Integrated Python-based workflow engine for SFTP downloads, extraction, and media app triggers.
- **Beautiful UI:** React-based dashboard with real-time progress and logs.
- **Secure:** Windows DPAPI support for local secret encryption.
- **Cross-Platform:** Native support for Windows (as a Service) and Linux.
- **Automated Releases:** Continuous Integration via GitHub Actions for Windows and Linux builds.

## Windows Support

Extractarr is designed to run natively as a Windows Service, ensuring it's always running in the background and starts automatically with your PC.

### Installation (Windows)
1. Download the latest `ExtractarrSetup.exe` from the [GitHub Releases](https://github.com/The-RavenKing/Extractarr/releases).
2. Run the installer and follow the wizard.
3. Once finished, Extractarr will be running as a background service ("Extractarr Service").
4. Access the dashboard at `http://localhost:29441`.

### Manual Build (Windows)
If you want to build the installer yourself:
1. Ensure you have [Inno Setup 6](https://jrsoftware.org/isdl.php) installed.
2. Open PowerShell and run: `.\build_windows.ps1`

## Linux Support

### Installation (Linux)
1. Download the `extractarr-linux` binary from the [GitHub Releases](https://github.com/The-RavenKing/Extractarr/releases).
2. Make it executable: `chmod +x extractarr-linux`
3. Run it: `./extractarr-linux`

## Support the Project

If you find Extractarr useful and would like to support its development, you can buy me a coffee:

[<img src="https://cdn.buymeacoffee.com/buttons/v2/default-yellow.png" alt="Buy Me A Coffee" style="height: 60px !important;width: 217px !important;" >](https://buymeacoffee.com/Nat20labs)

## Prerequisites (Development)
- Python 3.12+
- Node.js & npm
- UnRAR (for archive extraction)

## Development Setup

1. **Backend Setup:**
   ```bash
   pip install -r requirements.txt
   # On Windows, also install pywin32:
   # pip install pywin32
   ```

2. **Frontend Setup:**
   ```bash
   cd frontend
   npm install
   npm run build
   cd ..
   ```

## Running the Application (Development)

Start the backend server:
```bash
python backend/main.py
```
The dashboard will be available at `http://localhost:29441`.
