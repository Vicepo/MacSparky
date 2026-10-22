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
Detailed plan: [PHASE3_PLAN.md](PHASE3_PLAN.md).
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

## Progress (branch `mac-port`)

- **Phase 1 — done** (`4716ad9`). Extra fix: off Windows, `updater._restart` did nothing (an update never came back);
  version compare now uses every number so `1.6.1-mac.2 > 1.6.1-mac.1`.
- **Phase 2 — done** (`8d92383`). Verified on the M3 / 16 GB: Qwen3.5 4B on Metal, 284 tok/s prompt, 25 tok/s
  generation, chat through `/api/chat`, start/stop cycle. Changes vs. the plan: GPU monitor uses `ioreg` (real GPU use
  and memory, no sudo) instead of RAM only; llama.cpp macOS builds are `.tar.gz` with a sha256 digest (checked).

### Pending / to review
- ~~**Security (also on Windows, upstream):** llama-server ran with no API key and `CORS: *`~~ **fixed**: Sparky
  gives llama-server a random key (`data/llm.key`, owner-only, passed through the environment) and limits CORS to
  Sparky's origin; an unprotected llama-server left from an older session is restarted. Only `/health` stays open.
  Worth reporting upstream (`anisayari/sparky`).
- ~~**macOS:** `psutil.net_connections()` needs root~~ **fixed**: `stop_llm` / `stop_comfy` crashed with AccessDenied,
  so switching or restarting the assistant failed on a Mac; they now ask each candidate process for its own sockets.
- ~~**Computer mode said "done" without doing it**~~ **fixed**: the small model put the script in an artifact (Sparky's
  panel only) and replied "your script is in your folder". The prompt and the post-artifact note now say an artifact is
  not on the disk and point to `write`; a reply claiming a file is on the computer with no real write this turn is sent
  back to the model (`DISK_CLAIM`, at most twice). Live on Qwen3.5 4B: 2/3 runs wrote the file after approval, 3/3 honest.
- **Phase 4 (security part) done early:** macOS protected folders (`/System`, `/Library`, `/Applications`, `/usr`, `/opt`,
  `/private`, `/etc`, `/var`..., `~/Library`, every hidden file of the home folder, disk roots), symlinks resolved and case
  folded; Trash (`/usr/bin/trash`, Finder fallback), `open`, `zsh` with a timeout that stops the whole process group,
  `/` + `/Volumes` disks, Mac prompt. Still to do in phase 4: screenshot permission message, UI texts ("Recycle Bin").
  Note: the macOS test sends `sparky-test-trash.txt` to the Trash on each local run.
- **Fixes after the second real test (A, B, D, E, F, G) done.** Thinking spirals cut early (D); page crash on an artifact
  that turns into a project file (E); an artifact with a disk path goes through computer write (F) and the prompt says
  saving = write only (G); the context added to each message is marked as Sparky's (A); no imaginary image model (B).
- ~~**C:** with no image model installed, leave the image-generation instructions out of the system prompt~~ **done**:
  `prompt.md` stays one file (easier upstream merges); its image-only rules are marked `{{images}}…{{/images}}` and
  `harness.image_rules` drops them when no image model is chosen (with one, the prompt is byte-identical to before).
  Measured on the M3 / Qwen3.5 4B, cache off: 2 724 → 1 268 tokens, first answer 8.5 s → 4.2 s. Same answers on a
  4-message check (image refused with the install hint, code artifact or short reply, chat, explanation).
- Note: running tests while Sparky answers chats makes both slow on 16 GB (338 s instead of 25 s for the suite).
- **Version naming (phase 6):** `1.6.1-mac.1` fails `test_version_is_semver`; relax the test or pick another scheme.
- **install.ps1** clones `Vicepo/MacSparky`, the repository the updater checks (was `anisayari/sparky`).
- **CI:** the new macOS jobs and ShellCheck have not run yet (needs a push).
- Context window: `auto_ctx` picks 65 536 tokens on a 16 GB Mac with the 4B model; fine here, watch memory with
  bigger models (phase 3 adds images on top).
