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
