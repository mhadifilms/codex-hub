#!/bin/sh
set -eu
umask 077
prefix="${CODEX_HUB_PREFIX:-$HOME/.local}"
no_deps=false
while [ "$#" -gt 0 ]; do
  case "$1" in
    --prefix) [ "$#" -ge 2 ] || { echo '--prefix needs a path' >&2; exit 2; }; prefix="$2"; shift 2 ;;
    --no-deps) no_deps=true; shift ;;
    -h|--help) echo 'Usage: ./install.sh [--prefix PATH] [--no-deps]'; exit 0 ;;
    *) echo "Unknown option: $1" >&2; exit 2 ;;
  esac
done
for dependency in codex python3 tmux; do
  command -v "$dependency" >/dev/null 2>&1 || { echo "$dependency is required" >&2; exit 1; }
done
python3 -c 'import curses,sys; assert sys.version_info >= (3,10), "Python 3.10+ required"'
repo_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
install -d -m 700 "$prefix/bin" "$prefix/share/codex-hub"
if [ "$no_deps" = false ]; then
  python3 -m venv "$prefix/share/codex-hub/venv"
  "$prefix/share/codex-hub/venv/bin/python" -m pip --disable-pip-version-check install -r "$repo_dir/requirements.txt"
else
  python3 -c 'import rich,PIL' || { echo '--no-deps needs Rich and Pillow installed for python3' >&2; exit 1; }
fi
for library in "$repo_dir"/lib/*.py; do
  install -m 600 "$library" "$prefix/share/codex-hub/"
done
install -m 600 "$repo_dir/VERSION" "$prefix/share/codex-hub/VERSION"
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
fi
printf 'Installed Codex Hub %s. Run %s/bin/codex-hub.\n' "$(cat "$repo_dir/VERSION")" "$prefix"
case ":$PATH:" in *":$prefix/bin:"*) ;; *) printf 'Add %s/bin to PATH for convenient access.\n' "$prefix" ;; esac
