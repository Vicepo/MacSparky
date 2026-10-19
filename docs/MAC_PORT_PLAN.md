# MacSparky — porting plan (Windows → macOS)

Target machine for development and testing: **Apple M3, 16 GB unified memory, macOS 26**.
Starting point: upstream `anisayari/sparky` at `7f8e9fc` (v1.6.1). On macOS today: lint clean, 202 tests pass,
3 skipped (one of them Windows-only: computer mode's Recycle Bin / PowerShell).

## Guiding decision: stay cross-platform, branch on the OS

Keep the Windows code and add macOS branches (`sys.platform == "darwin"`) next to it, instead of rewriting files
for Mac only. Reason: upstream keeps shipping features, and we want `git merge upstream/main` to stay easy.
Small, local `if` branches merge cleanly; rewritten files conflict on every update.

Rule of thumb: one small helper per OS difference (in `config.py` or a new `app/platform_util.py`), called from
the modules — not `if mac:` scattered everywhere.

## What is Windows-only today

| Area | Where | Windows today | macOS replacement |
|---|---|---|---|
| Install | `install.ps1`, `install.bat` | winget Python, CUDA PyTorch, llama.cpp Windows zip, portable Node, desktop shortcuts | new `install.sh` (Homebrew Python 3.12, PyTorch with MPS, llama.cpp macOS arm64 build with Metal, Node from Homebrew) |
| Start / stop | `start.ps1`, `stop.ps1`, `.bat` | PowerShell `Start-Process`, hidden window | `start.sh` / `stop.sh`, plus a double-clickable `Sparky.command` |
| Paths | `app/config.py:23` | `llama-server.exe` | `llama-server` (no extension) |
| Hidden windows | `config.NOWIN` | `CREATE_NO_WINDOW` | already `0` off Windows — nothing to do |
| System scan | `app/syscheck.py:28-80` | PowerShell CIM, `nvidia-smi` | `sysctl` (chip name, RAM), Apple Silicon = "unified" mode on Metal; bandwidth table for M1–M4 |
| GPU monitor | `app/server.py:325` | `nvidia-smi` every 5 s | no NVIDIA: show RAM pressure via `psutil` (GPU stats on Mac need `sudo powermetrics` — skip) |
| LLM launch | `app/server.py:149` | `-ngl 99` when GPU found | same flags; works once syscheck reports Metal as GPU |
| Image model choice | `app/catalog.py:69-80` | `nvidia-smi` picks FP4/FP8 encoder | Mac: no FP4/FP8 on MPS — needs fp16/bf16 or GGUF variants (**to verify**) |
| Dictation | `app/stt.py:17` | `torch.cuda` | `torch.backends.mps` (float16 on MPS) |
| Computer mode | `app/computer.py` | shell32 known folders, drive letters, Recycle Bin via `SHFileOperationW`, PowerShell `run`, Windows-specific prompt | `~/Desktop`…`~/Movies`, `/` and `/Volumes`, Trash via Finder (`osascript`) or `send2trash`, `open`, `zsh -c`, Mac prompt text, protected `/System`, `/Library`, `/usr`, `/bin`, `/sbin`, `/private` |
| Project checker | `app/checker.py:20,81,227` | `node.exe`, `npm.cmd`, Edge/Chrome in `C:\Program Files` | `node` / `npm`, `/Applications/Google Chrome.app/…`, Edge, Brave, Chromium |
| MCP servers | `app/mcp.py:107` | `taskkill /T` | kill the process group (`start_new_session=True` + `os.killpg`) |
| Local model scan | `app/localscan.py:14-29,149-159` | `%LOCALAPPDATA%`, drive letters | `~/Library/Application Support/…` (GPT4All, Jan), `~/.lmstudio`, `~/.ollama`, HF cache; `/Volumes/*` as extra roots |
| Updater | `app/updater.py:10-14,83` | checks `anisayari/sparky`, restarts via PowerShell, `irm … \| iex` | point to `Vicepo/MacSparky`; restart with a detached `nohup` / `os.execv`; `curl … \| bash` install command |
| UI / texts | `app/index.html` (6 mentions), `README.md` | "Windows", `start.bat` | Mac wording |
| CI | `.github/workflows/ci.yml` | Windows + Ubuntu | add `macos-latest` (Apple Silicon runner) |

Already portable: the server, harness, chat, cloud providers, RAG, memory, scheduler, web search, TTS
(onnxruntime + espeak-ng installed fine on arm64), attachments, the whole UI.

## Phases

Each phase ends with: tests green on macOS, a commit, a push to `origin`.

### Phase 1 — Foundations (small, low risk)
1. OS helper: `IS_MAC` / `IS_WIN` and the `llama-server` path without `.exe` in `config.py`.
2. Updater: repo → `Vicepo/MacSparky`, macOS restart path, Mac install command.
3. CI: add a `macos-latest` job running lint + tests.

### Phase 2 — Run it on a Mac (the big milestone)
1. `install.sh`: checks Homebrew → Python 3.12 → `runtime/venv` → PyTorch (MPS) → ComfyUI (+ IP-Adapter) →
   llama.cpp macOS arm64 release → Node. Same `runtime/` layout as Windows, so the Python code finds everything.
2. `start.sh` / `stop.sh` / `Sparky.command`.
3. `syscheck.py`: detect Apple Silicon, report "unified" mode, sensible model memory budget
   (16 GB Mac → ~10 GB for models, leaving room for macOS).
4. GPU monitor fallback in `server.py`.
5. **Milestone:** Sparky opens at `http://127.0.0.1:7860`, chat works with a small local model on Metal.

### Phase 3 — Images, voice, dictation
1. ComfyUI on MPS: test which catalog image models actually run; add Mac-friendly variants (fp16 / GGUF) where
   FP8/INT8 files fail. Big models (Qwen Image, 16 GB) will not fit in 16 GB — hide them on small Macs.
2. `stt.py`: MPS device.
3. TTS: download a Piper voice, un-skip `test_tts.py`.
4. Video generation: probably not realistic on a 16 GB M3 — check, then hide or keep behind a warning.

### Phase 4 — Computer mode on macOS
Folders, Trash, `open`, `zsh` commands, protected folders, disks (`/`, `/Volumes`), screenshot (needs the
Screen Recording permission), assistant prompt in Mac terms. Write the macOS counterpart of the skipped test.
This is the area with the most security weight — every path check needs tests.

### Phase 5 — Remaining modules
`checker.py` (browsers, node/npm), `mcp.py` (process groups), `localscan.py` (Mac locations, `/Volumes`).

### Phase 6 — Polish and release
README for Mac (install, screenshots), UI texts, version `1.6.1-mac.1`, GitHub release.

## Risks / open questions
- **FP8 / INT8 image models on MPS**: PyTorch's MPS backend has limited support for 8-bit float types; several
  catalog models may need other files. To test early in Phase 3.
- **16 GB unified memory**: LLM + image model cannot both stay loaded; Sparky already unloads ComfyUI before
  loading another big model (`free_comfy_memory`) — keep that path working.
- **Upstream merges**: the original changes often; sync regularly (`git fetch upstream && git merge upstream/main`)
  so conflicts stay small.
- **macOS permissions**: screenshots and controlling Finder ask for user permission the first time.
