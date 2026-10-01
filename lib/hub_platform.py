"""Desktop integration for macOS, Linux, and Windows through WSL."""
import base64
import os
from pathlib import Path
import shutil
import subprocess
import sys


def is_wsl():
    return sys.platform == 'linux' and bool(os.environ.get('WSL_DISTRO_NAME') or os.environ.get('WSL_INTEROP'))


def clipboard_command():
    if sys.platform == 'darwin' and shutil.which('pbcopy'):
        return ['pbcopy']
    if is_wsl() and shutil.which('powershell.exe'):
        return ['powershell.exe', '-NoProfile', '-NonInteractive', '-Command',
                '[Console]::InputEncoding = [Text.UTF8Encoding]::new(); Set-Clipboard -Value ([Console]::In.ReadToEnd())']
    if shutil.which('wl-copy'):
        return ['wl-copy']
    if shutil.which('xclip'):
        return ['xclip', '-selection', 'clipboard']
    return None


def open_command(value, text=False):
    if sys.platform == 'darwin' and shutil.which('open'):
        return ['open', '-t', value] if text else ['open', value]
    if is_wsl() and shutil.which('powershell.exe'):
        if Path(value).is_absolute():
            value = subprocess.check_output(['wslpath', '-w', value], text=True).strip()
        # A literal PowerShell string, encoded as one argument, never shell input.
        script = "Start-Process -FilePath '" + value.replace("'", "''") + "'"
        encoded = base64.b64encode(script.encode('utf-16-le')).decode()
        return ['powershell.exe', '-NoProfile', '-NonInteractive', '-EncodedCommand', encoded]
    if shutil.which('xdg-open'):
        return ['xdg-open', value]
    raise ValueError('No system opener found. Install xdg-utils or enable Windows/WSL interoperability.')
