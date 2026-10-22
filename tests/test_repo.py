"""Repository hygiene: things that broke installs before."""
import os, re, shutil, subprocess

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read(p, mode="r"):
    with open(os.path.join(ROOT, p), mode, **({} if "b" in mode else {"encoding": "utf-8"})) as f:
        return f.read()


@pytest.mark.parametrize("script", ["install.ps1", "start.ps1", "stop.ps1"])
def test_powershell_scripts_are_ascii_without_bom(script):
    """A BOM or a non-ASCII byte breaks the one-line install `irm ... | iex`."""
    data = read(script, "rb")
    assert not data.startswith(b"\xef\xbb\xbf")
    assert all(b < 128 for b in data), f"non-ASCII byte in {script}: write accents as \\uXXXX"


def test_version_is_semver():
    assert re.fullmatch(r"\d+\.\d+\.\d+\n?", read("VERSION"))


def test_requirements_cover_the_imports():
    req = read("requirements.txt").lower()
    for pkg in ("psutil", "pillow", "pypdf", "anthropic"):
        assert pkg in req


def test_installer_never_downloads_models_by_default():
    ps = read("install.ps1")
    assert "if ($Models -and -not $NoModels" in ps


def test_page_script_parses():
    node = shutil.which("node")
    if not node:
        pytest.skip("node missing")
    html = read("app/index.html")
    scripts = re.findall(r"<script>([\s\S]*?)</script>", html)
    assert scripts
    for js in scripts:
        r = subprocess.run([node, "-e", "new Function(require('fs').readFileSync(0, 'utf8'))"], input=js,
                           capture_output=True, text=True, encoding="utf-8")
        assert r.returncode == 0, r.stderr


def test_every_api_route_used_by_the_page_exists():
    html, server = read("app/index.html"), read("app/server.py")
    used = set(re.findall(r"""fetch\(\s*['"](/api/[a-z/]+)""", html))
    missing = [u for u in used if f'"{u}"' not in server and f'"{u.rstrip("/")}' not in server]
    assert not missing, missing


def test_generated_projects_load_from_the_preview_origin_only():
    """Generated code must never run on the API's origin (it could drive Sparky)."""
    html = read("app/index.html")
    uses = re.findall(r".{0,12}/api/proj/", html)
    assert uses and all("PREVIEW" in u for u in uses), uses
    assert '"/api/proj/"' not in read("app/server.py").split("class PreviewHandler")[0]


SHELL_SCRIPTS = ["install.sh", "start.sh", "stop.sh", "uninstall.sh", "Sparky.command"]


@pytest.mark.parametrize("script", SHELL_SCRIPTS)
def test_shell_scripts_parse_and_are_executable(script):
    """macOS scripts: LF endings, executable (double-click, ./start.sh), valid for the bash 3.2 of macOS."""
    data = read(script, "rb")
    assert data.startswith(b"#!/bin/bash\n") and b"\r\n" not in data
    if os.name != "nt":
        assert os.access(os.path.join(ROOT, script), os.X_OK)
    bash = shutil.which("bash")
    if not bash or os.name == "nt":
        pytest.skip("bash missing")
    r = subprocess.run([bash, "-n", os.path.join(ROOT, script)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def test_mac_installer_is_safe_to_pipe_and_never_downloads_models_by_default():
    sh = read("install.sh")
    assert sh.rstrip().endswith('\nmain "$@"')  # "curl | bash" cut in the middle runs nothing
    assert 'if [ -n "$MODELS" ]; then' in sh
    assert "shasum -a 256" in sh and "badsum" in sh  # llama.cpp binaries are checked before use
    assert "sudo" not in sh.replace("Nothing needs sudo", "")


def test_mac_stop_script_only_stops_sparky_processes():
    """stop.sh must not kill another program that happens to listen on 8080 / 8188."""
    sh = read("stop.sh")
    assert "app/server.py" in sh and "llama-server" in sh and "main.py" in sh and "not Sparky" in sh


def test_mac_uninstall_only_deletes_a_sparky_folder_after_asking():
    sh = read("uninstall.sh")
    assert sh.rstrip().endswith('\nmain "$@"')
    assert '[ ! -f "$ROOT/app/server.py" ]' in sh and '[ "$ROOT" = "$HOME" ]' in sh
    assert '[ "$r" = yes ]' in sh and "stop.sh" in sh


def test_mac_installer_app_bundle_never_replaces_another_app():
    """~/Applications/Sparky.app is only (re)written when install.sh made it; node is checked like llama.cpp."""
    sh = read("install.sh")
    assert "APP_ID='local.sparky.launcher'" in sh and '! grep -qs "$APP_ID" "$app/Contents/Info.plist"; then return 1' in sh
    assert "SHASUMS256.txt" in sh and "badnode" in sh
    assert 'rm -rf "$(' not in sh  # a failed command substitution must never become "rm -rf /"


def test_mac_uninstall_removes_only_its_own_app():
    sh = read("uninstall.sh")
    assert 'grep -qF "$ROOT/start.sh" "$app/Contents/MacOS/Sparky" 2>/dev/null || app=\'\'' in sh

