#!/bin/bash
# Sparky - installer (macOS, Apple Silicon; Intel Macs run without GPU acceleration)
#
#   From the project folder : ./install.sh
#   One line                : curl -fsSL https://raw.githubusercontent.com/Vicepo/MacSparky/main/install.sh | bash
#
# Options (or environment variables for the one-line install):
#   --lang en|fr     / SPARKY_LANG       interface and installer language
#   --dir <folder>   / SPARKY_DIR        install folder (default: ~/Sparky)
#   --models         / SPARKY_MODELS     also download the recommended models from the terminal
#                                        (by default they are chosen in the browser at first launch)
#   --yes            / SPARKY_YES        answer yes to every question (English unless --lang)
#   --no-launch      / SPARKY_NOLAUNCH   do not open Sparky at the end
#   --no-shortcut    / SPARKY_NOSHORTCUT no Sparky app in ~/Applications and no Sparky.command on the Desktop
#
# What it installs, all inside the Sparky folder (runtime/): a Python environment, PyTorch (Metal / MPS),
# ComfyUI, llama.cpp (Metal build, checksum verified), Node.js when the Mac has none (LTS build, checksum
# verified). Python comes from Homebrew when missing, only after you say yes. Nothing needs sudo, and Homebrew
# itself is never installed by this script. Outside the folder: ~/Applications/Sparky.app, a launcher.
#
# Written for the bash 3.2 that ships with macOS. Everything runs from main() at the very end, so a download
# cut in the middle of "curl | bash" runs nothing.

REPO_URL='https://github.com/Vicepo/MacSparky'

# ------------------------------------------------------------------ look & feel
if [ -t 1 ]; then
  C_M=$'\033[35m'; C_G=$'\033[32m'; C_Y=$'\033[33m'; C_R=$'\033[31m'; C_C=$'\033[36m'; C_D=$'\033[90m'; C_B=$'\033[1m'; C_0=$'\033[0m'
else
  C_M=''; C_G=''; C_Y=''; C_R=''; C_C=''; C_D=''; C_B=''; C_0=''
fi
STEP=0; TOTAL=7; LOG="${TMPDIR:-/tmp}/sparky-install.log"; L=en

step() { STEP=$((STEP + 1)); printf '\n  %s●%s %s%s %d/%d%s   %s%s%s\n' "$C_M" "$C_0" "$C_D" "$(T step)" "$STEP" "$TOTAL" "$C_0" "$C_B" "$1" "$C_0"; }
ok() { printf '    %s✔%s %s\n' "$C_G" "$C_0" "$1"; }
info() { printf '      %s%s%s\n' "$C_D" "$1" "$C_0"; }
warn() { printf '    %s! %s%s\n' "$C_Y" "$1" "$C_0"; }
fail() {
  printf '    %s✖ %s%s\n' "$C_R" "$1" "$C_0"
  if [ -f "$LOG" ]; then
    echo; tail -n 12 "$LOG" | sed 's/^/      /'
    printf '\n      %s%s %s%s\n' "$C_D" "$(T logat)" "$LOG" "$C_0"
  fi
  exit 1
}
# yes/no question; the answer is read from the terminal, also under "curl | bash" (stdin is the script there)
ask() {
  local q="$1" def="${2:-y}" hint r
  if [ -z "$INTERACTIVE" ]; then [ "$def" = y ]; return; fi
  if [ "$def" = y ]; then hint="$(T yn)"; else hint="$(T ny)"; fi
  printf '    %s› %s%s %s%s%s ' "$C_C" "$q" "$C_0" "$C_D" "$hint" "$C_0"
  read -r r </dev/tty || r=''
  r="$(printf '%s' "$r" | tr '[:upper:]' '[:lower:]')"
  [ -z "$r" ] && { [ "$def" = y ]; return; }
  case "$r" in y|yes|o|oui) return 0 ;; *) return 1 ;; esac
}
fmt() { if [ "$1" -lt 60 ]; then echo "$1 s"; else echo "$(($1 / 60)) min $(($1 % 60)) s"; fi; }
# runs a program in the background with a spinner; its output goes to the log
run() {
  local label="$1" hint=''; shift
  if [ "${1:-}" = --hint ]; then hint="$2"; shift 2; fi
  local t0=$SECONDS i=0 spin='|/-\' pid code
  echo "=== $label: $*" >>"$LOG"
  "$@" >>"$LOG" 2>&1 </dev/null &
  pid=$!
  while kill -0 "$pid" 2>/dev/null; do
    if [ -t 1 ]; then printf '\r    %s%s %s   %s   %s%s\033[K' "$C_C" "${spin:$((i % 4)):1}" "$label" "$(fmt $((SECONDS - t0)))" "$hint" "$C_0"; fi
    sleep 0.2; i=$((i + 1))
  done
  wait "$pid"; code=$?
  [ -t 1 ] && printf '\r\033[K'
  [ "$code" -eq 0 ] || fail "$label (code $code)"
  printf '    %s✔%s %s   %s%s%s\n' "$C_G" "$C_0" "$label" "$C_D" "$(fmt $((SECONDS - t0)))" "$C_0"
}
fetch() {  # fetch <label> <url> <file>
  echo "=== download $2" >>"$LOG"
  printf '    %s%s%s\n' "$C_C" "$1" "$C_0"
  local bar=-sS; [ -t 2 ] && bar=--progress-bar
  curl -fL --retry 3 "$bar" -o "$3" "$2" || fail "$(T dlfail) $2"
}

