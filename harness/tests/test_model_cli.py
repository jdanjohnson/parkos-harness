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

NPM_SHIM = ('@ECHO off\r\nSETLOCAL\r\nSET dp0=%~dp0\r\nIF EXIST "%dp0%\\node.exe" (SET "_prog=%dp0%\\node.exe") ELSE (SET "_prog=node")\r\n'
            'endLocal & goto #_undefined_# 2>NUL || title %COMSPEC% & "%_prog%"  "%dp0%\\{target}" %*\r\n')


def _fake_cli(tmp_path, name, body):
    """A `name` CLI on PATH: a shebang script on POSIX; on Windows a `name.py` behind an npm-style `name.cmd` shim."""
    script = "import sys, json, os, time\n" + body
    if sys.platform == "win32":
        (tmp_path / f"{name}.py").write_text(script)
        p = tmp_path / f"{name}.cmd"
        p.write_text(NPM_SHIM.format(target=f"{name}.py"))
        return p
    p = tmp_path / name
    p.write_text(f"#!{sys.executable}\n" + script)
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


def test_resolve_cli_bypasses_npm_cmd_shim(tmp_path):
    target = tmp_path / "node_modules" / "@anthropic-ai" / "claude-code" / "cli.js"
    target.parent.mkdir(parents=True)
    target.write_text("")
    shim = tmp_path / "claude.cmd"
    shim.write_text(NPM_SHIM.format(target="node_modules\\@anthropic-ai\\claude-code\\cli.js"))
    node = tmp_path / "bin" / ("node.exe" if sys.platform == "win32" else "node")
    node.parent.mkdir()
    node.write_text("")
    node.chmod(0o755)
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("PATH", str(node.parent))
        assert M.resolve_cli(str(shim)) == [str(node), str(target)]
        py_target = tmp_path / "tool.py"
        py_target.write_text("")
        py_shim = tmp_path / "tool.cmd"
        py_shim.write_text(NPM_SHIM.format(target="tool.py"))
        assert M.resolve_cli(str(py_shim)) == [sys.executable, str(py_target)]
        mp.setenv("PATH", str(tmp_path / "nowhere"))
        assert M.resolve_cli(str(shim)) == [str(shim)]  # node not on PATH: fall back to the shim itself
    missing = tmp_path / "gone.cmd"
    missing.write_text(NPM_SHIM.format(target="gone.js"))
    assert M.resolve_cli(str(missing)) == [str(missing)]  # shim target does not exist
    opaque = tmp_path / "opaque.cmd"
    opaque.write_text("@ECHO off\r\nsomething-else %*\r\n")
    assert M.resolve_cli(str(opaque)) == [str(opaque)]  # not an npm shim
    assert M.resolve_cli("/usr/local/bin/claude") == ["/usr/local/bin/claude"]
    assert M.resolve_cli(r"C:\tools\claude.exe") == [r"C:\tools\claude.exe"]


def test_cli_behind_cmd_shim_runs_end_to_end(cli_env):
    (cli_env / "tool.py").write_text('import sys, json\nprint(json.dumps({"argv": sys.argv[1:]}))\n')
    shim = cli_env / "tool.cmd"
    shim.write_text(NPM_SHIM.format(target="tool.py"))
    shim.chmod(0o755)
    os.environ["MODEL_CLI"] = "tool.cmd"
    try:
        r = ModelClient(provider="cli").complete(model="lot-fast", messages=[{"role": "user", "content": 'say "hi"\nline 2'}], response_schema={})
    finally:
        del os.environ["MODEL_CLI"]
    assert r.content == {"argv": ["-p", 'say "hi"\nline 2\n\nReply with only JSON matching this schema: {}']}


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


def test_auto_without_configured_gateway_goes_straight_to_cli(cli_env, monkeypatch):
    _fake_cli(cli_env, "codex", 'print("from codex")\n')
    import urllib.request

    def no_probe(req, timeout):
        raise AssertionError("gateway probed although not configured")
    monkeypatch.setattr(urllib.request, "urlopen", no_probe)
    c = ModelClient(timeout=30)
    assert c.gateway_configured is False
    assert c.complete(model="lot-fast", messages=[{"role": "user", "content": "U"}]).content == "from codex"
    assert c.last_provider == "cli:codex"


def test_configured_outage_503_never_falls_back_to_cli(cli_env, monkeypatch):
    _fake_cli(cli_env, "claude", 'print("should not run")\n')
    import urllib.error
    import urllib.request

    def boom(req, timeout):
        raise urllib.error.HTTPError(req.full_url, 503, "outage", {}, None)
    monkeypatch.setattr(urllib.request, "urlopen", boom)
    c = ModelClient(base_url="http://gw", timeout=1)
    with pytest.raises(ModelUnavailable, match="gateway outage") as ei:
        c.complete(model="lot-fast", messages=[{"role": "user", "content": "U"}])
    assert ei.value.outage is True and c.last_provider is None
