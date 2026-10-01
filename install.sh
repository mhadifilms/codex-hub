#!/bin/sh
set -eu
umask 077
prefix="${CODEX_HUB_PREFIX:-$HOME/.local}"
no_deps=false
bootstrap=false
python="${CODEX_HUB_PYTHON:-python3}"
while [ "$#" -gt 0 ]; do
  case "$1" in
    --prefix) [ "$#" -ge 2 ] || { echo '--prefix needs a path' >&2; exit 2; }; prefix="$2"; shift 2 ;;
    --no-deps) no_deps=true; shift ;;
    --bootstrap) bootstrap=true; shift ;;
    -h|--help) echo 'Usage: ./install.sh [--prefix PATH] [--bootstrap] [--no-deps]'; exit 0 ;;
    *) echo "Unknown option: $1" >&2; exit 2 ;;
  esac
done
export PATH="$prefix/bin:$PATH"
if [ "$bootstrap" = true ]; then
  case "$(uname -s)" in
    Darwin)
      command -v brew >/dev/null 2>&1 || { echo 'Install Homebrew from https://brew.sh, then rerun ./install.sh --bootstrap.' >&2; exit 1; }
      command -v "$python" >/dev/null 2>&1 || brew install python@3.12
      command -v tmux >/dev/null 2>&1 || brew install tmux
      command -v codex >/dev/null 2>&1 || brew install --cask codex
      ;;
    Linux)
      command -v apt-get >/dev/null 2>&1 || { echo 'Install Python 3.10+, python-venv, tmux, and Codex using your package manager; then rerun ./install.sh.' >&2; exit 1; }
      packages=''
      command -v "$python" >/dev/null 2>&1 || packages="$packages python3 python3-venv"
      "$python" -c 'import venv,ensurepip' >/dev/null 2>&1 || packages="$packages python3-venv"
      command -v tmux >/dev/null 2>&1 || packages="$packages tmux"
      if ! command -v codex >/dev/null 2>&1; then
        command -v npm >/dev/null 2>&1 || packages="$packages nodejs npm"
      fi
      if [ -n "$packages" ]; then
        if [ "$(id -u)" = 0 ]; then
          apt-get update
          # Package names above are controlled by this installer.
          apt-get install -y $packages
        else
          sudo apt-get update
          sudo apt-get install -y $packages
        fi
      fi
      command -v codex >/dev/null 2>&1 || npm install --global --prefix "$prefix" @openai/codex
      ;;
    *) echo 'Use macOS, Linux, or Windows Terminal with WSL. On Windows run install.ps1.' >&2; exit 1 ;;
  esac
fi
for dependency in "${CODEX_HUB_CODEX:-codex}" "$python" tmux; do
  command -v "$dependency" >/dev/null 2>&1 || { echo "$dependency is missing. Run ./install.sh --bootstrap, or install it and retry." >&2; exit 1; }
done
"$python" -c 'import curses,sys; assert sys.version_info >= (3,10), "Python 3.10+ required"'
"$python" -c 'import re,subprocess; v=re.search(r"(\d+)\.(\d+)",subprocess.check_output(["tmux","-V"],text=True)); assert v and tuple(map(int,v.groups())) >= (3,2), "tmux 3.2+ required"'
repo_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
install -d -m 700 "$prefix/bin" "$prefix/share/codex-hub"
if [ "$no_deps" = false ]; then
  "$python" -m venv "$prefix/share/codex-hub/venv"
  "$prefix/share/codex-hub/venv/bin/python" -m pip --disable-pip-version-check install -r "$repo_dir/requirements.txt"
else
  "$python" -c 'import rich,PIL' || { echo '--no-deps needs Rich and Pillow installed for the selected Python' >&2; exit 1; }
fi
for library in "$repo_dir"/lib/*.py; do
  install -m 600 "$library" "$prefix/share/codex-hub/"
done
install -m 600 "$repo_dir/VERSION" "$prefix/share/codex-hub/VERSION"
install -m 600 "$repo_dir/tmux.conf" "$prefix/share/codex-hub/tmux.conf"
for launcher in "$repo_dir"/bin/*; do
  [ -f "$launcher" ] || continue
  install -m 700 "$launcher" "$prefix/bin/"
done
config_file=$("$prefix/bin/codex-hub" config)
root=$(dirname "$config_file")
install -m 600 "$repo_dir/tmux.conf" "$root/tmux.conf"
if tmux -S "$root/tmux.sock" has-session 2>/dev/null; then
  tmux -S "$root/tmux.sock" source-file "$root/tmux.conf"
  "$prefix/bin/codex-hub" setup --reload
  printf 'Existing chats keep their frontend until reloaded. Use the chat menu or codex-hub reload ACCOUNT after stopping active work.\n'
fi
printf 'Installed Codex Hub %s. Run %s/bin/codex-hub.\n' "$(cat "$repo_dir/VERSION")" "$prefix"
printf 'Sign in with codex login if needed, then open codex-hub.\n'
printf 'For future shells, ensure %s/bin is on PATH.\n' "$prefix"