# ------------------------------------------------------------------ texts
T() {
  local k="$1" v=''
  if [ "$L" = fr ]; then
    case "$k" in
      step) v='Étape' ;; yn) v='[O/n]' ;; ny) v='[o/N]' ;; logat) v='Journal complet :' ;; dlfail) v='Téléchargement impossible :' ;;
      welcome1) v='Chat, vision, images, code et dictée vocale,' ;; welcome2) v='entièrement sur ce Mac. Rien n'"'"'en sort.' ;;
      s1) v='Vérification de ton Mac' ;; s2) v='Fichiers de Sparky' ;; s3) v='Python' ;; s4) v='Moteur d'"'"'images (PyTorch + ComfyUI)' ;;
      s5) v='Moteur IA (llama.cpp) et Node.js' ;; s6) v='Diagnostic de ton Mac' ;; s7) v='Application Sparky' ;;
      notmac) v='Cet installateur est pour macOS. Sous Windows : install.ps1.' ;;
      intel) v='Mac Intel : pas d'"'"'accélération GPU, l'"'"'assistant tourne sur le processeur (plus lent).' ;;
      lowdisk) v='Moins de 25 Go libres : les outils prennent ~5 Go, plus 3 à 20 Go par modèle.' ;;
      folder) v='Dossier d'"'"'installation' ;; folderq) v='Entrée pour accepter, ou tape un autre dossier :' ;;
      dlcode) v='Téléchargement de Sparky' ;; updated) v='Mise à jour de Sparky' ;; free) v='libres' ;;
      nopy) v='Python 3.10 à 3.13 introuvable.' ;; brewpy) v='Installer Python 3.12 avec Homebrew ?' ;; pyinst) v='Installation de Python 3.12 (Homebrew)' ;;
      nobrew) v='Installe Homebrew (https://brew.sh) ou Python 3.12 (https://www.python.org), puis relance ce script.' ;;
      venv) v='Création de l'"'"'environnement Python' ;; torch) v='Installation de PyTorch' ;; torchhint) v='(~1 Go, quelques minutes)' ;;
      deps) v='Installation des dépendances' ;; mps) v='Accélération GPU (Metal / MPS)' ;; nomps) v='sans accélération GPU' ;;
      llamarel) v='Recherche de la dernière version de llama.cpp' ;; nollama) v='llama.cpp : pas de version pour macOS' ;;
      badsum) v='llama.cpp : somme de contrôle incorrecte, fichier rejeté' ;; sumok) v='somme de contrôle vérifiée' ;;
      nonode) v='Node.js absent : les projets JavaScript générés ne pourront pas être testés.' ;;
      badnode) v='Node.js : somme de contrôle incorrecte, fichier rejeté' ;; scan) v='Analyse du matériel' ;;
      level) v='Niveau :' ;; usable) v='Go utilisables pour les modèles' ;; recommended) v='Recommandé pour ce Mac' ;;
      later) v='Tu choisiras et installeras tes modèles dans le navigateur, au premier lancement.' ;;
      shortq) v='Créer aussi un raccourci Sparky sur le Bureau ?' ;; shortcut) v='Raccourci sur le Bureau : Sparky.command' ;; noshort) v='Pas de raccourci sur le Bureau' ;;
      app) v='Application « Sparky » dans ~/Applications (Spotlight, Launchpad)' ;; noapp) v='~/Applications/Sparky.app appartient à un autre programme : laissée telle quelle' ;;
      ready) v='Sparky est prêt !' ;; launchhow) v='Lance-le depuis Spotlight ou Launchpad (« Sparky »),' ;; launchhow2) v='ou ./start.sh dans le dossier d'"'"'installation.' ;;
      opening) v='Ouverture de Sparky dans ton navigateur...' ;; bye) v='Amuse-toi bien !' ;; already) v='déjà installé' ;;
      nogit) v='git absent : téléchargement de l'"'"'archive (les mises à jour automatiques demandent git).' ;;
    esac
  fi
  if [ -z "$v" ]; then
    case "$k" in
      step) v='Step' ;; yn) v='[Y/n]' ;; ny) v='[y/N]' ;; logat) v='Full log:' ;; dlfail) v='Download failed:' ;;
      welcome1) v='Chat, vision, images, code and voice dictation,' ;; welcome2) v='running entirely on this Mac. Nothing leaves it.' ;;
      s1) v='Checking your Mac' ;; s2) v='Sparky files' ;; s3) v='Python' ;; s4) v='Image engine (PyTorch + ComfyUI)' ;;
      s5) v='AI engine (llama.cpp) and Node.js' ;; s6) v='System scan' ;; s7) v='Sparky app' ;;
      notmac) v='This installer is for macOS. On Windows: install.ps1.' ;;
      intel) v='Intel Mac: no GPU acceleration, the assistant runs on the processor (slower).' ;;
      lowdisk) v='Less than 25 GB free: the tools take ~5 GB, plus 3 to 20 GB per model.' ;;
      folder) v='Install folder' ;; folderq) v='Press Enter to accept, or type another folder:' ;;
      dlcode) v='Downloading Sparky' ;; updated) v='Updating Sparky' ;; free) v='free' ;;
      nopy) v='Python 3.10 to 3.13 not found.' ;; brewpy) v='Install Python 3.12 with Homebrew?' ;; pyinst) v='Installing Python 3.12 (Homebrew)' ;;
      nobrew) v='Install Homebrew (https://brew.sh) or Python 3.12 (https://www.python.org), then run this script again.' ;;
      venv) v='Creating the Python environment' ;; torch) v='Installing PyTorch' ;; torchhint) v='(~1 GB, a few minutes)' ;;
      deps) v='Installing dependencies' ;; mps) v='GPU acceleration (Metal / MPS)' ;; nomps) v='no GPU acceleration' ;;
      llamarel) v='Looking up the latest llama.cpp release' ;; nollama) v='llama.cpp: no macOS build found' ;;
      badsum) v='llama.cpp: checksum mismatch, file rejected' ;; sumok) v='checksum verified' ;;
      nonode) v='Node.js missing: the JavaScript projects Sparky builds cannot be tested.' ;;
      badnode) v='Node.js: checksum mismatch, file rejected' ;; scan) v='Analysing your hardware' ;;
      level) v='Level:' ;; usable) v='GB usable for models' ;; recommended) v='Recommended for this Mac' ;;
      later) v='You will choose and install your models in the browser, at first launch.' ;;
      shortq) v='Also create a Sparky shortcut on the Desktop?' ;; shortcut) v='Desktop shortcut: Sparky.command' ;; noshort) v='No Desktop shortcut' ;;
      app) v='"Sparky" app in ~/Applications (Spotlight, Launchpad)' ;; noapp) v='~/Applications/Sparky.app belongs to another program: left alone' ;;
      ready) v='Sparky is ready!' ;; launchhow) v='Open it from Spotlight or Launchpad ("Sparky"),' ;; launchhow2) v='or ./start.sh in the install folder.' ;;
      opening) v='Opening Sparky in your browser...' ;; bye) v='Enjoy!' ;; already) v='already installed' ;;
      nogit) v='git missing: downloading the archive (automatic updates need git).' ;;
    esac
  fi
  printf '%s' "$v"
}

