#!/bin/sh
set -eu
apt-get update
apt-get install -y python3 python3-pip python3-venv tmux nodejs npm
mkdir -p /root/codex-hub-test
cp -R "$1"/. /root/codex-hub-test/
cd /root/codex-hub-test
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
export CODEX_HUB_PYTHON="$PWD/.venv/bin/python"
export TERM=xterm-256color
"$CODEX_HUB_PYTHON" -m unittest discover -s tests -v
# Test the public PowerShell entry point from a path containing spaces.
test_source='/mnt/c/codex hub install test'
mkdir -p "$test_source"
cp -R bin lib requirements.txt VERSION tmux.conf install.sh install.ps1 uninstall.sh "$test_source/"
powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File 'C:\codex hub install test\install.ps1' -Distribution Ubuntu
"$HOME/.local/bin/codex-hub" --version
"$HOME/.local/bin/codex-hub" doctor
./uninstall.sh
test ! -e "$HOME/.local/bin/codex-hub"
