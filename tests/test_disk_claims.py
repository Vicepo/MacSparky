"""An artifact is only in Sparky's panel: the assistant must not tell the user a file is on their computer unless
Computer mode really wrote it. Regression: "Here's your script ready in the ClaudeHouse folder" with nothing written."""
import json

import pytest

import harness

CLAIMS = ["Here's your script ready in the ClaudeHouse folder. You can run it with: `python3 big-file-checker.py`.",
          "The script is now in your current folder. To run it, open Terminal",
          "I saved it to your Desktop.", "Saved to /Users/victor/ClaudeHouse/big.py", "I've written big.py to ~/ClaudeHouse.",
          "J'ai créé le fichier dans ton dossier Documents.", "Le script est maintenant dans le dossier ClaudeHouse.",
          "Fichier enregistré dans /Users/victor/x.py"]
NORMAL = ["Save it in your folder and run python3 x.py.", "To run it, open Terminal and navigate to that folder, then execute it.",
          "Copy it into a file named big.py, then run it.", "The script scans your folder and all subfolders.",
          "Here is the script in the panel on the right.", "I created an artifact with the code: download it from the panel.",
          "Enregistre-le dans ton dossier puis lance-le.", "Le script parcourt le dossier et ses sous-dossiers.",
          "Change TARGET_PATH to the folder you want to scan.", "It lists files created in the last week."]


@pytest.mark.parametrize("text", CLAIMS)
def test_claims_of_a_file_on_disk_are_recognised(text):
    assert harness.DISK_CLAIM.search(text)


@pytest.mark.parametrize("text", NORMAL)
def test_ordinary_replies_are_not_flagged(text):
    assert not harness.DISK_CLAIM.search(text)


@pytest.fixture
def agent(monkeypatch):
    """run(script, level) -> (session, events), with a scripted model (see test_agent.py)."""
    monkeypatch.setitem(harness.SETTINGS, "max_steps", 6)
    monkeypatch.setitem(harness.SETTINGS, "autotest", False)
    monkeypatch.setitem(harness.SETTINGS, "llm", None)

    def run(script, level, text="Write a Python script that lists big files and put it in my ClaudeHouse folder"):
        script, notes = list(script), []

        def fake(body, think="off"):
            notes.append(body["messages"][-1]["content"])
            out = script.pop(0) if script else {"action": "reply", "args": {"text": "end of script"}}
            yield json.dumps(out, ensure_ascii=False), ""
        monkeypatch.setattr(harness, "chat_deltas", fake)
        monkeypatch.setattr(harness, "chat_once", lambda body: body["messages"][0]["content"].split("\n\n", 1)[-1])
        s = harness.Session(ephemeral=True)
        s.config["computer"] = level
        events = []
        s.turn(text, [], None, None, events.append)
        return s, events, notes
    return run


CODE = "import os\nfor d, _, files in os.walk('.'):\n    for f in files:\n        print(f)\n" * 2
ARTIFACT = {"action": "artifact", "args": {"id": "big-files", "title": "Big files", "kind": "code", "language": "python", "content": CODE}}
CLAIM = {"action": "reply", "args": {"text": "Here's your script ready in the ClaudeHouse folder."}}


def replies(events):
    return [e["text"] for e in events if e["type"] == "reply"]


def text_of(note):
    return note if isinstance(note, str) else json.dumps(note, ensure_ascii=False)


def test_the_original_bug_is_caught_and_the_file_is_really_written(agent, tmp_path):
    """Computer mode on: artifact, then a false claim -> Sparky refuses the claim, the model writes the file, then replies."""
    target = tmp_path / "big_files.py"
    write = {"action": "computer", "args": {"tool": "write", "path": str(target), "content": CODE}}
    done = {"action": "reply", "args": {"text": f"Saved to {target}."}}
    s, ev, notes = agent([ARTIFACT, CLAIM, write, done], "full")
    assert "PAS sur l'ordinateur" in text_of(notes[1]) and "computer write" in text_of(notes[1])  # hint right after the artifact
    assert "[HONESTY]" in text_of(notes[2]) and "computer write now" in text_of(notes[2])
    assert target.read_text() == CODE
    assert replies(ev) == [f"Saved to {target}."]  # the false claim never reached the user


def test_without_computer_mode_the_reply_must_be_honest(agent):
    honest = {"action": "reply", "args": {"text": "The script is in the panel on the right: download it, or turn on Computer mode."}}
    s, ev, notes = agent([ARTIFACT, CLAIM, honest], "off")
    assert "désactivé" in text_of(notes[1]) and "activer le mode Ordinateur" in text_of(notes[1])
    assert "[HONESTY]" in text_of(notes[2]) and "cannot write" in text_of(notes[2])
    assert replies(ev) == [honest["args"]["text"]]


def test_read_only_mode_says_so(agent):
    s, ev, notes = agent([ARTIFACT, {"action": "reply", "args": {"text": "Done, see the panel."}}], "read")
    assert "lecture seule" in text_of(notes[1])