# ------------------------------------------------------------------ helpers
# a usable git: on a Mac without the developer tools, /usr/bin/git only opens an install dialog
has_git() { command -v git >/dev/null 2>&1 && git --version >/dev/null 2>&1; }
py_ok() { "$1" -c 'import sys; sys.exit(0 if (3, 10) <= sys.version_info[:2] <= (3, 13) else 1)' >/dev/null 2>&1; }
find_python() {
  local c
  for c in python3.12 python3.11 python3.13 python3.10 /opt/homebrew/bin/python3.12 /opt/homebrew/bin/python3 python3; do
    if command -v "$c" >/dev/null 2>&1 && py_ok "$c"; then command -v "$c"; return 0; fi
  done
  return 1
}
get_repo() {  # get_repo <label> <url> <dest> <branch>
  if [ -d "$3" ]; then ok "$1   $(T already)"; return; fi
  if has_git; then run "$1" git clone --depth 1 "$2" "$3"; return; fi
  local tmp; tmp="$(mktemp -d)"
  fetch "$1" "$2/archive/refs/heads/$4.tar.gz" "$tmp/src.tar.gz"
  tar -xzf "$tmp/src.tar.gz" -C "$tmp" || fail "$1"
  mv "$(find "$tmp" -mindepth 1 -maxdepth 1 -type d | head -n 1)" "$3" || fail "$1"
  rm -rf "$tmp"
}

