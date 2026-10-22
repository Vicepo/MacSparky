"""Phase 3 of the Mac port: FLUX.2 Klein in GGUF, models that can't run on a Mac hidden, smaller images and context.
The Mac branches are tested on every OS (config.IS_MAC patched); Windows / Linux must stay exactly as before."""
import os, subprocess, types

import pytest

import catalog
import config
import harness
import server
import studio

G = 2 ** 30


@pytest.fixture
def mac(monkeypatch):
    monkeypatch.setattr(config, "IS_MAC", True)


@pytest.fixture
def not_mac(monkeypatch):
    monkeypatch.setattr(config, "IS_MAC", False)


def ram(monkeypatch, gb):
    import psutil
    monkeypatch.setattr(psutil, "virtual_memory", lambda: types.SimpleNamespace(total=gb * G, available=gb * G / 2))


# ---------------------------------------------------------------- catalog
def test_klein_on_a_16gb_mac_is_gguf_q4(monkeypatch):
    ram(monkeypatch, 16)
    m = catalog.klein_mac()
    names = [f[1] for f in m["files"]]
    assert m["id"] == "klein4b" and m["engine"] == "klein" and m["gguf"]
    assert names == ["flux-2-klein-4b-Q4_K_M.gguf", "Qwen3-4B-Q4_K_M.gguf", "split_files/vae/flux2-vae.safetensors"]
    assert m["unet"] == names[0] and m["clip"] == names[1] and not any("fp8" in n or "fp4" in n for n in names)
    assert m["files"][0][2].endswith(os.path.join("diffusion_models", names[0]))
    assert m["files"][1][2].endswith(os.path.join("text_encoders", names[1]))
    assert m["size_gb"] == 5.1 and m["est_secs_mac"] == 80


def test_klein_on_a_32gb_mac_is_gguf_q8(monkeypatch):
    ram(monkeypatch, 32)
    m = catalog.klein_mac()
    assert m["unet"] == "flux-2-klein-4b-Q8_0.gguf" and m["clip"] == "Qwen3-4B-Q8_0.gguf" and m["size_gb"] == 8.3


def test_klein_elsewhere_keeps_its_fp8_files(not_mac):
    m = catalog.klein()
    assert not m.get("gguf") and m["unet"] == "flux-2-klein-4b-fp8.safetensors"
    assert m["files"][0][:2] == ("black-forest-labs/FLUX.2-klein-4b-fp8", "flux-2-klein-4b-fp8.safetensors")


def test_only_klein_gguf_is_validated_on_a_mac(mac, monkeypatch):
    ram(monkeypatch, 32)  # big Mac: SDXL is only untested there
    assert catalog.validated_here(catalog.klein_mac()) and catalog.mac_note(catalog.klein_mac()) is None
    with monkeypatch.context() as mp:
        mp.setattr(config, "IS_MAC", False)
        fp8_klein = catalog.klein()
    assert not catalog.validated_here(fp8_klein) and catalog.mac_note(fp8_klein) == "fp8"  # same engine, FP8 files
    for mid in ("juggernaut", "animagine", "qwen21", "ltx25"):
        assert catalog.mac_note(catalog.BY_ID[mid]) == "untested", mid
    assert catalog.mac_note(catalog.BY_ID["wan22-5b"]) == "fp8"  # its text encoder is umt5 FP8
    for m in catalog.CATALOG:
        if m["kind"] in ("llm", "voice", "embed"):
            assert catalog.validated_here(m) and catalog.mac_note(m) is None, m["id"]
    sdxl = catalog.ckpt("hf:x", "x", 3, "someone/x", "x.safetensors", 6.5)
    assert catalog.mac_note(sdxl) == "untested"
    assert catalog.mac_note(catalog.ckpt("hf:y", "y", 3, "someone/y", "y_fp8.safetensors", 6.5)) == "fp8"


def test_sdxl_is_too_big_for_a_16gb_mac(mac, monkeypatch):
    ram(monkeypatch, 16)
    for mid in ("juggernaut", "animagine"):
        assert catalog.mac_note(catalog.BY_ID[mid]) == "too_big", mid
    assert catalog.mac_note(catalog.ckpt("hf:x", "x", 3, "someone/x", "x.safetensors", 6.5)) == "too_big"
    assert catalog.mac_note(catalog.BY_ID["qwen21"]) == "untested" and catalog.mac_note(catalog.BY_ID["wan22-5b"]) == "fp8"
    ram(monkeypatch, 24)
    assert catalog.mac_note(catalog.BY_ID["juggernaut"]) == "too_big"
    ram(monkeypatch, 32)
    assert catalog.mac_note(catalog.BY_ID["juggernaut"]) == "untested"


