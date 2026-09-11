"""ModelClient must pick up gateway URL + attempt token written by `./interview start` when no env is set."""
import json
import os

from scaffold import model as m


def test_model_client_reads_interview_state(monkeypatch, tmp_path):
    root = os.path.dirname(os.path.dirname(os.path.abspath(m.__file__)))
    state = os.path.join(root, ".interview_state.json")
    monkeypatch.delenv("MODEL_BASE_URL", raising=False)
    monkeypatch.delenv("ATTEMPT_TOKEN", raising=False)
    backup = None
    if os.path.exists(state):
        with open(state) as fh:
            backup = fh.read()
    try:
        with open(state, "w") as fh:
            json.dump({"gateway_url": "https://parkos.stationed.net/gw/", "attempt_token": "at_xyz"}, fh)
        c = m.ModelClient()
        assert c.base_url == "https://parkos.stationed.net/gw"
        assert c.attempt_token == "at_xyz"
        # explicit args and env win over the state file
        monkeypatch.setenv("MODEL_BASE_URL", "http://env:1")
        assert m.ModelClient().base_url == "http://env:1"
        assert m.ModelClient(base_url="http://arg:2", attempt_token="t").base_url == "http://arg:2"
        # corrupt state falls back to defaults, does not crash
        with open(state, "w") as fh:
            fh.write("{not json")
        monkeypatch.delenv("MODEL_BASE_URL")
        c = m.ModelClient()
        assert c.base_url == "http://localhost:8081" and c.attempt_token == "local-dev"
    finally:
        if backup is None:
            os.remove(state)
        else:
            with open(state, "w") as fh:
                fh.write(backup)
