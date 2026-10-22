#!/bin/bash
# Uninstalls Sparky (macOS): stops it, then deletes the install folder, ~/Applications/Sparky.app and the Desktop shortcut.
# Everything Sparky installed lives in that folder (runtime/, models/, data/): chats and models go with it.
# Python and Node.js from Homebrew are left alone (other programs may use them).
#
#   ./uninstall.sh          asks before deleting anything
#   ./uninstall.sh --yes    no question
#
# Folders that config.json places outside the install folder are listed, never deleted.
# Written for the bash 3.2 that ships with macOS. Everything runs from main() at the very end.

main() {
  local YES='' ROOT lnk app r k v outside=''
  case "${1:-}" in
    --yes|-y) YES=1 ;; '') ;; *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
  ROOT="$(cd "$(dirname "$0")" && pwd)"
  # never "rm -rf" a folder that is not a Sparky install
  if [ ! -f "$ROOT/app/server.py" ] || [ ! -f "$ROOT/install.sh" ] || [ "$ROOT" = / ] || [ "$ROOT" = "$HOME" ]; then
    echo "$ROOT does not look like a Sparky folder: nothing removed." >&2; exit 1
  fi
  lnk="$HOME/Desktop/Sparky.command"
  # the shortcut written by install.sh, only when it starts this install
  grep -qF "$ROOT/start.sh" "$lnk" 2>/dev/null || lnk=''
  # the app written by install.sh, only when it starts this install
  app="$HOME/Applications/Sparky.app"
  grep -qF "$ROOT/start.sh" "$app/Contents/MacOS/Sparky" 2>/dev/null || app=''

  echo "Sparky will be removed:"
  echo "  $ROOT   ($(du -sh "$ROOT" 2>/dev/null | cut -f1), with your chats, documents and models)"
  [ -n "$lnk" ] && echo "  $lnk"
  [ -n "$app" ] && echo "  $app"
  if [ -f "$ROOT/config.json" ]; then
    for k in runtime_dir comfy_dir llama_server llm_dir mmproj_dir voice_dir embed_dir data_dir; do
      v="$(plutil -extract "$k" raw -o - "$ROOT/config.json" 2>/dev/null)" || continue
      case "$v" in "$ROOT"/*|'') ;; *) outside="$outside  $v ($k)\n" ;; esac
    done
  fi
  [ -n "$outside" ] && printf 'Kept (config.json, outside the folder):\n%b' "$outside"

  if [ -z "$YES" ]; then
    printf 'Type "yes" to uninstall: '
    read -r r </dev/tty || r=''
    [ "$r" = yes ] || { echo "Cancelled, nothing removed."; exit 1; }
  fi
  "$ROOT/stop.sh" >/dev/null 2>&1
  [ -n "$lnk" ] && rm -f "$lnk"
  [ -n "$app" ] && rm -rf "$app"
  cd / && rm -rf "$ROOT" || { echo "Could not delete $ROOT" >&2; exit 1; }
  echo "Sparky is uninstalled."
}

main "$@"
