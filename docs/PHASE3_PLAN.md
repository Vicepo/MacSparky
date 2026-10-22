# MacSparky — Phase 3 plan: images, dictation, read-aloud, video on macOS

Parent plan: [MAC_PORT_PLAN.md](MAC_PORT_PLAN.md), phase 3. Target: **Apple M3, 16 GB unified memory, macOS 26**.
Same rule as the parent plan: keep the Windows code, add small `config.IS_MAC` branches in one place per
difference, so `git merge upstream/main` stays easy. Each work item ends with tests green on macOS and a commit.

## 1. Where things stand (checked on 2026-10-22)

**Runtime on the M3**
- `runtime/venv`: Python **3.13.4** (the installer prefers 3.12 but accepts 3.13), PyTorch **2.14.1**, `mps` available.
- ComfyUI **0.42.0** (`a2440bc`, 2026-10-19) + `ComfyUI_IPAdapter_plus`. It starts on MPS: `Device: mps`,
  `vram state: SHARED`, sub-quadratic attention. `comfy-aimdo` is off on Darwin (fine). `comfy_kitchen` has only its
  `eager` backend (no CUDA, no Triton).
- No image model is installed (`ckpt: null`). No Piper voice is installed. Whisper turbo is installed.

**Code that blocks images on a Mac today**
- `syscheck.assess()` (line 105): `"images": ... and not apple`. So no image model is recommended, and the scan shows the
  note "Mac : la génération d'images n'est pas encore validée" (also translated in `index.html:1035`).
- `catalog.klein()` (line 69): picks the FLUX.2 Klein text encoder with `nvidia-smi` (FP4 on Blackwell, FP8 elsewhere).
  On a Mac it falls back to **FP8**.
- `stt._load()`: `torch.cuda` only. On a Mac Whisper runs on the CPU in float32.
- Nothing hides the models that cannot run here: the library shows Qwen-Image (16 GB), LTX (39 GB), Wan (18 GB).

**What already works and stays as is**
- `install.sh` installs PyTorch (MPS), ComfyUI and IP-Adapter. `start_comfy` / `stop_comfy` / `free_comfy_memory` work
  without root (fixed after phase 2).
- Commit C: with no image model, the image rules are left out of the system prompt. With one, the prompt is the same
  as on Windows.
- The chat image tools (`tool_generate`, `tool_edit`, `face_pass`, `qwen_masked_edit`), Studio, the model switch
  steps and speed measurement (`record_speed`) don't depend on the OS.

**Tests run on the M3 (scratch scripts, not in the repo)**

| Test | Result |
|---|---|
| `float8_e4m3fn` / `float8_e5m2` tensor → MPS | moving it works |
| Any cast of that FP8 tensor on MPS (`.to(float16)`) | **fails**: `Undefined type Float8_e4m3fn` |
| `comfy_kitchen.dequantize_per_tensor_fp8` on MPS | **fails**: same error |
| `int8` tensor on MPS, `comfy_kitchen.dequantize_int8_simple` on MPS | works |
| bf16 matmul on MPS | works |

What this means: **every FP8 / FP4 file in the catalog is a risk on a Mac**. ComfyUI turns FP8 weights into fp16/bf16
when it loads them, but only if it thinks the model fits at 2 bytes per parameter. Otherwise it keeps them in FP8 and the
first sampling step fails. `*_fp8_mixed` and `*_scaled` files (comfy_quant format) stay quantized and are decoded on the
GPU, so they **always fail** on MPS. INT8 (`*_int8_convrot`) should work, but slowly (eager decoding).

## 2. Catalog check: what can run on a Mac

Sizes are taken from the Hugging Face API (GiB).

