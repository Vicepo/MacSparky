"""llama-server answers only Sparky: shared API key, CORS limited to Sparky, unprotected sessions are restarted.
Without this, any web page open in the browser could use the local model on 127.0.0.1:8080 and read its answers."""
import json, os, stat, threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

import config
import harness


@pytest.fixture
def fresh_key(data_dir, monkeypatch):
    monkeypatch.setattr(harness, "LLM_KEY_FILE", os.path.join(data_dir, "llm.key"))
    monkeypatch.setitem(harness._llm_key, "v", None)
    if os.path.exists(harness.LLM_KEY_FILE):
        os.remove(harness.LLM_KEY_FILE)
    yield harness.LLM_KEY_FILE
    monkeypatch.setitem(harness._llm_key, "v", None)


def test_key_is_random_owner_only_and_kept_across_restarts(fresh_key, monkeypatch):
    key = harness.llm_key()
    assert len(key) >= 32 and open(fresh_key).read() == key
    if os.name != "nt":
        assert stat.S_IMODE(os.stat(fresh_key).st_mode) == 0o600
    monkeypatch.setitem(harness._llm_key, "v", None)  # a new Sparky process reads the same key
    assert harness.llm_key() == key
    assert harness.llm_headers()["Authorization"] == "Bearer " + key


def test_a_damaged_key_file_is_replaced(fresh_key):
    with open(fresh_key, "w") as f:
        f.write("short")
    assert len(harness.llm_key()) >= 32 and harness.llm_key() != "short"


def test_llama_server_gets_the_key_and_cors_through_the_environment(fresh_key, monkeypatch):
    import catalog, server
    spawned = []
    monkeypatch.setattr(server, "_spawn", lambda cmd, log, **kw: spawned.append((cmd, kw)))
    monkeypatch.setattr(config, "LLAMA_SERVER", server.sys.executable)  # any existing file
    monkeypatch.setattr(server.syscheck, "current", lambda: {"assess": {"mode": "unified"}})
    m = next(m for m in catalog.CATALOG if m["kind"] == "llm" and not m.get("cloud"))
    server.launch_llm(m)
    (cmd, kw), = spawned
    assert kw["env"]["LLAMA_API_KEY"] == harness.llm_key() and harness.llm_key() not in " ".join(cmd)
    assert kw["env"]["LLAMA_ARG_CORS_ORIGINS"] == f"http://127.0.0.1:{config.APP_PORT}"
    assert kw["env"].get("PATH") == os.environ.get("PATH")  # the rest of the environment is kept


def fake_llama(key):
    """/props like llama-server: 401 without the right key, unless it was started without a key (key=None)."""
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            ok = key is None or self.headers.get("Authorization") == f"Bearer {key}"
            self.send_response(200 if ok else 401)
            body = json.dumps({}).encode()
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


@pytest.mark.parametrize("started_with,protected", [("ours", True), (None, False), ("another-key", False)])
def test_running_llama_server_is_checked_before_reuse(fresh_key, monkeypatch, started_with, protected):
    import server
    srv = fake_llama(harness.llm_key() if started_with == "ours" else started_with)
    try:
        monkeypatch.setattr(harness, "LLM", f"http://127.0.0.1:{srv.server_address[1]}")
        assert server.llm_protected() is protected
    finally:
        srv.shutdown()


def test_unprotected_session_from_an_older_sparky_is_restarted(monkeypatch):
    import server
    calls = []
    monkeypatch.setattr(server, "alive", lambda url: not calls)  # up until stop_llm runs
    monkeypatch.setattr(server, "llm_protected", lambda: False)
    monkeypatch.setattr(server, "stop_llm", lambda: calls.append("stop"))
    monkeypatch.setattr(server, "installed_llms", lambda: ["m1"])
    monkeypatch.setattr(server, "use_model", lambda mid: calls.append(("use", mid)))
    monkeypatch.setitem(harness.SETTINGS, "llm", "m1")
    monkeypatch.setitem(server.llm_state, "name", None)
    server.first_assistant()
    assert calls == ["stop", ("use", "m1")]


def test_protected_session_is_reused(monkeypatch):
    import server
    monkeypatch.setattr(server, "alive", lambda url: True)
    monkeypatch.setattr(server, "llm_protected", lambda: True)
    monkeypatch.setattr(server, "use_model", lambda mid: pytest.fail("must not reload"))
    monkeypatch.setitem(harness.SETTINGS, "llm", "m1")
    monkeypatch.setitem(server.llm_state, "name", None)  # restored after the test
    server.first_assistant()
    assert server.llm_state["name"] == "m1"


def test_harness_sends_the_key(fresh_key, monkeypatch):
    """chat_once and the streaming path go through the same headers (the fake refuses requests without the key)."""
    from test_openai_api import FakeLlama, _serve
    srv = _serve(FakeLlama)
    try:
        monkeypatch.setattr(harness, "LLM", f"http://127.0.0.1:{srv.server_address[1]}")
        monkeypatch.setattr(harness, "cloud_model", lambda: None)
        monkeypatch.setitem(harness.SETTINGS, "llm", "x")
        body = {"messages": [{"role": "user", "content": "hi"}]}
        assert harness.chat_once(body) == "Bonjour"
        assert "".join(t for t, _ in harness.chat_deltas(body)) == "Bonjour"
        monkeypatch.setattr(harness, "llm_headers", lambda: {"Content-Type": "application/json", "Authorization": "Bearer wrong"})
        with pytest.raises(RuntimeError, match="401"):
            harness.chat_once(body)
    finally:
        srv.shutdown()