def test_small_mac_is_24gb_or_less(monkeypatch):
    monkeypatch.setattr(config, "IS_MAC", True)
    for gb, small in ((8, True), (16, True), (24, True), (32, False)):
        ram(monkeypatch, gb)
        assert config.small_mac() is small, gb
    monkeypatch.setattr(config, "IS_MAC", False)
    ram(monkeypatch, 16)
    assert not config.small_mac()


def test_no_mac_note_elsewhere(not_mac):
    assert all(catalog.validated_here(m) and catalog.mac_note(m) is None for m in catalog.CATALOG)


def _listing():
    return catalog.listing({"speed": {}})


def test_library_on_a_mac_shows_every_model_with_a_tag(mac, monkeypatch):
    ram(monkeypatch, 32)
    rows = {m["id"]: m for m in _listing()}
    assert {"juggernaut", "animagine", "qwen21", "ltx25", "wan22-5b", "qwen354"} <= rows.keys()
    assert rows["juggernaut"]["macNote"] == "untested" and rows["wan22-5b"]["macNote"] == "fp8"
    assert rows["qwen354"]["macNote"] is None


def test_library_elsewhere_has_no_tag(not_mac):
    rows = _listing()
    assert {"klein4b", "juggernaut", "qwen21", "ltx25", "wan22-5b"} <= {m["id"] for m in rows}
    assert all(m["macNote"] is None for m in rows)


def test_an_untested_model_can_be_installed_on_a_mac(mac, monkeypatch):
    seen = []
    monkeypatch.setattr(catalog, "remote_size", lambda repo, file: seen.append(file) or 0)
    monkeypatch.setattr(catalog, "fetch", lambda *a, **k: None)
    monkeypatch.setattr(catalog.os, "replace", lambda a, b: None)
    catalog.jobs["juggernaut"] = {"done": 0, "total": 1, "state": "running", "error": ""}
    catalog._install("juggernaut")
    assert catalog.jobs.pop("juggernaut")["state"] == "ok" and "Juggernaut-XL_v9_RunDiffusionPhoto_v2.safetensors" in seen


def test_hugging_face_image_search_works_on_a_mac(mac, monkeypatch):
    monkeypatch.setattr(catalog, "hf_get", lambda path: [{"id": "RunDiffusion/Juggernaut-XL-v9", "downloads": 9, "likes": 1}])
    assert catalog.hf_search("juggernaut", "image")[0]["repo"] == "RunDiffusion/Juggernaut-XL-v9"


# ---------------------------------------------------------------- ComfyUI-GGUF extension
def test_gguf_node_is_cloned_at_the_reviewed_commit(monkeypatch, tmp_path):
    d = tmp_path / "custom_nodes" / "ComfyUI-GGUF"
    monkeypatch.setattr(catalog, "GGUF_DIR", str(d))
    calls = []

    def fake(cmd, **kw):
        calls.append(list(cmd))
        if cmd[:2] == ("git", "init"):
            os.makedirs(cmd[-1])
        return subprocess.CompletedProcess(cmd, 0, "", "")
    monkeypatch.setattr(catalog.subprocess, "run", fake)
    monkeypatch.setattr("importlib.util.find_spec", lambda name: object())  # gguf already installed
    catalog.ensure_gguf_node()
    assert d.is_dir() and not (tmp_path / "custom_nodes" / "ComfyUI-GGUF.part").exists()
    fetch = next(c for c in calls if "fetch" in c)
    assert fetch[-2:] == list(catalog.GGUF_NODE) and catalog.GGUF_NODE[1] == "6ea2651e7df66d7585f6ffee804b20e92fb38b8a"
    calls.clear()
    catalog.ensure_gguf_node()  # already there: nothing runs
    assert calls == []


