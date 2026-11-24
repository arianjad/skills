"""tw.py runners against fake codex/claude/agy/omp executables, the OMP continuation, the `ran` reader, and the
`hook` migration shim. Run: python test_tw.py (also collected by pytest)."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

TW = str(Path(__file__).with_name("tw.py"))
FAKE = r'''
import json, os, sys, time
from pathlib import Path
tool, args = sys.argv[1], sys.argv[2:]
home = Path(os.environ['FAKE_HOME'])
stdin = sys.stdin.buffer.read().decode('utf-8')
(home/f'{tool}-call.json').write_text(json.dumps({'args': args, 'stdin': stdin, 'cwd': os.getcwd()}), encoding='utf-8')
val = lambda flag: args[args.index(flag)+1] if flag in args else None
if tool == 'codex':
    rollout = home/'.codex'/'sessions'/'2026'/'rollout-x-T1.jsonl'
    rollout.parent.mkdir(parents=True, exist_ok=True)
    rollout.write_text(json.dumps({'type':'turn_context','payload':{'model':val('-m'),'effort':'high'}})+'\n', encoding='utf-8')
    print(json.dumps({'type':'thread.started','thread_id':'T1'}))
    print(json.dumps({'type':'turn.completed','usage':{'input_tokens':7,'output_tokens':2}}))
    Path(val('-o')).write_text('codex done', encoding='utf-8')
elif tool == 'claude':
    print(json.dumps({'type':'result','subtype':'success','is_error':False,'result':'claude done','session_id':'S1',
                      'modelUsage':{val('--model'):{'outputTokens':9},'claude-haiku-x':{'outputTokens':1}},'usage':{'output_tokens':10}}))
elif tool == 'agy':
    print(json.dumps({'event':'init','conversation_id':'C1','init':{'model':val('--model')}}))
    print(json.dumps({'event':'result','result':{'status':'SUCCESS','response':'agy done','usage':{'out':3}}}))
elif tool == 'omp':
    if '--resume' in args:
        session = Path(val('--resume'))
    else:
        session = Path(val('--session-dir'))/'2026-11-24_W1.jsonl'
        session.parent.mkdir(parents=True, exist_ok=True)
        session.write_text(json.dumps({'type':'thinking_level_change','thinkingLevel':'medium'})+'\n', encoding='utf-8')
    print(json.dumps({'type':'session','id':'W1'}), flush=True)
    marker = home/'slept.marker'
    if os.environ.get('FAKE_SLEEP_ALWAYS') or (os.environ.get('FAKE_SLEEP_ONCE') and not marker.exists()):
        marker.write_text('x', encoding='utf-8')
        time.sleep(30)
    print(json.dumps({'type':'message_end','message':{'role':'assistant','provider':'p','model':'local-a',
          'stopReason':'stop','content':[{'type':'text','text':'omp done'}],'usage':{'input':4,'output':1}}}))
    print(json.dumps({'type':'agent_end','isTerminal':True,'yielded':True}))
'''


def tw(env, *args, stdin=""):
    return subprocess.run([sys.executable, TW, *args], env=env, input=stdin, capture_output=True, text=True,
                          encoding="utf-8", timeout=120)


def test_all():
    with tempfile.TemporaryDirectory(prefix="tw test ") as temp:
        home = Path(temp)
        bin_dir = home / "bin"
        bin_dir.mkdir()
        (bin_dir / "fake.py").write_text(FAKE, encoding="utf-8")
        for tool in ("codex", "claude", "agy", "omp"):
            if os.name == "nt":
                (bin_dir / f"{tool}.cmd").write_text(f'@"{sys.executable}" "%~dp0fake.py" {tool} %*\n', encoding="utf-8")
            else:
                launcher = bin_dir / tool
                launcher.write_text(f'#!/bin/sh\nexec "{sys.executable}" "$(dirname "$0")/fake.py" {tool} "$@"\n')
                launcher.chmod(0o755)
        env = {**os.environ, "PATH": str(bin_dir) + os.pathsep + os.environ["PATH"], "FAKE_HOME": str(home)}
        env.pop("CLAUDE_CONFIG_DIR", None)
        brief = home / "brief.md"
        text = "TW-Role: worker\nDo the task. λ \" & | < > ^ % !\n"
        brief.write_text(text, encoding="utf-8")
        common = ["--brief-file", str(brief), "--cd", str(home), "--home", str(home)]

        # the shim: exit 0 and silence for an old settings entry, whatever it passes
        p = tw(env, "hook", "--home", str(home), "--harness", "claude", "--owner", "thinker-worker-v1",
               stdin='{"tool_name": "Agent"}')
        assert (p.returncode, p.stdout, p.stderr) == (0, "", ""), p

        expect = {"codex": ("gpt-x", "codex done"), "claude": ("claude-opus-5-5", "claude done"),
                  "agy": ("gemini-x-high", "agy done"), "omp": (None, "omp done")}
        for tool, (model, answer) in expect.items():
            extra = ["--model", model, "--effort", "high"] if model else []
            p = tw(env, tool, *common, *extra)
            assert p.returncode == 0, (tool, p.stdout, p.stderr)
            res = json.loads(p.stdout)
            assert res["completed"] and Path(res["last_message"]).read_text(encoding="utf-8") == answer, res
            call = json.loads((home / f"{tool}-call.json").read_text(encoding="utf-8"))
            sent = json.loads(call["stdin"])["message"]["content"] if tool == "agy" else call["stdin"]
            assert sent == text, (tool, call)  # verbatim, metacharacters included
            if model:
                assert model in call["args"], (tool, call)
        assert res["model"] == "local-a" and res["effort"] == "medium" and res["session_id"] == "W1", res
        codex = json.loads((home / ".thinker-worker" / "log.jsonl").read_text(encoding="utf-8").splitlines()[0])
        assert codex["model"] == "gpt-x" and codex["effort"] == "high" and codex["session_id"] == "T1", codex
        assert "danger-full-access" in json.loads((home / "codex-call.json").read_text(encoding="utf-8"))["args"]
        claude = json.loads((home / ".thinker-worker" / "log.jsonl").read_text(encoding="utf-8").splitlines()[1])
        assert claude["model"] == "claude-opus-5-5" and claude["session_id"] == "S1", claude
        assert "--dangerously-skip-permissions" in json.loads((home / "agy-call.json").read_text(encoding="utf-8"))["args"]
        assert len((home / ".thinker-worker" / "log.jsonl").read_text(encoding="utf-8").splitlines()) == 4

        # OMP: a timed-out first attempt continues the saved session once
        p = tw({**env, "FAKE_SLEEP_ONCE": "1"}, "omp", *common, "--timeout", "3")
        res = json.loads(p.stdout)
        assert p.returncode == 0 and res["continued"] and res["completed"], res
        assert "Continue the same bounded assignment" in json.loads((home / "omp-call.json").read_text(encoding="utf-8"))["stdin"]
        # ... and a run that still times out hands back the command that continues it
        p = tw({**env, "FAKE_SLEEP_ALWAYS": "1"}, "omp", *common, "--timeout", "3")
        res = json.loads(p.stdout)
        assert p.returncode != 0 and res["timed_out"] and "--resume" in res["resume_command"], res

        # ran: role, per-turn model and effort, token totals de-duplicated per message id
        sub = home / ".claude" / "projects" / "C--proj" / "sess-1" / "subagents"
        sub.mkdir(parents=True)
        (sub / "agent-a1.meta.json").write_text(json.dumps({"agentType": "general-purpose", "description": "fix it",
                                                            "model": "opus", "effort": "high"}), encoding="utf-8")
        turn = lambda mid, model, effort, out: {"type": "assistant", "effort": effort, "message": {
            "id": mid, "model": model, "usage": {"input_tokens": 1, "output_tokens": out}}}
        lines = [{"type": "user", "message": {"role": "user", "content": "<teammate-message teammate_id=\"lead\">\nTW-Role: independent-review\nReview X."}},
                 turn("m1", "claude-opus-5-5", "high", 5), turn("m1", "claude-opus-5-5", "high", 6),
                 turn("m2", "claude-opus-5-5", "high", 1), turn("m3", "claude-sonnet-x", "medium", 2),
                 {"type": "assistant", "message": {"model": "<synthetic>"}}]
        (sub / "agent-a1.jsonl").write_text("\n".join(json.dumps(x) for x in lines) + "\n{torn", encoding="utf-8")
        p = tw(env, "ran", "sess-1", "--home", str(home))
        child = json.loads(p.stdout)
        assert child["role"] == "independent-review" and child["name"] == "fix it", child
        assert child["turns"] == [["claude-opus-5-5", "high", 2],["claude-sonnet-x", "medium", 1]], child
        assert child["output_tokens"] == 6 + 1 + 2 and child["input_tokens"] == 3, child
        assert tw(env, "ran", "--home", str(home)).stdout == p.stdout  # default: the latest session
        assert tw(env, "ran", "no-such-session", "--home", str(home)).stdout == ""


if __name__ == "__main__":
    test_all()
    print("ok")