| Catalog entry | Files today | MPS verdict | Mac replacement | 16 GB M3 |
|---|---|---|---|---|
| **FLUX.2 Klein 4B** `klein4b` | diffusion `flux-2-klein-4b-fp8` 3.79 · text encoder `qwen_3_4b_fp8_mixed` 5.25 · VAE `flux2-vae` 0.3 | text encoder fails for sure (fp8_mixed); diffusion model at risk | **GGUF** via ComfyUI-GGUF: `unsloth/FLUX.2-klein-4B-GGUF` (Q8_0 4.01 · Q5_K_M 2.86 · Q4_K_M 2.43) + `unsloth/Qwen3-4B-GGUF` (Q8_0 3.99 · Q4_K_M 2.33) + same VAE. bf16 fallback: `black-forest-labs/FLUX.2-klein-4B/flux-2-klein-4b.safetensors` 7.22 + `Comfy-Org/z_image_turbo/.../qwen_3_4b.safetensors` 7.49 | **Recommended** (GGUF, ~5–8 GB) |
| **Juggernaut XL v9** | single fp16 checkpoint 6.6 + IP-Adapter 3.9 | should run as is | none | visible, "heavy" |
| **Animagine XL 4.0** | single fp16 checkpoint 6.5 + IP-Adapter 3.9 | should run as is | none | visible, "heavy" |
| **Qwen-Image 2.1** | diffusion int8_convrot 6.76 · text encoder `qwen3vl_8b_int8_convrot` 8.71 · VAE 0.63 | INT8: should run, slowly | none for now (bf16 = 13.25 + 16.33) | **hidden** (16.1 GB > budget) |
| **LTX-2.5 22B** (video) | int8, 38.7 total | INT8 | none | **hidden** |
| **Wan 2.2 5B** (video) | unet fp16 9.31 · text encoder `umt5_xxl_fp8_e4m3fn_scaled` 6.27 · VAE 1.31 | text encoder fails (FP8 scaled) | `umt5_xxl_fp16` 10.59, or `QuantStack/Wan2.2-TI2V-5B-GGUF` Q8_0 5.03 + a umt5 GGUF | **hidden** |
| Custom SDXL from Hugging Face | single `.safetensors` > 1.5 GB | fp16: OK; FP8 merges: fail | filter by file name | visible if not FP8 |

ComfyUI-GGUF (city96) is already compatible with what Sparky needs. `TXT_ARCH_LIST` has `qwen3`, `CLIPLoaderGGUF`
reuses the core `CLIPLoader` types (so `flux2` is there), and GGUF files are read from `diffusion_models/` and
`text_encoders/`. Its `IMG_ARCH_LIST` has `flux` but not `flux2`; **checked 2026-10-22:** the header of
`flux-2-klein-4b-Q4_K_M.gguf` says `general.architecture = flux` (first 64 KB read, no download), so the loader accepts
it. Still to confirm in K2: ComfyUI's model detection must see FLUX.2 (not FLUX.1) from the tensor names.

Also checked 2026-10-22: `unsloth/FLUX.2-klein-4B-GGUF`, `unsloth/Qwen3-4B-GGUF` and `black-forest-labs/FLUX.2-klein-4B`
exist, are **not gated** and are Apache-2.0. All catalog files are `.safetensors` / `.gguf` (no pickle, no code run at
load). ComfyUI listens on `127.0.0.1` only.

## 3. Design decisions

1. **Mac files go in the same catalog entry (same id `klein4b`)**, chosen by an `IS_MAC` branch inside `klein()`. This is
   how the FP4/FP8 choice already works. Settings (`ckpt`), measured speeds, tests and the UI keep their ids, and an
   upstream merge only touches `klein()`.
2. **Use GGUF on small Macs, not bf16.** In the chat, the vision LLM stays loaded while images are made, because it
   checks each image, up to `max_steps`. On 16 GB, about 10 GB is usable: LLM ~3.2 GB + mmproj ~0.9 + KV cache +
   image model. bf16 Klein needs ~15 GB with its text encoder; GGUF needs ~5–8 GB. bf16 is kept as a fallback, and as the
   choice for Macs with ≥ 32 GB if it is faster there (GGUF is decoded on the fly).
3. **One rule hides what cannot run, the same for catalog and custom models:** `catalog.runs_here(m)`. On a Mac it is
   False when a file name looks like FP8/FP4 (`fp8|fp4|nvfp4|mxfp8`), or when an image/video model has `fit == 0`.
   `listing()`, `recommend()` and `install()` all use it. On Windows/Linux it is always True, so nothing changes there.
4. **Speed estimates on Apple Silicon.** Image generation is limited by GPU compute, not memory bandwidth. Today's formula
   (`est_secs * (230/bw)^0.7`) would promise ~6 s per Klein image on the M3. The spike gives a real M3 value
   (`est_secs_mac`), scaled by the chip's bandwidth (already in `syscheck`) as a stand-in for GPU size (Pro/Max/Ultra).
   A measured speed (`record_speed`) replaces the estimate after the first image.
