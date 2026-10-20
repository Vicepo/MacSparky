"""Computer mode: security levels, protected folders, file tools, approval flow in the agent."""
import os, sys, threading, time

import pytest

import computer
import config
import harness

MAC = sys.platform == "darwin"


def test_levels():
    na = computer.needs_approval
    assert na("off", "list") == "deny" and na("off", "run") == "deny"
    assert na("read", "read") is None and na("read", "write") == "deny" and na("read", "run") == "deny"
    assert na("ask", "search") is None and na("ask", "write") == "ask" and na("ask", "trash") == "ask"
    assert na("ask_all", "list") == "ask" and na("full", "run") is None


@pytest.mark.skipif(os.name != "nt", reason="Windows folders")
def test_protected_folders():
    for p in (os.environ.get("SystemRoot", r"C:\Windows"), os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"), "x"), "C:\\"):
        with pytest.raises(PermissionError):
            computer.check_writable(os.path.abspath(p))


H = os.path.expanduser("~")
MAC_BLOCKED = ["/Library/x", "/LIBRARY/x", "/Applications/Evil.app", "/System/x", "/usr/local/bin/x", "/opt/homebrew/bin/python3",
               "/etc/hosts", "/private/etc/hosts", "/var/x", "/bin/x", "/", "/Volumes", "/Volumes/USB",
               H + "/Library/LaunchAgents/x.plist", H + "/library/launchagents/x.plist", H + "/.zshrc", H + "/.zprofile",
               H + "/.ssh/authorized_keys", H + "/.gitconfig", H + "/.config/gh/hosts.yml", os.path.join(config.ROOT, "app", "server.py")]
MAC_WRITABLE = [H + "/Desktop/a.py", H + "/Documents/sub/x.txt", H + "/ClaudeHouse/big.py", "/Volumes/USB/photos/a.jpg", "/tmp/x.txt"]


@pytest.mark.skipif(not MAC, reason="macOS folders")
@pytest.mark.parametrize("path", MAC_BLOCKED)
def test_mac_protected_folders(path):
    """Regression: on macOS only Sparky's own folder was protected (/Library, ~/Library/LaunchAgents, ~/.zshrc... were writable)."""
    with pytest.raises(PermissionError):
        computer.check_writable(path)


@pytest.mark.skipif(not MAC, reason="macOS folders")
@pytest.mark.parametrize("path", MAC_WRITABLE)
def test_mac_user_folders_stay_writable(path):
    computer.check_writable(path)


@pytest.mark.skipif(os.name == "nt", reason="symlinks to system folders")
def test_a_link_cannot_lead_into_a_protected_folder(tmp_path):
    target = "/Library" if MAC else "/etc"
    (tmp_path / "link").symlink_to(target)
    with pytest.raises(PermissionError):
        computer.check_writable(str(tmp_path / "link" / "x"))
    computer.check_writable(str(tmp_path / "plain.txt"))  # the temporary folder itself is fine


def test_places_and_resolve():
    pl = computer.places()
    assert os.path.isabs(pl["desktop"]) and computer.resolve("desktop\\a.txt") == os.path.join(pl["desktop"], "a.txt")
    if os.name != "nt":  # regression: "desktop/sub/a.py" became a file named "sub\a.py"
        want = os.path.join(pl["desktop"], "sub", "a.py")
        assert computer.resolve("desktop/sub/a.py") == want and computer.resolve("desktop\\sub\\a.py") == want
        assert computer.resolve("Desktop") == pl["desktop"] and computer.resolve("~/x.txt") == os.path.join(H, "x.txt")
    if MAC:
        assert pl["videos"].endswith("/Movies")


def test_prompt_matches_the_os():
    text = computer.prompt("ask", True)
    assert "NOT saved on the computer" in text and "write" in text  # an artifact is not a file on the disk
    if MAC:
        assert "user's Mac" in text and "zsh" in text and "the Trash" in text and "desktop/file.txt" in text
        assert "PowerShell" not in text and "Windows" not in text and "Recycle Bin" not in text
        assert "zsh" in computer.TOOLS["run"][1] and "Trash" in computer.TOOLS["trash"][1]


def test_file_tools(tmp_path):
    d = str(tmp_path)
    out = computer.RUN["write"]({"path": os.path.join(d, "notes", "a.txt"), "content": "bonjour Sparky"})
    assert "créé" in out
    assert "a.txt" in computer.RUN["list"]({"path": os.path.join(d, "notes")})
    assert "bonjour Sparky" in computer.RUN["read"]({"path": os.path.join(d, "notes", "a.txt")})
    assert "1 fichier" in computer.RUN["search"]({"root": d, "name": "*.txt", "text": "sparky"})
    computer.RUN["copy"]({"src": os.path.join(d, "notes", "a.txt"), "dst": os.path.join(d, "b.txt")})
    computer.RUN["move"]({"src": os.path.join(d, "b.txt"), "dst": os.path.join(d, "c.txt")})
    assert os.path.exists(os.path.join(d, "c.txt")) and not os.path.exists(os.path.join(d, "b.txt"))
    with pytest.raises(FileExistsError):
        computer.RUN["copy"]({"src": os.path.join(d, "c.txt"), "dst": os.path.join(d, "notes", "a.txt")})


@pytest.mark.skipif(os.name != "nt", reason="Recycle Bin and PowerShell: Windows only")
def test_trash_and_run(tmp_path):
    p = tmp_path / "old.txt"
    p.write_text("x")
    assert "corbeille" in computer.RUN["trash"]({"path": str(p)}) and not p.exists()
    out = computer.RUN["run"]({"command": "Write-Output (6*7)", "cwd": str(tmp_path)})
    assert "code de sortie 0" in out and "42" in out


@pytest.mark.skipif(not MAC, reason="macOS Trash and zsh")
def test_mac_trash_and_run(tmp_path):
    p = tmp_path / "sparky-test-trash.txt"
    p.write_text("x")
    assert "corbeille" in computer.RUN["trash"]({"path": str(p)}) and not p.exists()  # in the Trash: recoverable
    out = computer.RUN["run"]({"command": "echo $((6*7)); pwd", "cwd": str(tmp_path)})
    assert "code de sortie 0" in out and "42" in out and tmp_path.name in out  # ran in cwd
    assert "42" in computer.RUN["run"]({"command": ["zsh", "-c", "echo $((6*7))"]})  # list form, shell name dropped


@pytest.mark.skipif(os.name == "nt", reason="zsh / sh")
def test_run_timeout_stops_the_whole_command(monkeypatch, tmp_path):
    monkeypatch.setattr(computer, "CMD_TIMEOUT", 1)
    t0 = time.time()
    out = computer.RUN["run"]({"command": "sleep 30 & sleep 30; echo never", "cwd": str(tmp_path)})
    assert time.time() - t0 < 10 and "arrêté après 1 s" in out and "never" not in out


@pytest.mark.skipif(not MAC, reason="macOS open / trash commands")
def test_mac_commands_get_paths_as_arguments(monkeypatch, tmp_path):
    """No shell: a path or app name is one argument, never pasted into a command line or a script."""
    calls = []
    monkeypatch.setattr(computer.subprocess, "run", lambda cmd, **kw: calls.append(cmd) or type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})())
    computer.t_open("https://example.com")
    computer.t_open("TextEdit")
    computer.t_open(str(tmp_path))
    assert calls == [["open", "--", "https://example.com"], ["open", "-a", "TextEdit"], ["open", "--", str(tmp_path)]]
    calls.clear()
    weird = str(tmp_path / 'a" & rm -rf ~ & ".txt')
    monkeypatch.setattr(computer.os.path, "exists", lambda p: False)  # older macOS: Finder through osascript
    with pytest.raises(OSError):  # the fake run moved nothing, so the file "still exists": reported as a failure
        monkeypatch.setattr(computer.os.path, "lexists", lambda p: True)
        computer._mac_trash(weird)
    assert calls[0][0] == "osascript" and calls[0][-1] == weird and all(weird not in c for c in calls[0][:-1])


