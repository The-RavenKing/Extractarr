import os
import platform
import subprocess

def is_windows() -> bool:
    return platform.system() == "Windows"

def encrypt_secret(raw_value: str) -> str:
    """Encrypt a secret with Windows DPAPI if available."""
    if not raw_value:
        return ""
    if raw_value.startswith("enc::"):
        return raw_value
    if not is_windows():
        # Mock for non-windows
        return f"enc::linux_mock::{raw_value}"

    ps = (
        "$raw = $env:EXTRACTARR_SECRET; "
        "if ([string]::IsNullOrEmpty($raw)) { exit 2 }; "
        "$secure = ConvertTo-SecureString -String $raw -AsPlainText -Force; "
        "$enc = ConvertFrom-SecureString -SecureString $secure; "
        "Write-Output ('enc::' + $enc)"
    )
    env = dict(os.environ)
    env["EXTRACTARR_SECRET"] = raw_value
    try:
        proc = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", ps],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
            env=env,
        )
        out = (proc.stdout or "").strip()
        if proc.returncode == 0 and out:
            return out.splitlines()[-1].strip()
    except Exception:
        pass
    return raw_value

def decrypt_secret(encrypted_value: str) -> str:
    """Decrypt a secret with Windows DPAPI if available."""
    if not encrypted_value or not encrypted_value.startswith("enc::"):
        return encrypted_value
    
    if not is_windows():
        if encrypted_value.startswith("enc::linux_mock::"):
            return encrypted_value.replace("enc::linux_mock::", "")
        return encrypted_value

    payload = encrypted_value[5:]
    ps = (
        "$enc = $env:EXTRACTARR_ENCRYPTED; "
        "if ([string]::IsNullOrEmpty($enc)) { exit 2 }; "
        "try { "
        "  $secure = ConvertTo-SecureString -String $enc; "
        "  $raw = [System.Net.NetworkCredential]::new('', $secure).Password; "
        "  Write-Output $raw "
        "} catch { exit 1 }"
    )
    env = dict(os.environ)
    env["EXTRACTARR_ENCRYPTED"] = payload
    try:
        proc = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", ps],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
            env=env,
        )
        if proc.returncode == 0:
            return (proc.stdout or "").strip()
    except Exception:
        pass
    return encrypted_value
