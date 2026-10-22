"""Hardware -> recommended models (regression: what each kind of PC gets by default)."""
import pytest

import syscheck


def machine(gpu=None, vram=0, ram=32, disk=500):
    gpus = [{"name": gpu, "vram_gb": vram, "driver": "600", "vendor": "nvidia"}] if gpu else []
    hw = {"os": "Windows 11", "arch": "AMD64", "cpu": "x", "cores": 8, "ram_gb": ram, "gpus": gpus, "disk_free_gb": disk}
    info = {"hw": hw, "assess": syscheck.assess(hw)}
    info["recommended"], info["notes"] = syscheck.recommend(info)
    return info


def test_rtx_5090_gets_the_smartest_model_and_fast_images():
    i = machine("NVIDIA GeForce RTX 5090", 31.8, 64)
    assert i["assess"]["tier_label"] == "Excellente"
    assert i["recommended"] == {"llm": "qwen38", "image": "klein4b", "voice": "whisper-turbo"} and not i["notes"]


@pytest.mark.parametrize("gpu,vram", [("NVIDIA GeForce RTX 4060", 8), ("NVIDIA GeForce RTX 3060", 12)])
def test_mid_range_gpus_get_a_model_that_fits(gpu, vram):
    import catalog
    i = machine(gpu, vram)
    llm = catalog.BY_ID[i["recommended"]["llm"]]
    assert llm["size_gb"] + 2.5 <= i["assess"]["model_mem_gb"]
    assert i["recommended"]["voice"] == "whisper-turbo"


def test_image_model_is_recommended_only_when_it_fits():
    """FLUX.2 Klein's size depends on the GPU running the tests (FP4 text encoder on RTX 50, FP8 elsewhere)."""
    import catalog
    klein = catalog.BY_ID["klein4b"]["size_gb"]
    for vram in (8, 12, 16):
        i = machine("NVIDIA GeForce RTX 4070", vram)
        fits = klein <= i["assess"]["model_mem_gb"] + 2
        assert (i["recommended"].get("image") is not None) == fits, (vram, klein)


def test_no_gpu_runs_a_small_model_without_images():
    i = machine(None, ram=16)
    assert i["assess"]["mode"] == "cpu" and i["assess"]["tier"] == 1
    assert "image" not in i["recommended"] and i["recommended"]["voice"] == "whisper-base"
    assert any("processeur" in n for n in i["notes"])


def test_low_disk_space_is_reported():
    assert any("Espace disque faible" in n for n in machine("NVIDIA GeForce RTX 5090", 31.8, 64, disk=12)["notes"])


def test_unified_memory_machines_keep_memory_for_windows():
    i = machine("NVIDIA GB10 Spark", 120, 128)
    assert i["assess"]["mode"] == "unified" and i["assess"]["model_mem_gb"] == 118


def mac(chip="Apple M3", ram=16, disk=500, wired_mb=0):
    share = wired_mb / 1024 if wired_mb else ram * (2 / 3 if ram <= 36 else 3 / 4)
    hw = {"os": "macOS 26.6", "arch": "arm64", "cpu": chip, "cores": 8, "ram_gb": ram, "disk_free_gb": disk,
          "gpus": [{"name": f"{chip} GPU", "vram_gb": share, "driver": "Metal", "vendor": "apple", "wired_limit": bool(wired_mb)}]}
    info = {"hw": hw, "assess": syscheck.assess(hw)}
    info["recommended"], info["notes"] = syscheck.recommend(info)
    return info


def test_16gb_mac_runs_on_metal_and_keeps_memory_for_macos():
    i = mac()
    a = i["assess"]
    assert a["mode"] == "unified" and a["gpu"] == "Apple M3 GPU" and a["model_mem_gb"] == 10
    assert a["bandwidth"] == 84 and a["images"] and a["image_gb"] == 8.0  # Klein GGUF Q4, measured on the M3
    assert i["recommended"] == {"llm": "qwen354", "image": "klein4b", "voice": "whisper-turbo"}
    assert not any(n.startswith("Mac :") for n in i["notes"])


def test_8gb_mac_has_no_images_and_says_why():
    i = mac("Apple M1", 8)
    assert not i["assess"]["images"] and "image" not in i["recommended"]
    note = next(n for n in i["notes"] if n.startswith("Mac :"))
    assert "16 Go" in note and syscheck.note_en(note) == "Mac: image generation needs 16 GB of memory or more."


