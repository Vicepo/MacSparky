"""Thinking that goes round in circles ("Wait, ... Wait, ...") is stopped early and the answer asked directly,
instead of waiting minutes for the whole thinking budget (regression seen with Qwen3.5 4B in Computer mode)."""
import json

import pytest

import catalog
import harness

THINKER = next(m["id"] for m in catalog.CATALOG if m.get("think") and not m.get("cloud"))
SPIRAL = ["Wait, if I use action computer, does it override the top schema? Yes.\n",
          "* Wait, I need to create the file first. Then execute it.\n", "* I will create the file in the first turn.\n",
          "* Wait, the user said \"Then execute it\".\n", "* Wait, I need to check the thought language.\n",
          "* Actually, I could run ls first to check the folder.\n", "* Hmm, but the user gave the path.\n",
          "* Wait, I need to make sure I don't violate the one tool rule.\n"] * 6
HEALTHY = ["The user wants a script saved in a folder. ", "I will write it with the write tool first, ",
           "then run it in the next step once the result comes back. " * 20, "Wait, the path is absolute, fine."]


@pytest.fixture
def model(monkeypatch):
    """Scripted model: each call gets the next (reasoning pieces, answer) pair; records the thinking asked."""
    monkeypatch.setitem(harness.SETTINGS, "llm", THINKER)
    monkeypatch.setitem(harness.SETTINGS, "think", "medium")
    monkeypatch.setitem(harness.SETTINGS, "max_steps", 4)
    calls = []

    def run(script):
        script = list(script)

        def fake(body, think="off"):
            calls.append(body["chat_template_kwargs"].get("enable_thinking"))
            reasoning, answer = script.pop(0)
            for r in reasoning:
                yield "", r
            if answer is not None:
                yield json.dumps(answer), ""
        monkeypatch.setattr(harness, "chat_deltas", fake)
        s, events = harness.Session(ephemeral=True), []
        s._emit = s._ev = events.append
        s._read = False
        return s.ask_llm(), events
    run.calls = calls
    return run


REPLY = {"thought": "ok", "action": "reply", "args": {"text": "Done."}}


def test_a_thinking_spiral_is_cut_and_answered_directly(model):
    act, events = model([(SPIRAL, None), ([], REPLY)])  # the spiral never reaches an answer by itself
    assert act["action"] == "reply" and model.calls == [True, False]  # second request: no thinking
    assert any(e.get("type") == "status" and "tournait en rond" in e.get("text", "") for e in events)
    thought = next(e for e in events if e.get("type") == "reasoned")["text"]
    assert len(thought) < len("".join(SPIRAL))  # stopped early, not at the end of the budget


def test_healthy_thinking_is_not_cut(model):
    act, events = model([(HEALTHY, REPLY)])
    assert act["action"] == "reply" and model.calls == [True]
    assert not any(e.get("type") == "status" for e in events)


@pytest.mark.parametrize("text,n", [("Wait, no.\nActually yes. Hmm. But wait, maybe.", 4),
                                    ("* Wait, check.\n- Hold on.\nAttends, en fait non.", 3),
                                    ("I will wait for the result, actually it is fast.", 0)])  # mid-sentence: not a restart
def test_hesitation_counting(text, n):
    assert len(harness.HESITATION.findall(text)) == n


def test_computer_prompt_has_one_format_and_one_step_at_a_time():
    import computer
    text = computer.prompt("ask", True)
    assert "one more action of the same JSON object" in text and '"notes" only right after you saw an image' in text
    assert "do the FIRST step now" in text