APP_ID='local.sparky.launcher'
# ~/Applications/Sparky.app: a small bundle that runs start.sh, found by Spotlight and Launchpad (no Terminal window).
# An app of that name that this installer did not make is never replaced.
make_app() {  # make_app <root> <bundle>
  local root="$1" app="$2" tmp s
  [ -n "$root" ] && [ -n "$app" ] || return 1
  if [ -e "$app" ] && ! grep -qs "$APP_ID" "$app/Contents/Info.plist"; then return 1; fi
  rm -rf "$app" && mkdir -p "$app/Contents/MacOS" "$app/Contents/Resources" || return 1
  cat >"$app/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleName</key><string>Sparky</string>
  <key>CFBundleDisplayName</key><string>Sparky</string>
  <key>CFBundleIdentifier</key><string>$APP_ID</string>
  <key>CFBundleExecutable</key><string>Sparky</string>
  <key>CFBundleIconFile</key><string>Sparky</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>$(tr -cd '0-9A-Za-z.-' <"$root/VERSION" 2>/dev/null)</string>
  <key>LSUIElement</key><true/>
</dict></plist>
PLIST
  printf '#!/bin/bash\n# Starts Sparky (created by install.sh)\nexec %q\n' "$root/start.sh" >"$app/Contents/MacOS/Sparky" || return 1
  chmod +x "$app/Contents/MacOS/Sparky"
  tmp="$(mktemp -d)" || return 0   # no icon: the app still works
  mkdir "$tmp/Sparky.iconset"
  for s in 16 32 128 256 512; do
    sips -z $s $s "$root/app/logo.png" --out "$tmp/Sparky.iconset/icon_${s}x${s}.png" >/dev/null 2>&1
    sips -z $((s * 2)) $((s * 2)) "$root/app/logo.png" --out "$tmp/Sparky.iconset/icon_${s}x${s}@2x.png" >/dev/null 2>&1
  done
  iconutil -c icns "$tmp/Sparky.iconset" -o "$app/Contents/Resources/Sparky.icns" >>"$LOG" 2>&1
  rm -rf "$tmp"
  touch "$app"   # Finder and Launchpad pick up the new icon
}

