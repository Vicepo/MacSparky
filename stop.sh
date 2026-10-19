#!/bin/bash
# Stops Sparky: UI, assistant (llama-server) and image engine (ComfyUI) (macOS).
# Only Sparky's own processes are stopped: another program listening on the same port is left alone.
ROOT="$(cd "$(dirname "$0")" && pwd)"
cfg() { [ -f "$ROOT/config.json" ] && plutil -extract "$1" raw -o - "$ROOT/config.json" 2>/dev/null; }

app="$(cfg app_port)"; llm="$(cfg llm_port)"; comfy="$(cfg comfy_port)"
pids=""
for spec in "${app:-7860}:app/server.py" "${llm:-8080}:llama-server" "${comfy:-8188}:main.py"; do
  port="${spec%%:*}"; want="${spec#*:}"
  for pid in $(lsof -nP -iTCP:"$port" -sTCP:LISTEN -t 2>/dev/null); do
    case "$(ps -o command= -p "$pid" 2>/dev/null)" in
      *"$want"*) pids="$pids $pid" ;;
      *) echo "Port $port: not Sparky (pid $pid), left running." ;;
    esac
  done
done
if [ -n "$pids" ]; then
  kill $pids 2>/dev/null
  alive() { for p in $pids; do kill -0 "$p" 2>/dev/null && return 0; done; return 1; }
  i=0
  while [ $i -lt 20 ] && alive; do sleep 0.25; i=$((i + 1)); done
  alive && kill -9 $pids 2>/dev/null
fi
echo "Sparky stopped."
