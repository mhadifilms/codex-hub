#!/bin/sh
set -eu
prefix="${CODEX_HUB_PREFIX:-$HOME/.local}"
case "${1:-}" in
  --prefix) [ "$#" = 2 ] || { echo 'Usage: ./uninstall.sh [--prefix PATH]' >&2; exit 2; }; prefix="$2" ;;
  '') ;;
  *) echo 'Usage: ./uninstall.sh [--prefix PATH]' >&2; exit 2 ;;
esac
[ -n "$prefix" ] && [ "$prefix" != / ] || { echo 'Invalid installation prefix' >&2; exit 2; }
for launcher in codex-hub codex-hub-tui codex-hub-usage codex-sub; do
  rm -f "$prefix/bin/$launcher"
done
rm -rf "$prefix/share/codex-hub"
printf 'Removed Codex Hub. Chats, projects, account settings, and the Codex CLI are retained.\n'