def test_gguf_node_failure_leaves_nothing_behind(monkeypatch, tmp_path):
    d = tmp_path / "ComfyUI-GGUF"
    monkeypatch.setattr(catalog, "GGUF_DIR", str(d))

    def fake(cmd, **kw):
        if cmd[:2] == ("git", "init"):
            os.makedirs(cmd[-1])
            return subprocess.CompletedProcess(cmd, 0, "", "")
        return subprocess.CompletedProcess(cmd, 128, "", "fatal: unable to access")
    monkeypatch.setattr(catalog.subprocess, "run", fake)
    with pytest.raises(RuntimeError, match="ComfyUI-GGUF"):
        catalog.ensure_gguf_node()
    assert not d.exists() and not (tmp_path / "ComfyUI-GGUF.part").exists()


def test_gguf_package_is_installed_pinned_when_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(catalog, "GGUF_DIR", str(tmp_path))  # node already there
    calls = []
    monkeypatch.setattr(catalog.subprocess, "run", lambda cmd, **kw: calls.append(cmd) or subprocess.CompletedProcess(cmd, 0, "", ""))
    monkeypatch.setattr("importlib.util.find_spec", lambda name: None)
    catalog.ensure_gguf_node()
    assert calls and calls[0][-1] == "gguf==0.19.0" and calls[0][1:4] == ("-m", "pip", "install")


def test_requirements_pin_the_same_gguf_version():
    with open(os.path.join(config.ROOT, "requirements.txt"), encoding="utf-8") as f:
        assert f'{catalog.GGUF_PKG}; sys_platform == "darwin"' in f.read()


# ---------------------------------------------------------------- graphs
def test_klein_graph_elsewhere_is_unchanged():
    g = harness.build_klein("a fox", 1, size=(1024, 1024))
    assert g["1"] == {"class_type": "UNETLoader", "inputs": {"unet_name": "flux-2-klein-4b-fp8.safetensors", "weight_dtype": "default"}}
    assert g["2"] == {"class_type": "CLIPLoader", "inputs": {"clip_name": "qwen_3_4b_fp4_mixed.safetensors", "type": "flux2", "device": "default"}}
    assert harness.build_instruct({"engine": "klein", "clip": "qwen_3_4b_fp8_mixed.safetensors"}, "a fox", 1, size=(1024, 1024)) \
        == harness.build_klein("a fox", 1, size=(1024, 1024), clip="qwen_3_4b_fp8_mixed.safetensors")


def test_klein_graph_with_gguf_swaps_only_the_two_loaders():
    m = {"engine": "klein", "unet": "flux-2-klein-4b-Q4_K_M.gguf", "clip": "Qwen3-4B-Q4_K_M.gguf", "gguf": True}
    g = harness.build_instruct(m, "a fox", 1, size=(768, 768))
    plain = harness.build_klein("a fox", 1, size=(768, 768), clip=m["clip"], unet=m["unet"])
    assert g["1"] == {"class_type": "UnetLoaderGGUF", "inputs": {"unet_name": "flux-2-klein-4b-Q4_K_M.gguf"}}
    assert g["2"] == {"class_type": "CLIPLoaderGGUF", "inputs": {"clip_name": "Qwen3-4B-Q4_K_M.gguf", "type": "flux2"}}
    assert {k: v for k, v in g.items() if k not in ("1", "2")} == {k: v for k, v in plain.items() if k not in ("1", "2")}


# ---------------------------------------------------------------- image size
def test_small_mac_draws_768_sized_images(monkeypatch):
    monkeypatch.setattr(harness, "IMAGE_MP", 0.5625)
    assert harness.mp_size(1024, 1024) == (768, 768)
    w, h = harness.mp_size(832, 1216)
    assert w % 16 == 0 and h % 16 == 0 and abs(w / h - 832 / 1216) < 0.02 and 0.5 < w * h / 2**20 < 0.62
    from PIL import Image
    assert harness.fit_1mp(Image.new("RGB", (2048, 1536))).size == (888, 664)


def test_image_size_elsewhere_is_unchanged(monkeypatch):
    monkeypatch.setattr(harness, "IMAGE_MP", 1.0)
    from PIL import Image
    assert harness.fit_1mp(Image.new("RGB", (2048, 2048))).size == (1024, 1024)
    if not config.IS_MAC:
        assert harness.SIZES == {"square": (1024, 1024), "portrait": (832, 1216), "landscape": (1216, 832)}


