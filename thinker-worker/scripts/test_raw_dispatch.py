from pathlib import Path
import sys
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import raw_dispatch as rd
import tw


def test_argv_builders_preserve_model_effort_and_flags(tmp_path):
    cd = tmp_path / "repo"
    cd.mkdir()
    out = tmp_path / "last.md"

    c_argv = rd.build_codex_argv("codex", "gpt-6-astra", "high", cd, out, "danger-full-access", "never", search=True)
    assert c_argv[:4] == ["codex", "--search", "--ask-for-approval", "never"]
    assert "-m" in c_argv and c_argv[c_argv.index("-m") + 1] == "gpt-6-astra"
    assert "model_reasoning_effort=high" in c_argv

    cl_argv = rd.build_claude_argv("claude", "claude-opus-5-5", "high", "bypassPermissions")
    assert cl_argv == ["claude", "-p", "--output-format", "json", "--permission-mode", "bypassPermissions",
                       "--model", "claude-opus-5-5", "--effort", "high"]

    ag_argv = rd.build_agy_argv("agy", "gemini-4-neon-high", None, None)
    assert "--model" in ag_argv and "gemini-4-neon-high" in ag_argv
    assert "--dangerously-skip-permissions" in ag_argv
    assert "--effort" not in ag_argv

    ag_mode = rd.build_agy_argv("agy", "gemini-4-carbon-high", None, "plan")
    assert "--mode" in ag_mode and "--dangerously-skip-permissions" not in ag_mode

    omp_argv = rd.build_omp_argv("omp", cd, "qwen", "high", None, tmp_path / "sess")
    assert "--model" in omp_argv and "--thinking" in omp_argv and "--session-dir" in omp_argv


def test_claude_evidence_positive_and_negative():
    good = '{"type":"result","subtype":"success","is_error":false,"result":"ok","session_id":"s1","total_cost_usd":0.1,"usage":{"output_tokens":12},"modelUsage":{"claude-opus-5-5":{"outputTokens":12},"claude-haiku-5-5":{"outputTokens":1}}}'
    ev = rd._claude_evidence(good)
    assert ev["model"] == "claude-opus-5-5"
    assert ev["session_id"] == "s1"
    assert ev["is_error"] is False
    assert ev["text"] == "ok"

    bad = rd._claude_evidence("not json at all")
    assert bad["model"] is None
    assert bad["is_error"] is True


def test_raw_run_rejects_bad_cd_and_home_for_codex(tmp_path):
    with pytest.raises(tw.Conflict, match="does not exist"):
        rd.raw_run("claude", "hi", tmp_path / "missing")
    with pytest.raises(tw.Conflict, match="home directory"):
        rd.raw_run("codex", "hi", Path.home())
    with pytest.raises(tw.Conflict, match="unsupported backend"):
        rd.raw_run("bogus", "hi", tmp_path)