5. **Memory on unified memory.** ComfyUI on MPS uses `SHARED` mode, so its models stay in RAM. The existing
   `free_comfy_memory()` before an LLM switch stays. New: `auto_ctx()` sets aside the image budget when an image model
   is active on a unified-memory machine (expected 65 536 → 32 768 tokens on the M3; the spike confirms).

## 4. Work items

### 3.0 Spike: measure first (M3, ~half a day, mostly downloads)
Goal: replace every "to check" in this plan with a number. The results go into MAC_PORT_PLAN.md.

**Safety rules for the spike (the test Mac is a fanless MacBook Air M3, 16 GB):**
- Plugged in (not on battery). Sparky is stopped, or at least its assistant is unloaded, for S1–S4 and K2–K4. The spike
  starts its own ComfyUI and never writes `data/settings.json`.
- **Memory guard** in the spike script: it stops ComfyUI (and the run) as soon as swap used grows by more than 3 GB
  over its start value, or `memory_pressure` reports critical. A frozen Mac is the main risk here, not damage.
- The Air slows down when it gets hot: time 5 images in a row, not one, and record the sustained value.
- No bf16 Klein run on this Mac (K5 removed: ~15 GB peak means heavy swap, and decision 2 keeps bf16 for ≥ 32 GB).
- No FP8 Klein download (K1 removed: 9 GB to show a failure the scratch tests already proved).

Setup, by hand, not committed:
- ComfyUI-GGUF **at a pinned commit**, read before its first run (it runs inside ComfyUI with the user's rights):
  `git clone https://github.com/city96/ComfyUI-GGUF runtime/ComfyUI/custom_nodes/ComfyUI-GGUF` then
  `git -C runtime/ComfyUI/custom_nodes/ComfyUI-GGUF checkout 6ea2651e7d` (main on 2026-01-12), and `pip install` of a
  pinned `gguf` version.
- Download into `runtime/ComfyUI/models/` (~24 GB, 130 GB free): Juggernaut XL v9 + IP-Adapter; Klein GGUF Q8_0 and
  Q4_K_M; Qwen3-4B GGUF Q8_0 and Q4_K_M; `flux2-vae`. At the end, delete the quant that is not chosen.
- A scratchpad script sends graphs from `harness.build_graph` / `harness.build_klein` (with GGUF loaders swapped in) to
  ComfyUI's API. It records success, warmup time, seconds per 1024² image, peak memory (`psutil`,
  `sysctl vm.swapusage`) and whether the output is a real image (not black, no NaN).

| # | Test | Expected / decides |
|---|---|---|
| S1 | SDXL Juggernaut, text → image 1024², 30 steps, dpmpp_2m karras | works; s/image; black image → VAE flag |
| S2 | SDXL image → image and inpaint with a mask (`build_graph(src, mask)`) | works |
| S3 | SDXL + IP-Adapter, face and style references | works on MPS |
| S4 | SDXL `face_pass` (crop, denoise 0.38) | works |
| K2 | Klein GGUF Q8_0 + Qwen3-4B GGUF Q8_0, text → image 1024², 4 steps | works? FLUX.2 detected? s/image, peak memory |
| K3 | Same with Q4_K_M + Q4_K_M | quality vs speed vs memory |
| K4 | Klein edit by instruction (`size=None`, image 1) and 2 references | works |
| M1 | Klein **Q4** with Sparky running Qwen3.5 4B at **32 768** ctx: chat "draw a cat", 3 images, 1 edit. Q8 only if Q4 stays under the guard with room to spare | total time; swap growth < 1 GB |
| M2 | Switch LLM ↔ image model, then back | memory comes back (`free_comfy_memory`) |
| F1 | ComfyUI flags: default vs `--use-pytorch-cross-attention`, `--force-fp16`; env `PYTORCH_ENABLE_MPS_FALLBACK=1` | best flags |

Exit: one quant choice per Mac memory class (≤ 16 GB / 24 GB / ≥ 32 GB), the ComfyUI flags, the SDXL VAE dtype, the
`est_secs_mac` values. **If ComfyUI-GGUF can't load Klein GGUF:** the 16 GB recommendation becomes Klein bf16
diffusion + Qwen3-4B GGUF text encoder (~10 GB, text encoder unloaded after encoding), or SDXL if that does not fit.
Then 3.2 / 3.3 change to match.