# ---------------------------------------------------------------- server
def test_comfyui_on_a_mac_starts_with_mps_fallback_and_sdpa(mac, monkeypatch):
    seen = {}
    monkeypatch.setattr(server, "port_listening", lambda port: False)
    monkeypatch.setattr(server.os.path, "exists", lambda p: True)
    monkeypatch.setattr(server, "_spawn", lambda cmd, log, **kw: seen.update(cmd=cmd, **kw))
    server.start_comfy()
    assert "--use-pytorch-cross-attention" in seen["cmd"] and seen["env"]["PYTORCH_ENABLE_MPS_FALLBACK"] == "1"


def test_comfyui_elsewhere_starts_as_before(not_mac, monkeypatch):
    seen = {}
    monkeypatch.setattr(server, "port_listening", lambda port: False)
    monkeypatch.setattr(server.os.path, "exists", lambda p: True)
    monkeypatch.setattr(server, "_spawn", lambda cmd, log, **kw: seen.update(cmd=cmd, **kw))
    server.start_comfy()
    assert seen["cmd"][1:] == ["main.py", "--listen", "127.0.0.1", "--port", str(config.COMFY_PORT)] and seen["env"] is None


def _assess(monkeypatch):
    import syscheck
    monkeypatch.setattr(syscheck, "current", lambda: {"assess": {"image_gb": 8.0, "mode": "unified"}})


def test_context_leaves_room_for_the_image_model_on_a_mac(mac, monkeypatch):
    ram(monkeypatch, 16)
    _assess(monkeypatch)
    m = catalog.BY_ID["qwen354"]
    monkeypatch.setitem(harness.SETTINGS, "ckpt", None)
    assert server.auto_ctx(m) == 65536
    monkeypatch.setitem(harness.SETTINGS, "ckpt", "klein4b")
    assert server.auto_ctx(m) == 16384


def test_context_elsewhere_ignores_the_image_model(not_mac, monkeypatch):
    ram(monkeypatch, 16)
    monkeypatch.setitem(harness.SETTINGS, "ckpt", "klein4b")
    assert server.auto_ctx(catalog.BY_ID["qwen354"]) == 65536


def _fake_switch(monkeypatch, ctx):
    calls = []
    for name in ("free_comfy_memory", "stop_llm", "_wait_llm"):
        monkeypatch.setattr(server, name, lambda *a, n=name, **k: calls.append(n))
    monkeypatch.setattr(server, "restart_comfy_for", lambda node: calls.append("comfy:" + node))
    monkeypatch.setattr(server, "launch_llm", lambda m: calls.append("launch") or server.llm_state.update(ctx=server.llm_ctx(m)))
    monkeypatch.setattr(harness, "_comfy_run", lambda g: calls.append("warmup:" + g["1"]["class_type"]))
    monkeypatch.setitem(server.llm_state, "name", "qwen354")
    monkeypatch.setitem(server.llm_state, "ctx", ctx)
    monkeypatch.setitem(harness.SETTINGS, "ckpt", None)
    monkeypatch.setitem(harness.SETTINGS, "llm_ctx", 0)
    return calls


def test_choosing_klein_on_a_16gb_mac_restarts_the_assistant_once(mac, monkeypatch):
    ram(monkeypatch, 16)
    monkeypatch.setattr(harness, "IMAGE_MP", 0.5625)  # what a 16 GB Mac gets at import
    _assess(monkeypatch)
    m = catalog.klein_mac()
    calls = _fake_switch(monkeypatch, 65536)
    server._switch_image(m)
    assert calls == ["free_comfy_memory", "comfy:UnetLoaderGGUF", "stop_llm", "launch", "_wait_llm", "warmup:UnetLoaderGGUF",
                     "free_comfy_memory"]
    assert server.llm_state["ctx"] == 16384 and harness.SETTINGS["ckpt"] == "klein4b"
    calls.clear()
    server._switch_image(m)  # already small enough: no second restart
    assert "launch" not in calls


def test_choosing_klein_elsewhere_never_restarts_the_assistant(not_mac, monkeypatch):
    ram(monkeypatch, 16)
    calls = _fake_switch(monkeypatch, 65536)
    server._switch_image(catalog.klein())
    assert "launch" not in calls and "comfy:UnetLoaderGGUF" not in calls and calls[-1] == "warmup:UNETLoader"