def test_64gb_mac_gets_klein_too():
    i = mac("Apple M3 Max", 64)
    assert i["assess"]["images"] and i["recommended"]["image"] == "klein4b"


@pytest.mark.parametrize("chip,bw", [("Apple M3 Max", 400), ("Apple M3 Pro", 150), ("Apple M4 Pro", 273), ("Apple M1", 68),
                                     ("Apple M9", 100)])
def test_apple_chip_bandwidth_most_specific_name_wins(chip, bw):
    assert mac(chip, 64)["assess"]["bandwidth"] == round(bw * syscheck.EFFECTIVE)


def test_big_mac_gets_a_bigger_model_and_small_mac_a_small_one():
    import catalog
    big, small = mac("Apple M4 Max", 128), mac("Apple M1", 8)
    assert big["assess"]["model_mem_gb"] == pytest.approx(89.6) and big["assess"]["tier"] == 4
    assert catalog.BY_ID[big["recommended"]["llm"]]["quality"] == 5
    assert small["assess"]["model_mem_gb"] == 2 and small["assess"]["tier"] == 1


def test_detect_on_apple_silicon(monkeypatch):
    import config
    monkeypatch.setattr(config, "IS_MAC", True)
    monkeypatch.setattr(syscheck.platform, "machine", lambda: "x86_64")  # Python under Rosetta
    monkeypatch.setattr(syscheck.platform, "mac_ver", lambda: ("26.6", ("", "", ""), "arm64"))
    answers = {"hw.optional.arm64": "1\n", "machdep.cpu.brand_string": "Apple M3\n"}
    monkeypatch.setattr(syscheck, "_run", lambda cmd, timeout=10: answers.get(cmd[-1], "") if cmd[0] == "sysctl" else "")
    hw = syscheck.detect()
    assert hw["os"] == "macOS 26.6" and hw["arch"] == "arm64" and hw["cpu"] == "Apple M3"
    assert hw["gpus"][0] | {"vram_gb": 0} == {"name": "Apple M3 GPU", "vram_gb": 0, "driver": "Metal", "vendor": "apple",
                                               "wired_limit": False}


def test_metal_share_follows_the_wired_limit(monkeypatch):
    import config
    monkeypatch.setattr(config, "IS_MAC", True)
    vals = {"iogpu.wired_limit_mb": "0"}
    monkeypatch.setattr(syscheck, "_sysctl", lambda k: vals[k])
    assert syscheck.metal_share(24) == (16, False) and syscheck.metal_share(64) == (48, False)
    vals["iogpu.wired_limit_mb"] = "20480"  # raised by the user (sudo sysctl iogpu.wired_limit_mb=20480)
    assert syscheck.metal_share(24) == (20, True)


def test_a_wired_limit_set_by_hand_changes_the_model_budget():
    assert mac(ram=16)["assess"]["model_mem_gb"] == 10                    # default: 70 %, macOS keeps 6 GB
    assert mac(ram=16, wired_mb=14336)["assess"]["model_mem_gb"] == 12     # raised to 14 GB: macOS still keeps 4 GB
    assert mac(ram=16, wired_mb=8192)["assess"]["model_mem_gb"] == 7       # lowered to 8 GB: Metal cannot use more
    assert mac(ram=64, wired_mb=57344)["assess"]["model_mem_gb"] == 55


def test_a_scan_saved_by_an_older_sparky_is_redone(monkeypatch):
    old = {"ts": 1, "hw": {}, "assess": {"images": False}, "recommended": {"llm": "x"}, "notes": ["Mac : ancienne note"]}
    monkeypatch.setattr(syscheck.config, "read_json", lambda path, default=None: old)
    monkeypatch.setattr(syscheck, "run", lambda: {"v": syscheck.SCAN_VERSION, "fresh": True})
    monkeypatch.setitem(syscheck._cache, "v", None)
    assert syscheck.current() == {"v": syscheck.SCAN_VERSION, "fresh": True}
    monkeypatch.setitem(syscheck._cache, "v", None)
    monkeypatch.setattr(syscheck.config, "read_json", lambda path, default=None: old | {"v": syscheck.SCAN_VERSION})
    assert syscheck.current()["notes"] == ["Mac : ancienne note"]  # same version: the saved scan is kept