### 3.1 ComfyUI on macOS: install and start
- `install.sh` step 4: `get_repo ComfyUI-GGUF https://github.com/city96/ComfyUI-GGUF "$COMFY/custom_nodes/ComfyUI-GGUF" main`,
  and add `-r "$COMFY/custom_nodes/ComfyUI-GGUF/requirements.txt"` to the pip line. `get_repo` skips existing folders,
  so running the installer again also adds it to existing installs.
- `requirements.txt`: `gguf; sys_platform == "darwin"`. The updater already runs `pip install -r requirements.txt`
  after a `git pull`, and Windows is not affected.
- `get_repo` for ComfyUI-GGUF checks out the **pinned commit** (`6ea2651e7d`, or the one reviewed in the spike), never
  `main`; `gguf` is pinned to the tested version in `requirements.txt`.
- Existing installs updated through the updater (no installer rerun): **no automatic clone when ComfyUI starts**
  (downloading and running code silently at each start is the riskiest thing this phase could add). Instead, installing
  a GGUF model from the library when ComfyUI-GGUF is missing asks once ("This model needs the ComfyUI-GGUF extension
  (city96, pinned version). Install it?"); a no leaves everything as it is.
- `start_comfy()` on a Mac: `env=os.environ | {"PYTORCH_ENABLE_MPS_FALLBACK": "1"}`, so an operation missing on MPS runs on
  the CPU instead of stopping the job. Add the flags chosen in F1.
- On a Mac, `install.sh` checks out the tested ComfyUI commit (`a2440bc`) instead of `master`, and the commit goes in
  MAC_PORT_PLAN.md. Moving to a newer ComfyUI = test it, then change the pin.
- Checks: `bash -n` / ShellCheck (CI `shell` job); a fresh `./install.sh` run **only on a copy in another folder**, never
  on the working install (it may offer `brew install python@3.12` / `node`).

### 3.2 Catalog: Mac files and visibility (`app/catalog.py`)
- `klein()`: `if config.IS_MAC:` returns the GGUF files (`diffusion_models/flux-2-klein-4b-<Q>.gguf`,
  `text_encoders/Qwen3-4B-<Q>.gguf`, the same VAE) with `"gguf": True`, `"unet": <name>`, `"clip": <name>` and a size
  computed from those files. It must not call `nvidia-smi` on a Mac. The quant depends on total memory, read with
  `psutil.virtual_memory()` like `server.auto_ctx()` does (`klein()` runs at import, before syscheck). Values come
  from the spike.
- On every OS, store the diffusion file name in the entry (`"unet"`) instead of hard-coding it in `build_klein`.
- `runs_here(m)` (decision 3). Use it in `listing()` (skip), `syscheck.recommend()` (skip), `install()` and
  `hf_install()` (refuse with a clear message, in case the API is called directly), and `hf_files(kind="image")` (filter
  FP8 checkpoints on a Mac).
- `indicators()` image and video branches: on Apple, `secs = m["est_secs_mac"] * (84 / bw) ** 0.8` when the entry has it
  (84 = the M3's effective bandwidth). Add `est_secs_mac` to Klein and the two SDXL entries.
- Tests (`tests/test_catalog_mac.py`, `IS_MAC` and memory patched): Klein's files are GGUF and contain no `fp8`; on a 16 GB
  Mac `listing()` has no Qwen-Image / LTX / Wan; on a 64 GB Mac Qwen-Image is visible; an FP8 custom SDXL checkpoint is
  hidden on Mac and visible on Windows; Windows entries are unchanged (the existing tests stay green as they are).

### 3.3 Graph builders (`app/harness.py`)
- `build_klein(prompt, seed, size, images, steps, clip, unet, gguf=False)`: when `gguf`, use
  `{"class_type": "UnetLoaderGGUF", "inputs": {"unet_name": unet}}` and
  `{"class_type": "CLIPLoaderGGUF", "inputs": {"clip_name": clip, "type": "flux2"}}`. The rest of the graph doesn't
  change. `build_instruct(m, …)` passes `m["unet"]`, `m["clip"]`, `m.get("gguf")`.
- `_switch_image` warmup (256², 1 step) goes through `build_instruct`: nothing else to change.
- SDXL: no graph change. If S1 gives black images, the fix is a ComfyUI flag in 3.1 (`--fp32-vae` / `--bf16-vae`),
  not the graph.
- Tests: with `gguf` the graph uses the two GGUF loaders with the names from the entry; without `gguf` it is exactly the
  same as today (compare to a saved dict).

### 3.4 System scan and recommendation (`app/syscheck.py`)
- `assess()`: remove `and not apple`. Images are on when `mode != "cpu"` and usable memory ≥ 5.5 GB. A 16 GB Mac
  (10 GB usable) is in; an 8 GB Mac (2 GB usable) is out.
- `image_gb`: on Apple, the size of the Mac Klein entry instead of the fixed 7.5. It feeds `fit` for the LLMs
  ("fits with image generation").
- `recommend()`: Klein on Mac when `runs_here` and `fit ≥ 1`. Remove the "not validated" note. Add a note for Macs below
  the limit ("8 GB Mac: images need 16 GB or more"), in `NOTES_EN` and in the `index.html` translation table (line 1035).
- Tests: update `test_16gb_mac_runs_on_metal…` (images True, `recommended["image"] == "klein4b"`, no "Mac :" note);
  add an 8 GB Mac (no images, the new note) and a 64 GB Mac (Klein, Qwen-Image visible).

### 3.5 Memory on 16 GB (`app/server.py`)
- `auto_ctx(m)`: on a unified-memory machine with an image model chosen (`SETTINGS["ckpt"]`), also subtract
  `image_gb` from `spare`. On a unified-memory Mac with ≤ 16 GB, choosing an image model **restarts the assistant once**
  so the smaller context applies at once: without it, the first session runs 65 536 tokens of context plus the image
  model, the heavy-swap case. The model switch overlay already covers a restart. Other machines: no restart.
- After M1, decide whether ComfyUI should free Klein after each chat turn on ≤ 16 GB Macs (`free_comfy_memory()` at the
  end of a turn that made images). That is slower for the next image, but leaves room for the LLM. Default: keep Klein
  loaded unless M1 shows heavy swapping.
- Check by hand that the memory gauge (`ioreg` GPU share, from commit 3f2f229) shows ComfyUI's share in a way that makes
  sense while an image is being made.
- Test: `auto_ctx` with and without an image model on a patched 16 GB unified machine.

### 3.6 Dictation on MPS (`app/stt.py`)
- One `_device()` helper: CUDA → (`"cuda:0"`, float16); else `torch.backends.mps.is_available()` → (`"mps"`, float16);
  else (`"cpu"`, float32). Free memory: `torch.cuda.empty_cache()` or `torch.mps.empty_cache()`.
- Risk: Whisper in float16 on MPS can give empty text or repeated words with some PyTorch versions. Compare a 10 s French
  sample and an English one with the CPU result. If they differ, use float32 on MPS (turbo = 1.6 GB, which is fine).
- Whisper loads on first use and is freed after 10 min idle. With Klein and the LLM loaded, check M1 + one dictation.
- Tests: unit test of `_device()` with patched `torch.cuda` / `torch.backends.mps`. By hand: dictate in the UI, measure
  10 s of speech (the catalog says `gpu_secs: 1` for turbo).

### 3.7 Read-aloud (TTS)
- The code is already portable (onnxruntime on CPU, `espeakng-loader` arm64). Install `en_US-lessac-medium` and
  `fr_FR-siwis-medium` from Settings (~60 MB each).
- Check that `tts._espeak_lib()` finds the espeak-ng `.dylib` with ctypes on macOS.
- `test_tts.py::test_real_synthesis` then runs locally (it reads the real `models/voice/piper`). On CI it stays skipped,
  which is expected.
- By hand: read a French and an English reply aloud, check the speed setting.

### 3.8 Video on a 16 GB Mac
- **Decision: not available on the M3.** LTX is hidden by `fit == 0`, and Wan by its FP8 text encoder (3.2).
- Studio: when no video model can run here, the video mode says "Video needs a Mac with more memory (32 GB or more)"
  instead of "install a video model from the library" (`studio._run` message and the `index.html` Studio video tab,
  `videoModels` empty).
- Later (Phase 3b, needs a bigger Mac to test): Wan 2.2 5B with GGUF Q8_0 + umt5 fp16 or GGUF, labelled "experimental,
  slow", for Macs with ≥ 32 GB; LTX int8 for ≥ 64 GB. Optional now, only to write the number down: one 2 s 480p Wan
  Q4 clip on the M3.

### 3.9 UI and texts (`app/index.html`)
- Library: one quiet line under the table, "N models hidden: they don't run on this Mac", so a missing model doesn't
  look like a bug. `listing()` returns the count.
- Speed and memory tooltips (`bolts`, `memi`) work unchanged with the new estimates. Check the wording for a Mac image
  model with `fit == 1`.
- Every new string gets its EN translation in the table (the UI is French-first).
- "Auto (comme Windows)" and other OS wording: phase 6, not here.

### 3.10 Wrap-up
- MAC_PORT_PLAN.md: phase 3 progress, measured numbers (s/image, memory, dictation speed), the tested ComfyUI commit.
- `ruff check app tests` + `pytest` green on macOS; push; the macOS CI jobs run.

## 5. Order and commits

| Step | Commit | Depends on |
|---|---|---|
| 3.0 spike | none (numbers go into MAC_PORT_PLAN in 3.10, or in a "Phase 3 spike" note) | — |
| 3.1 | "Mac: ComfyUI-GGUF node, MPS fallback" | 3.0 (flags) |
| 3.2 + 3.3 | "Mac: FLUX.2 Klein in GGUF, hide models that can't run" | 3.0, 3.1 |
| 3.4 | "Mac: images recommended on Apple Silicon" | 3.2 |
| 3.5 | "Mac: context and memory with an image model" | 3.0 (M1) |
| 3.6 | "Dictation on MPS" | — (can go first) |
| 3.7 | no code change expected (voice + local test) | — |
| 3.8 + 3.9 | "Studio / library: say what this Mac can't run" | 3.2 |
| 3.10 | "Port plan: phase 3 done" | all |

3.6 and 3.7 don't depend on the image work and can be done first, or in parallel.

## 6. Done when
1. A fresh scan on the M3 recommends **FLUX.2 Klein 4B** for images; it installs from the library and becomes active
   (every switch step OK).
2. Chat: "draw …" makes an image, the assistant looks at it and answers; an edit by instruction works; time per image
   is close to the spike number; swap grows < 1 GB over a 3-image session with the 4B assistant.
3. SDXL (Juggernaut): generate, inpaint with a painted mask and an IP-Adapter reference all work in the chat.
4. Studio image mode works; video mode explains why it isn't available on this Mac.
5. The library on the M3 shows no model that can't run (no FP8-only file, no Qwen-Image, LTX or Wan).
6. Dictation runs on MPS in French and English; read-aloud works with a Piper voice; `test_real_synthesis` passes locally.
7. Windows doesn't change: non-Mac graphs and catalog entries are identical, and the existing tests pass unchanged.
8. Lint and tests green on macOS, locally and in CI.

## 7. Risks
- **ComfyUI-GGUF and FLUX.2** (`flux2` not in its list): plan B in 3.0 (bf16 diffusion + GGUF text encoder, or SDXL).
- **Speed on the M3**: if one Klein image takes ~20–40 s, an agent turn that checks and redoes images (`max_steps` 6)
  can take minutes. Measure in M1; a lower default `max_steps` on Macs with ≤ 16 GB is an option (Settings already
  allows 1–20).
- **ComfyUI moves fast** (upstream's installer clones `master`): MPS can break in a later version. On a Mac the installer
  pins the tested commit (3.1); upstream doesn't pin, so keep that branch small for merges.
- **PyTorch MPS allocator** keeps freed memory. ComfyUI's `/free` calls `torch.mps.empty_cache()`
  (`soft_empty_cache`), so check in M2 that memory really comes back.
- **Upstream merges**: `catalog.klein()`, `syscheck.assess()` and `stt._load()` change often upstream. Keep each Mac
  branch to a few lines.
- **Gated downloads**: checked 2026-10-22, none of the repos used here is gated.
- **Third-party code**: ComfyUI-GGUF and the `gguf` package run with the user's rights. Pinned versions only, read
  before the first run, and no download of code at ComfyUI start (3.1).
- **Memory on a 16 GB fanless Air**: the spike's memory guard (3.0), Q4 first in M1, and the assistant restart when an
  image model is chosen (3.5).