class _T:
    computer, free, tools_used, disk_written = 0, 0, False, False

    def spare(self):
        self.free += 1


def _session(level):
    s = harness.Session(ephemeral=True)
    s.config["computer"] = level
    return s


def test_agent_denied_by_level(tmp_path):
    s, evs = _session("read"), []
    s._on_computer(_T(), {"tool": "write", "path": str(tmp_path / "x.txt"), "content": "x"}, evs.append)
    assert not (tmp_path / "x.txt").exists() and "[REFUSÉ]" in s.history[-1]["text"]
    assert [e["type"] for e in evs] == ["ctool", "cresult"]


def test_agent_approval_flow(tmp_path):
    s, evs = _session("ask"), []
    target = tmp_path / "ok.txt"

    def user():  # the user clicks "Allow" on the card
        for _ in range(100):
            ap = [e for e in evs if e["type"] == "approve"]
            if ap:
                assert s.approve(ap[0]["id"], "always")
                return
            time.sleep(0.05)
    threading.Thread(target=user).start()
    s._on_computer(_T(), {"tool": "write", "path": str(target), "content": "fait"}, evs.append)
    assert target.read_text() == "fait"
    assert [e["type"] for e in evs] == ["ctool", "approve", "approved", "cresult"] and evs[2]["decision"] == "always"
    evs.clear()  # "always": the next write runs without asking
    s._on_computer(_T(), {"tool": "write", "path": str(target), "content": "encore"}, evs.append)
    assert target.read_text() == "encore" and "approve" not in [e["type"] for e in evs]


def test_agent_user_denies(tmp_path):
    s, evs = _session("ask_all"), []

    def user():
        for _ in range(100):
            ap = [e for e in evs if e["type"] == "approve"]
            if ap:
                s.approve(ap[0]["id"], "deny")
                return
            time.sleep(0.05)
    threading.Thread(target=user).start()
    s._on_computer(_T(), {"tool": "list", "path": str(tmp_path)}, evs.append)
    assert "REFUSÉ PAR L'UTILISATEUR" in s.history[-1]["text"]


def test_batch_disks_and_info(tmp_path):
    for n in ("a.txt", "b.txt", "c.png"):
        (tmp_path / n).write_text(n)
    out = computer.RUN["move"]({"paths": [str(tmp_path / "a.txt"), str(tmp_path / "b.txt")], "dst": str(tmp_path / "Notes")})
    assert out.startswith("2/2") and sorted(os.listdir(tmp_path / "Notes")) == ["a.txt", "b.txt"]
    out = computer.RUN["copy"]({"paths": [str(tmp_path / "c.png"), str(tmp_path / "missing.png")], "dst": str(tmp_path / "Img")})
    assert out.startswith("1/2") and "✗" in out
    assert "libres" in computer.RUN["info"]({"path": str(tmp_path)}) and "fichiers" in computer.RUN["info"]({"path": str(tmp_path)})
    if os.name == "nt" or MAC:
        assert "libres sur" in computer.RUN["disks"]({})
    if MAC:
        assert computer.RUN["disks"]({}).startswith("/ ")
    assert computer.summary("move", {"paths": ["x", "y"], "dst": "z"}).startswith("2 éléments → z")