def test_settings_api_lists_hand_placed_checkpoints_on_a_mac(mac, monkeypatch):
    monkeypatch.setattr(server, "checkpoints", lambda: ["my_sdxl.safetensors"])
    sent = {}
    h = types.SimpleNamespace(send=lambda code, body: sent.update(code=code, body=body))
    server.Handler.settings(h, "/api/settings")
    assert sent["body"]["otherCheckpoints"] == ["my_sdxl.safetensors"] and "hiddenHere" not in sent["body"]


# ---------------------------------------------------------------- Studio
def test_studio_can_use_a_video_model_on_a_mac(mac, monkeypatch):
    monkeypatch.setattr(catalog, "installed", lambda m: m["id"] == "ltx25")
    monkeypatch.setitem(harness.SETTINGS, "video", "ltx25")
    assert studio.video_model()["id"] == "ltx25"


# ---------------------------------------------------------------- the assistant pauses during each image (small Mac)
def _pause_env(monkeypatch, llm="qwen354"):
    calls = []
    monkeypatch.setattr(server, "stop_llm", lambda: calls.append("stop"))
    monkeypatch.setattr(server, "launch_llm", lambda m: calls.append("launch:" + m["id"]))
    monkeypatch.setattr(server, "_wait_llm", lambda: calls.append("wait"))
    monkeypatch.setattr(server, "free_comfy_memory", lambda timeout=10: calls.append("free"))
    monkeypatch.setitem(server.llm_state, "name", llm)
    monkeypatch.setitem(server.llm_state, "paused", None)
    monkeypatch.setattr(harness, "IMAGE_MP", 0.5625)
    return calls


EDIT = {"1": {"class_type": "UnetLoaderGGUF"}, "60": {"class_type": "LoadImage", "inputs": {"image": "x.png"}}}
GENERATE = {"1": {"class_type": "UnetLoaderGGUF"}, "9": {"class_type": "EmptyFlux2LatentImage"}}


@pytest.mark.parametrize("graph", [GENERATE, EDIT])
def test_each_image_on_a_small_mac_pauses_the_assistant(mac, monkeypatch, graph):
    calls = _pause_env(monkeypatch)
    with server.room_for_image(graph):
        assert server.llm_state["paused"] == "qwen354" and server.llm_state["name"] is None and calls == ["stop"]
    # the image model is unloaded before the assistant comes back
    assert calls == ["stop", "free", "launch:qwen354", "wait"] and server.llm_state["name"] == "qwen354"
    assert not server.llm_state["paused"]


def test_the_assistant_comes_back_when_the_image_fails(mac, monkeypatch):
    calls = _pause_env(monkeypatch)
    with pytest.raises(RuntimeError):
        with server.room_for_image(EDIT):
            raise RuntimeError("ComfyUI failed")
    assert calls == ["stop", "free", "launch:qwen354", "wait"] and server.llm_state["name"] == "qwen354"


@pytest.mark.parametrize("case", ["cloud", "big_mac", "not_mac", "already_paused"])
def test_no_pause_when_it_fits(monkeypatch, case):
    monkeypatch.setattr(config, "IS_MAC", case != "not_mac")
    calls = _pause_env(monkeypatch)
    if case == "cloud":
        monkeypatch.setitem(server.LLMS, "cloud-x", {"id": "cloud-x", "cloud": True, "kind": "llm"})
        monkeypatch.setitem(server.llm_state, "name", "cloud-x")
    if case == "big_mac":
        monkeypatch.setattr(harness, "IMAGE_MP", 1.0)
    if case == "already_paused":  # a Studio video paused it: its owner brings it back
        monkeypatch.setitem(server.llm_state, "paused", "qwen354")
        monkeypatch.setitem(server.llm_state, "name", None)
    with server.room_for_image(EDIT):
        pass
    assert calls == []


def test_the_pause_is_left_out_of_the_measured_speed(monkeypatch):
    import contextlib, time
    @contextlib.contextmanager
    def slow_pause(graph):
        yield
        time.sleep(0.3)  # the assistant restarting
    monkeypatch.setitem(harness.HOOKS, "around_image", slow_pause)
    monkeypatch.setitem(harness.SETTINGS, "ckpt", "klein4b")
    monkeypatch.setattr(harness, "_comfy_run", lambda g: "out.png")
    seen = {}
    monkeypatch.setattr(harness, "record_speed", lambda key, secs: seen.update(key=key, secs=secs))
    assert harness.comfy_run(EDIT) == "out.png" and seen["key"] == "img:klein4b" and seen["secs"] < 0.2
