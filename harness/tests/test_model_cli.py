"""ModelClient's agent-CLI provider, with a fake `claude` on PATH."""
import json
import os
import stat
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from scaffold import model as M
from scaffold.model import (
    ModelClient,
    ModelUnavailable,
    build_prompt,
    cli_argv,
    find_cli,
    first_json_object,
)


def _fake_cli(tmp_path, name, body):
    p = tmp_path / name
    p.write_text(f"#!{sys.executable}\nimport sys, json, os, time\n" + body)
    p.chmod(p.stat().st_mode | stat.S_IXUSR)
    return p


@pytest.fixture
def cli_env(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", str(tmp_path))
    monkeypatch.delenv("MODEL_CLI", raising=False)
    monkeypatch.delenv("MODEL_PROVIDER", raising=False)
    monkeypatch.setattr(M, "_interview_state", dict)
    return tmp_path


def test_argv_table():
    assert cli_argv("claude", "hi there") == ["claude", "-p", "hi there", "--output-format", "text"]
    assert cli_argv("codex", "hi") == ["codex", "exec", "hi"]
    assert cli_argv("cursor-agent", "hi") == ["cursor-agent", "-p", "hi"]
    assert cli_argv("gemini", "hi") == ["gemini", "-p", "hi"]


def test_prompt_and_json_extraction():
    msgs = [{"role": "system", "content": "You are terse."}, {"role": "user", "content": "Refund?"}]
    assert build_prompt(msgs) == "You are terse.\n\nRefund?"
    assert build_prompt(msgs, {"type": "object"}) == 'You are terse.\n\nRefund?\n\nReply with only JSON matching this schema: {"type":"object"}'
    assert first_json_object('Sure! ```json\n{"a": 1, "b": {"c": [1, 2]}}\n``` and {"d": 2}') == {"a": 1, "b": {"c": [1, 2]}}
    assert first_json_object("no json { here") is None


def test_cli_exact_argv_and_json(cli_env):
    _fake_cli(cli_env, "claude", 'open(os.environ.get("ARGV_OUT", os.devnull), "w").write(json.dumps({"argv": sys.argv[1:]}))\nprint(\'ok: {"action": "human"} trailing\')\n')
    os.environ["ARGV_OUT"] = str(cli_env / "argv.json")
    try:
        c = ModelClient(provider="cli")
        r = c.complete(model="lot-fast", messages=[{"role": "system", "content": "S"}, {"role": "user", "content": "U"}], response_schema={"type": "object"})
    finally:
        del os.environ["ARGV_OUT"]
    assert json.loads((cli_env / "argv.json").read_text())["argv"] == ["-p", 'S\n\nU\n\nReply with only JSON matching this schema: {"type":"object"}', "--output-format", "text"]
    assert r.content == {"action": "human"} and r.model == "claude:lot-fast" and c.last_provider == "cli:claude"
    text = ModelClient(provider="cli").complete(model="lot-fast", messages=[{"role": "user", "content": "U"}])
    assert text.content == 'ok: {"action": "human"} trailing'


def test_cli_timeout_failure_and_none(cli_env):
    _fake_cli(cli_env, "claude", "time.sleep(5)\n")
    with pytest.raises(ModelUnavailable, match="timed out"):
        ModelClient(provider="cli", cli_timeout=0.5).complete(model="lot-fast", messages=[{"role": "user", "content": "U"}])
    _fake_cli(cli_env, "claude", 'sys.stderr.write("not logged in"); sys.exit(2)\n')
    with pytest.raises(ModelUnavailable, match="exited 2"):
        ModelClient(provider="cli").complete(model="lot-fast", messages=[{"role": "user", "content": "U"}])
    _fake_cli(cli_env, "claude", 'print("prose only")\n')
    with pytest.raises(ModelUnavailable, match="no JSON"):
        ModelClient(provider="cli").complete(model="lot-fast", messages=[{"role": "user", "content": "U"}], response_schema={})
    os.environ["MODEL_CLI"] = "none"
    assert find_cli() is None
    with pytest.raises(ModelUnavailable, match="no model access"):
        ModelClient(provider="cli").complete(model="lot-fast", messages=[{"role": "user", "content": "U"}])


def test_gateway_unreachable_falls_back_to_cli(cli_env):
    _fake_cli(cli_env, "gemini", 'print("from gemini")\n')
    c = ModelClient(base_url="http://127.0.0.1:1", timeout=1)
    assert c.complete(model="lot-deep", messages=[{"role": "user", "content": "U"}]).content == "from gemini"
    assert find_cli() == "gemini" and M.describe_access({}) == "gemini CLI"
    with pytest.raises(ModelUnavailable, match="unreachable"):
        ModelClient(base_url="http://127.0.0.1:1", timeout=1, provider="gateway").complete(model="lot-deep", messages=[{"role": "user", "content": "U"}])


def test_describe_access_none(cli_env):
    assert M.describe_access({}) == "none — rules only"
    assert M.describe_access({"gateway_url": "http://g", "models": "ON"}) == "gateway"