# ------------------------------------------------------------------ main
main() {
  local DIR="${SPARKY_DIR:-}" MODELS="${SPARKY_MODELS:-}" YES="${SPARKY_YES:-}" NOLAUNCH="${SPARKY_NOLAUNCH:-}"
  local NOSHORT="${SPARKY_NOSHORTCUT:-}" LANG_OPT="${SPARKY_LANG:-}"
  while [ $# -gt 0 ]; do
    case "$1" in
      --lang) LANG_OPT="${2:-}"; shift ;; --lang=*) LANG_OPT="${1#*=}" ;;
      --dir) DIR="${2:-}"; shift ;; --dir=*) DIR="${1#*=}" ;;
      --models) MODELS=1 ;; --yes|-y) YES=1 ;; --no-launch) NOLAUNCH=1 ;; --no-shortcut) NOSHORT=1 ;;
      *) echo "unknown option: $1" >&2; exit 2 ;;
    esac
    shift
  done
  INTERACTIVE=1
  if [ -n "$YES" ] || ! { [ -r /dev/tty ] && : </dev/tty; } 2>/dev/null; then INTERACTIVE=''; fi

  printf '\n   %s✦  S P A R K Y%s   %s·  Your private AI assistant, 100%% local%s\n' "$C_M$C_B" "$C_0" "$C_D" "$C_0"
  case "$LANG_OPT" in
    en|fr) L="$LANG_OPT" ;;
    *) if [ -n "$INTERACTIVE" ]; then
         printf '\n    Choose your language / Choisis ta langue\n      1  English\n      2  Français\n    %s›%s ' "$C_C" "$C_0"
         local c; read -r c </dev/tty || c=''
         case "$c" in 2|f*|F*) L=fr ;; esac
       fi ;;
  esac
  local GB=GB; [ "$L" = fr ] && GB=Go
  printf '\n    %s\n    %s\n' "$(T welcome1)" "$(T welcome2)"

  # ---------------------------------------------------------------- 1. machine
  step "$(T s1)"
  [ "$(uname -s)" = Darwin ] || fail "$(T notmac)"
  local arch=x64 chip ram osv
  [ "$(sysctl -n hw.optional.arm64 2>/dev/null)" = 1 ] && arch=arm64
  chip="$(sysctl -n machdep.cpu.brand_string 2>/dev/null)"
  ram=$(( $(sysctl -n hw.memsize) / 1073741824 ))
  osv="$(sw_vers -productVersion)"
  ok "macOS $osv  ·  $chip  ·  $arch  ·  $ram $GB RAM"
  [ "$arch" = arm64 ] || warn "$(T intel)"

  # ---------------------------------------------------------------- 2. Sparky files
  step "$(T s2)"
  local here='' ROOT
  if [ -n "${BASH_SOURCE[0]:-}" ] && [ -f "${BASH_SOURCE[0]}" ]; then here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; fi
  if [ -n "$here" ] && [ -f "$here/app/server.py" ]; then
    ROOT="$here"
  else
    if [ -z "$DIR" ]; then
      DIR="$HOME/Sparky"
      if [ -n "$INTERACTIVE" ]; then
        info "$(T folder): $DIR"
        printf '    %s› %s%s ' "$C_C" "$(T folderq)" "$C_0"
        local d; read -r d </dev/tty || d=''
        [ -n "$d" ] && DIR="${d/#\~/$HOME}"
      fi
    fi
    mkdir -p "$(dirname "$DIR")" || fail "$DIR"
    if [ -f "$DIR/app/server.py" ]; then
      if has_git && [ -d "$DIR/.git" ]; then run "$(T updated)" git -C "$DIR" pull --ff-only; fi
    elif has_git; then
      run "$(T dlcode)" git clone --depth 1 "$REPO_URL.git" "$DIR"
    else
      warn "$(T nogit)"
      local tmp; tmp="$(mktemp -d)"
      fetch "$(T dlcode)" "$REPO_URL/archive/refs/heads/main.tar.gz" "$tmp/sparky.tar.gz"
      mkdir -p "$DIR" && tar -xzf "$tmp/sparky.tar.gz" -C "$DIR" --strip-components 1 || fail "$(T dlcode)"
      rm -rf "$tmp"
    fi
    ROOT="$(cd "$DIR" && pwd)"
  fi
  local RUNTIME="$ROOT/runtime"
  mkdir -p "$RUNTIME" "$ROOT/data"
  LOG="$ROOT/data/install.log"
  echo "=== Sparky install $(date '+%Y-%m-%dT%H:%M:%S')" >"$LOG"
  local free; free=$(( $(df -Pk "$ROOT" | awk 'NR==2 {print $4}') / 1048576 ))
  ok "$ROOT   ·   $free $GB $(T free)"
  [ "$free" -lt 25 ] && warn "$(T lowdisk)"

  # ---------------------------------------------------------------- 3. Python
  step "$(T s3)"
  local VPY="$RUNTIME/venv/bin/python" py
  if [ -x "$VPY" ] && py_ok "$VPY"; then
    ok "$("$VPY" --version 2>&1)   ($(T already))"
  else
    py="$(find_python)"
    if [ -z "$py" ]; then
      warn "$(T nopy)"
      if command -v brew >/dev/null 2>&1 && ask "$(T brewpy)" y; then
        run "$(T pyinst)" brew install python@3.12
        py="$(find_python)"
      fi
      [ -n "$py" ] || fail "$(T nobrew)"
    fi
    run "$(T venv)" "$py" -m venv "$RUNTIME/venv"
  fi
  run pip "$VPY" -m pip install --upgrade pip --quiet
  ok "$("$VPY" --version 2>&1)"

  # ---------------------------------------------------------------- 4. PyTorch + ComfyUI
  step "$(T s4)"
  if "$VPY" -c 'import torch' >/dev/null 2>&1; then
    ok "PyTorch   $(T already)"
  else  # the standard macOS arm64 wheels include the Metal backend (MPS)
    run "$(T torch)" --hint "$(T torchhint)" "$VPY" -m pip install torch torchvision torchaudio
  fi
  local tinfo; tinfo="$("$VPY" -c 'import torch; print(torch.__version__, torch.backends.mps.is_available())' 2>/dev/null)"
  case "$tinfo" in *True) ok "$(T mps)   PyTorch ${tinfo% *}" ;; *) warn "PyTorch ${tinfo% *}   $(T nomps)" ;; esac
  local COMFY="$RUNTIME/ComfyUI"
  get_repo ComfyUI https://github.com/comfyanonymous/ComfyUI "$COMFY" master
  get_repo IP-Adapter https://github.com/cubiq/ComfyUI_IPAdapter_plus "$COMFY/custom_nodes/ComfyUI_IPAdapter_plus" main
  run "$(T deps)" "$VPY" -m pip install -r "$COMFY/requirements.txt" -r "$ROOT/requirements.txt"

  # ---------------------------------------------------------------- 5. llama.cpp + Node.js
  step "$(T s5)"
  local LLAMA="$RUNTIME/llama"
  if [ -x "$LLAMA/llama-server" ]; then
    ok "llama.cpp   $(T already)"
  else
    local tmp rel tag url sum
    tmp="$(mktemp -d)"
    curl -fsSL -H 'User-Agent: sparky' 'https://api.github.com/repos/ggml-org/llama.cpp/releases?per_page=10' -o "$tmp/rels.json" \
      || fail "$(T dlfail) api.github.com"
    # tag, url and sha256 of the newest macOS build for this chip (Metal is built into the arm64 build)
    rel="$("$VPY" -I -c '
