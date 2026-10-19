#!/bin/bash
# Starts Sparky (server + ComfyUI + assistant) in the background and opens the UI in the browser (macOS).
# Written for the bash 3.2 that ships with macOS.
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT" || exit 1
# opened from the Finder, the PATH can miss Homebrew (node, git)
for d in /opt/homebrew/bin /usr/local/bin; do
  case ":$PATH:" in *":$d:"*) ;; *) [ -d "$d" ] && PATH="$d:$PATH" ;; esac
done
export PATH

# value of a key in config.json (plutil reads JSON on every macOS), empty when missing
cfg() { [ -f "$ROOT/config.json" ] && plutil -extract "$1" raw -o - "$ROOT/config.json" 2>/dev/null; }

port="$(cfg app_port)"; port="${port:-7860}"
py="$(cfg python)"; py="${py:-$ROOT/runtime/venv/bin/python}"
case "$port" in *[!0-9]*|'') echo "config.json: app_port must be a number" >&2; exit 1 ;; esac
if [ ! -x "$py" ]; then
  msg="Python not found ($py). Run install.sh first."
  echo "$msg" >&2
  [ -t 1 ] || osascript -e "display alert \"Sparky\" message \"$msg\"" >/dev/null 2>&1
  exit 1
fi

up() { (exec 3<>"/dev/tcp/127.0.0.1/$port") 2>/dev/null; }
if ! up; then
  mkdir -p "$ROOT/data"
  # nohup + own stdin: Sparky keeps running when the Terminal window is closed
  nohup "$py" app/server.py --port "$port" >"$ROOT/data/server.log" 2>"$ROOT/data/server.err.log" </dev/null &
  disown 2>/dev/null
  i=0
  while [ $i -lt 60 ] && ! up; do sleep 0.5; i=$((i + 1)); done
  if ! up; then
    echo "Sparky did not start: see $ROOT/data/server.err.log" >&2
    tail -n 15 "$ROOT/data/server.err.log" >&2
    exit 1
  fi
fi
echo "Sparky: http://127.0.0.1:$port"
[ -n "$SPARKY_NOBROWSER" ] || open "http://127.0.0.1:$port"
