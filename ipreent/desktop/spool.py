"""The "iPreent" entry in the Windows print dialog.

Windows has no simple way to add a printer from user space, so this reuses the built-in
"Microsoft Print To PDF" driver with a local port that is a file path. The spooler then writes
every job to that file without asking for a name, and the app (running in the tray) picks the
file up, turns the pages into rows and prints them. Adding the printer needs admin once.
"""
import base64
import os
import subprocess
import time
from pathlib import Path

PRINTER_NAME = "iPreent"
DRIVER = "Microsoft Print To PDF"
SPOOL_DIR = Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData")) / "iPreent" / "spool"
PORT_FILE = SPOOL_DIR / "job.pdf"

_NO_WINDOW = 0x08000000

INSTALL = f"""
$ErrorActionPreference = 'Stop'
$dir = '{SPOOL_DIR}'
New-Item -ItemType Directory -Force $dir | Out-Null
icacls $dir /grant '*S-1-5-32-545:(OI)(CI)M' | Out-Null
$port = '{PORT_FILE}'
if (-not (Get-PrinterPort -Name $port -ErrorAction SilentlyContinue)) {{ Add-PrinterPort -Name $port }}
if (-not (Get-Printer -Name '{PRINTER_NAME}' -ErrorAction SilentlyContinue)) {{
    Add-Printer -Name '{PRINTER_NAME}' -DriverName '{DRIVER}' -PortName $port
}}
"""

UNINSTALL = f"""
Remove-Printer -Name '{PRINTER_NAME}' -ErrorAction SilentlyContinue
Remove-PrinterPort -Name '{PORT_FILE}' -ErrorAction SilentlyContinue
"""


def _ps(script):
    return subprocess.run(["powershell", "-NoProfile", "-Command", script], capture_output=True,
                          text=True, creationflags=_NO_WINDOW)


def _elevated(script):
    """Run a PowerShell script as admin (one UAC prompt) and wait for it."""
    enc = base64.b64encode(script.encode("utf-16-le")).decode()
    outer = ("$p = Start-Process powershell -Verb RunAs -Wait -PassThru -WindowStyle Hidden "
             f"-ArgumentList '-NoProfile','-ExecutionPolicy','Bypass','-EncodedCommand','{enc}'; "
             "exit $p.ExitCode")
    r = _ps(outer)
    return r.returncode == 0


def installed():
    r = _ps(f"if (Get-Printer -Name '{PRINTER_NAME}' -ErrorAction SilentlyContinue) {{ 'yes' }}")
    return "yes" in r.stdout


def install():
    return _elevated(INSTALL) and installed()


def uninstall():
    return _elevated(UNINSTALL) and not installed()


def take_job(min_age=1.0):
    """If the spooler has finished writing a job, move it aside and return its path."""
    try:
        st = PORT_FILE.stat()
    except OSError:
        return None
    if st.st_size == 0 or time.time() - st.st_mtime < min_age:
        return None
    dest = SPOOL_DIR / f"job-{time.strftime('%Y%m%d-%H%M%S')}-{st.st_size}.pdf"
    try:
        PORT_FILE.rename(dest)   # fails while the spooler still has it open
    except OSError:
        return None
    return dest


def leftover_jobs():
    """Jobs taken but not printed (app closed mid-job)."""
    try:
        return sorted(SPOOL_DIR.glob("job-*.pdf"))
    except OSError:
        return []