import json, re, sys
for r in json.load(open(sys.argv[1])):
    for a in r.get("assets", []):
        if re.fullmatch(r"llama-.*-bin-macos-" + sys.argv[2] + r"\.(tar\.gz|zip)", a["name"]):
            print(r["tag_name"], a["browser_download_url"], (a.get("digest") or "").removeprefix("sha256:"))
            sys.exit()
' "$tmp/rels.json" "$arch")"
    [ -n "$rel" ] || fail "$(T nollama) ($arch)"
    tag="${rel%% *}"; url="$(echo "$rel" | cut -d' ' -f2)"; sum="$(echo "$rel" | cut -d' ' -f3)"
    local file="$tmp/${url##*/}"
    fetch "llama.cpp $tag" "$url" "$file"
    if [ -n "$sum" ]; then
      [ "$(shasum -a 256 "$file" | cut -d' ' -f1)" = "$sum" ] || fail "$(T badsum)"
      info "$(T sumok) (sha256)"
    fi
    mkdir -p "$tmp/x"
    case "$file" in *.zip) unzip -q "$file" -d "$tmp/x" ;; *) tar -xzf "$file" -C "$tmp/x" ;; esac || fail "llama.cpp"
    local exe; exe="$(find "$tmp/x" -type f -name llama-server | head -n 1)"
    [ -n "$exe" ] || fail "llama.cpp: llama-server"
    rm -rf "$LLAMA" && mkdir -p "$LLAMA"
    cp -R "$(dirname "$exe")/." "$LLAMA/" || fail "llama.cpp"   # llama-server and its .dylib files stay together
    rm -rf "$tmp"
    "$LLAMA/llama-server" --version >>"$LOG" 2>&1 || fail "llama.cpp: llama-server --version"
    ok "llama.cpp $tag   ·   Metal $arch"
  fi
  # Node.js: runs and tests the JavaScript projects the assistant builds (optional). The Mac's own node is used
  # when there is one; otherwise the LTS build goes into runtime/node (no Homebrew, removed with the folder)
  local NODE="$RUNTIME/node"
  if [ -x "$NODE/bin/node" ]; then
    ok "Node.js $("$NODE/bin/node" --version)   ($(T already))"
  elif command -v node >/dev/null 2>&1; then
    ok "Node.js $(node --version)"
  else
    local tmp nv nfile want
    tmp="$(mktemp -d)" || fail "mktemp"
    nv="$(curl -fsSL https://nodejs.org/dist/index.json 2>>"$LOG" | "$VPY" -I -c '