def test_a_true_claim_after_a_real_write_is_accepted(agent, tmp_path):
    target = tmp_path / "ok.py"
    s, ev, notes = agent([{"action": "computer", "args": {"tool": "write", "path": str(target), "content": "print(1)\n"}},
                          {"action": "reply", "args": {"text": f"I saved it to {target}."}}], "full")
    assert target.exists() and replies(ev) == [f"I saved it to {target}."]
    assert not any("[HONESTY]" in text_of(n) for n in notes)


def test_the_guard_gives_up_after_two_nudges(agent):
    """A stubborn model: the turn still ends (the reply goes out) instead of looping."""
    s, ev, notes = agent([ARTIFACT, CLAIM, CLAIM, CLAIM], "off")
    assert replies(ev) == [CLAIM["args"]["text"]] and sum("[HONESTY]" in text_of(n) for n in notes) == 2


# F: an artifact with a path on the computer = the model wants the file on the disk (seen live: crash, nothing saved)
def disk_artifact(path):
    return {"action": "artifact", "args": {"id": "large-files-scanner", "title": "Large Files Scanner", "kind": "code",
                                           "language": "python", "content": CODE, "path": str(path)}}


def test_an_artifact_with_a_disk_path_is_written_through_computer_mode(agent, tmp_path):
    target = tmp_path / "large_files.py"
    s, ev, notes = agent([disk_artifact(target), {"action": "reply", "args": {"text": f"Saved to {target}."}}], "full")
    assert target.read_text() == CODE and not s.projects  # on the disk, not a fake "project" named after the path
    kinds = [e["type"] for e in ev]
    assert "artifact" in kinds and kinds.index("artifact") < kinds.index("ctool")  # shown in the panel, then written
    assert next(e for e in ev if e["type"] == "ctool")["tool"] == "write"
    assert replies(ev) == [f"Saved to {target}."]


def test_a_disk_path_artifact_still_needs_the_users_approval(agent, tmp_path, monkeypatch):
    """Level "ask": the same approval card as a direct write; nobody allows it -> nothing written."""
    target = tmp_path / "large_files.py"

    class NoAnswer(harness.threading.Event):
        def wait(self, timeout=None):  # the card is closed without "Allow": the decision stays "deny"
            return False
    monkeypatch.setattr(harness.threading, "Event", NoAnswer)
    honest = {"action": "reply", "args": {"text": "The file was not saved: you declined the write."}}
    s, ev, notes = agent([disk_artifact(target), honest], "ask")
    assert not target.exists()
    assert [e["type"] for e in ev if e["type"] in ("approve", "approved")] == ["approve", "approved"]


def test_a_disk_path_artifact_cannot_reach_a_protected_place(agent, tmp_path):
    """Same protection as a direct write (computer.check_writable)."""
    import os
    home_hidden = os.path.join(os.path.expanduser("~"), ".sparky-test-should-never-exist")
    target = home_hidden if os.name != "nt" else os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "x.py")
    s, ev, notes = agent([disk_artifact(target), {"action": "reply", "args": {"text": "I could not save it there."}}], "full")
    assert not os.path.exists(target)
    assert any(e["type"] == "cresult" and not e["ok"] for e in ev)


def test_without_computer_mode_a_disk_path_artifact_stays_in_the_panel(agent, tmp_path):
    target = tmp_path / "large_files.py"
    honest = {"action": "reply", "args": {"text": "It is in the panel; turn on Computer mode to save it."}}
    s, ev, notes = agent([disk_artifact(target), honest], "off")
    assert not target.exists() and "ctool" not in [e["type"] for e in ev]
    assert "chemin de l'ordinateur" in text_of(notes[1]) and "désactivé" in text_of(notes[1])
    assert replies(ev) == [honest["args"]["text"]]


def test_relative_project_paths_are_unchanged(agent):
    files = {"action": "artifact", "args": {"project": "site", "title": "Site", "path": "index.html", "language": "html",
                                            "content": "<!doctype html><html><body><h1>Bonjour</h1><p>une page complète</p></body></html>"}}
    s, ev, notes = agent([files, {"action": "reply", "args": {"text": "The site is in the panel."}}], "full")
    assert "site" in s.projects and "ctool" not in [e["type"] for e in ev]


def test_computer_prompt_says_write_only_never_an_artifact():
    import computer
    text = computer.prompt("ask", True)
    assert "use ONLY" in text and "Never an artifact for that" in text and "you may also show it as an artifact" not in text


# B: with no image model, the assistant was told "Current image model: Qwen3.8 27B" (an assistant, not an image model)
def test_no_image_model_is_said_plainly(monkeypatch):
    import catalog
    monkeypatch.setitem(harness.SETTINGS, "ckpt", None)
    assert harness.image_model()["label"] == "aucun"
    assert all(harness.image_model()["label"] != m["label"] for m in catalog.CATALOG if m["kind"] != "image")
    text = harness.system_prompt()
    assert "Current image model: none installed. You cannot generate or edit images now" in text


def test_an_installed_image_model_is_named(monkeypatch):
    import catalog
    img = next(m for m in catalog.CATALOG if m["kind"] == "image" and m.get("ckpt"))
    monkeypatch.setitem(harness.SETTINGS, "ckpt", img["ckpt"])
    assert harness.image_model()["label"] == img["label"]
    assert f"Current image model: {img['label']} (" in harness.system_prompt()