import json, sys
print(next((r["version"] for r in json.load(sys.stdin) if r["lts"] and "osx-" + sys.argv[1] + "-tar" in r["files"]), ""))
' "$arch" 2>>"$LOG")"
    if [ -n "$nv" ]; then
      nfile="node-$nv-darwin-$arch.tar.gz"
      fetch "Node.js $nv" "https://nodejs.org/dist/$nv/$nfile" "$tmp/$nfile"
      curl -fsSL "https://nodejs.org/dist/$nv/SHASUMS256.txt" -o "$tmp/sums" || fail "$(T dlfail) SHASUMS256.txt"
      want="$(awk -v f="$nfile" '$2 == f {print $1}' "$tmp/sums")"
      [ -n "$want" ] && [ "$(shasum -a 256 "$tmp/$nfile" | cut -d' ' -f1)" = "$want" ] || fail "$(T badnode)"
      mkdir -p "$NODE" && tar -xzf "$tmp/$nfile" -C "$NODE" --strip-components 1 || fail "Node.js"
      ok "Node.js $nv   ·   $(T sumok) (sha256)"
    else
      warn "$(T nonode)"
    fi
    rm -rf "$tmp"
  fi

  # ---------------------------------------------------------------- 6. scan + models
  step "$(T s6)"
  cd "$ROOT" || fail "$ROOT"
  # interface language, saved for the first launch
  "$VPY" -c "import json,os,sys;p=os.path.join('data','settings.json');d=json.load(open(p,encoding='utf-8')) if os.path.exists(p) else {};d['ui_lang']=sys.argv[1];json.dump(d,open(p,'w',encoding='utf-8'),indent=1)" "$L"
  info "$(T scan)..."
  local scan; scan="$("$VPY" app/syscheck.py --json "--lang=$L" 2>>"$LOG")" || fail "$(T scan)"
  "$VPY" -c '
import json, sys
s, gb, level, usable, title, green, yellow, end = json.loads(sys.argv[1]), *sys.argv[2:]
a, rec = s["assess"], s["recommended"]
print(f"    {green}✔{end}", level, a["tier_label"], "  ·  ", round(a["model_mem_gb"]), usable)
for n in s["notes"]:
    print(f"    {yellow}! {n}{end}")
print("\n    " + title)
for k, lab in (("llm", "Assistant"), ("image", "Images"), ("voice", "Voice")):
    if k in rec:
        print("      %-11s%-31s%6.1f %s" % (lab, rec[k]["label"], rec[k]["size_gb"], gb))
print("      %-42s%6.1f %s" % ("Total", sum(rec[k]["size_gb"] for k in ("llm", "image", "voice") if k in rec), gb))
' "$scan" "$GB" "$(T level)" "$(T usable)" "$(T recommended)" "$C_G" "$C_Y" "$C_0"
  if [ -n "$MODELS" ]; then
    echo; "$VPY" app/models_cli.py --recommended "--lang=$L"
  else
    info "$(T later)"
  fi

  # ---------------------------------------------------------------- 7. app + shortcut
  step "$(T s7)"
  chmod +x "$ROOT/start.sh" "$ROOT/stop.sh" "$ROOT/Sparky.command" 2>/dev/null
  if [ -z "$NOSHORT" ]; then
    if make_app "$ROOT" "$HOME/Applications/Sparky.app"; then ok "$(T app)"; else warn "$(T noapp)"; fi
  fi
  local lnk="$HOME/Desktop/Sparky.command"
  if [ -z "$NOSHORT" ] && [ -d "$HOME/Desktop" ] && ask "$(T shortq)" y; then
    printf '#!/bin/bash\n# Starts Sparky (created by install.sh)\nexec %q\n' "$ROOT/start.sh" >"$lnk" && chmod +x "$lnk"
    ok "$(T shortcut)"
  else
    info "$(T noshort)"
  fi

  # ---------------------------------------------------------------- done
  printf '\n   %s✔  %s%s\n      %s\n      %s\n\n' "$C_G$C_B" "$(T ready)" "$C_0" "$(T launchhow)" "$(T launchhow2)"
  if [ -z "$NOLAUNCH" ]; then
    info "$(T opening)"
    "$ROOT/start.sh" && printf '    %s%s%s\n' "$C_M" "$(T bye)" "$C_0"
  fi
  echo
}

main "$@"
