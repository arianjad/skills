"""Antigravity (agy) backend through the real CLI, against a fake `agy` executable on PATH."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

TW = str(Path(__file__).with_name("tw.py"))
BRIEF = "TW-Role: worker\nTW-Class: C-coding\nTW-Deliverable: result\nTW-Accept: verify result\nTW-Risk: none\nDo the bounded task."
FAKE = r'''
import json, os, sys, time
from pathlib import Path
args = sys.argv[1:]
home = Path(os.environ['FAKE_AGY_HOME'])
stdin = sys.stdin.buffer.read().decode('utf-8')
(home/'call.json').write_text(json.dumps({'args':args,'stdin':stdin,'cwd':os.getcwd()}),encoding='utf-8')
time.sleep(float(os.environ.get('FAKE_SLEEP','0')))
def value(flag, default=None):
    return args[args.index(flag)+1] if flag in args else default
model = value('--model', os.environ.get('FAKE_DEFAULT_MODEL','gemini-default-low'))
conv = value('--conversation', 'conv-fresh-1')
print(json.dumps({'event':'init','conversation_id':conv,'init':{'model':model,'cwd':os.getcwd()}}))
print('not-json diagnostic')
print(json.dumps({'event':'step_update','usage':{'input_tokens':5,'output_tokens':1}}))
if not os.environ.get('FAKE_NO_RESULT'):
    status = 'ERROR' if os.environ.get('FAKE_ERROR') else 'SUCCESS'
    resp = '' if os.environ.get('FAKE_EMPTY') else 'Fake agy says OK.'
    print(json.dumps({'event':'result','result':{'conversation_id':conv,'status':status,'response':resp,
        'num_turns':1,'usage':{'input_tokens':12,'output_tokens':4}}}))
sys.exit(int(os.environ.get('FAKE_EXIT','0')))
'''


def run(home, env, *args):
    return subprocess.run([sys.executable, TW, *args, '--home', str(home)], env=env,
                          capture_output=True, text=True, encoding='utf-8', timeout=45)


if __name__ == '__main__':
    with tempfile.TemporaryDirectory(prefix='agy backend ') as temp:
        home = Path(temp) / 'test home'
        home.mkdir()
        executable = home / 'bin'
        executable.mkdir()
        (executable/'fake_agy.py').write_text(FAKE,encoding='utf-8')
        if os.name == 'nt':
            (executable/'agy.cmd').write_text(f'@"{sys.executable}" "%~dp0fake_agy.py" %*\n',encoding='utf-8')
        else:
            launcher = executable/'agy'
            launcher.write_text(f'#!/bin/sh\nexec "{sys.executable}" "$(dirname "$0")/fake_agy.py" "$@"\n')
            launcher.chmod(0o755)
        env = {k:v for k,v in os.environ.items() if k not in ('CODEX_THREAD_ID','CLAUDE_SESSION_ID')}
        env.update(PATH=str(executable)+os.pathsep+env['PATH'],FAKE_AGY_HOME=str(home))
        brief = home/'assignment unicode-λ.md'

        def dispatch(*extra, text=BRIEF, variables=None, role='worker'):
            brief.write_text(text,encoding='utf-8')
            result = run(home,{**env,**(variables or {})},'agy','--role',role,'--brief-file',str(brief),
                         '--cd',str(home),*extra)
            return result, json.loads(result.stdout) if result.stdout.strip() else None

        def call():
            return json.loads((home/'call.json').read_text(encoding='utf-8'))

        # Happy path: default model, default permissions, brief on stdin only.
        result, first = dispatch()
        assert result.returncode == 0, result.stderr
        assert first['completed'] and first['conversation_id']=='conv-fresh-1',first
        assert first['requested_model'] is None and first['reported_model']=='gemini-default-low' and 'effective_model' not in first,first
        assert first['usage']['input_tokens']==12 and first['usage']['output_tokens']==4,first
        assert first['exit_code']==0 and not first['timed_out'],first
        assert Path(first['last_message']).read_text(encoding='utf-8')=='Fake agy says OK.'
        assert Path(first['events']).is_file() and Path(first['stderr']).is_file(),first
        c = call()
        assert c['args']==['--print','','--input-format','stream-json','--output-format','stream-json',
                           '--dangerously-skip-permissions'],c
        assert c['cwd']==str(home.resolve()) or Path(c['cwd']).samefile(home),c
        lines = c['stdin'].splitlines()
        assert len(lines)==1,c
        msg = json.loads(lines[0])
        assert msg['event']=='user' and msg['message']['content'].endswith(BRIEF),msg
        assert f'Working directory: {home.resolve()}' in msg['message']['content'],msg
        assert first['permissions']['resolved']=={'permission':'dangerously-skip-permissions'},first
        assert first['permissions']['requested']=={'mode':None},first
        assert not (home/'.thinker-worker/state').exists(),'agy unexpectedly requires native activation'

        # Model, effort, mode, resume; quotes/newlines/unicode survive the stdin JSON line.
        tricky = BRIEF + '\nλ " & | < > ^ % ! \\ end\n'
        result, second = dispatch('--model','gemini-x-high','--effort','high','--mode','plan',
                                  '--resume','conv-old-9',text=tricky)
        assert result.returncode==0,result.stderr
        c = call()
        assert c['args']==['--print','','--input-format','stream-json','--output-format','stream-json',
                           '--model','gemini-x-high','--effort','high','--mode','plan',
                           '--conversation','conv-old-9'],c
        assert '--dangerously-skip-permissions' not in c['args'],c
        assert json.loads(c['stdin'])['message']['content'].endswith(tricky),c
        assert second['requested_model']=='gemini-x-high' and second['requested_effort']=='high',second
        assert second['reported_model']=='gemini-x-high' and second['conversation_id']=='conv-old-9',second
        assert second['permissions']['resolved']=={'permission':'mode','mode':'plan'},second
        assert second['permissions']['requested']=={'mode':'plan'},second

        # Fail before launch on structurally invalid assignments and bad settings.
        (home/'call.json').unlink()
        result, invalid = dispatch(text=BRIEF.replace('TW-Class: C-coding','TW-Class: unknown'))
        assert result.returncode==2 and invalid is None and not (home/'call.json').exists(),result
        result, invalid = dispatch('--timeout','nan')
        assert result.returncode==2 and not (home/'call.json').exists(),result
        result, invalid = dispatch(role='leaf')
        assert result.returncode==2 and not (home/'call.json').exists(),result
        review = BRIEF.replace('TW-Role: worker','TW-Role: independent-review')
        result, invalid = dispatch(text=review,role='independent-review')
        assert result.returncode==2 and 'TW-Authorization' in result.stderr and not (home/'call.json').exists(),result
        empty_path = home/'empty path'
        empty_path.mkdir()
        brief.write_text(BRIEF,encoding='utf-8')
        result = run(home,{**env,'PATH':str(empty_path)},'agy','--role','worker',
                     '--brief-file',str(brief),'--cd',str(home))
        assert result.returncode==2 and 'agy executable not found' in result.stderr,result
        if os.name == 'nt':
            result, invalid = dispatch('--model','x&echo.BAD>bad-launch')
            assert result.returncode==2 and not (home/'bad-launch').exists() and not (home/'call.json').exists(),result

        # Failure modes: every one must report completed false with its evidence files kept.
        for variables in ({'FAKE_ERROR':'1'},{'FAKE_NO_RESULT':'1'},{'FAKE_EMPTY':'1'},{'FAKE_EXIT':'7'}):
            result, failed = dispatch(variables=variables)
            assert result.returncode!=0 and not failed['completed'],(variables,failed)
            assert Path(failed['events']).is_file() and Path(failed['stderr']).is_file(),failed
        result, failed = dispatch(variables={'FAKE_ERROR':'1'})
        assert failed['status']=='ERROR',failed
        result, failed = dispatch(variables={'FAKE_NO_RESULT':'1'})
        assert failed['status'] is None and failed['exit_code']==0,failed
        result, failed = dispatch(variables={'FAKE_EXIT':'7'})
        assert failed['exit_code']==7 and result.returncode==7,(result,failed)

        result, timeout = dispatch('--timeout','0.1',variables={'FAKE_SLEEP':'10'})
        assert result.returncode!=0 and timeout['timed_out'] and timeout['exited'] and not timeout['completed'],timeout
        result, ok = dispatch(variables={'TW_AGY_TIMEOUT':'0.1','FAKE_SLEEP':'10'})
        assert ok['timed_out'],ok

        # Outcome runs TW-Check in --cd; tally groups agy runs by parsed (reported_model base, requested/suffix effort).
        text = BRIEF.replace('TW-Risk: none','TW-Risk: none\nTW-Check: test -f call.json')
        result, checked = dispatch('--model','tally-model-low','--effort','high',text=text)
        assert result.returncode==0,result.stderr
        result = run(home,env,'outcome','--harness','agy','--session',checked['session_id'],
                     '--tool-use-id',checked['tool_use_id'])
        assert result.returncode==0 and 'pass' in result.stdout,result
        result, suffixed = dispatch('--model','gemini-4-carbon-high',text=text)
        assert result.returncode==0,result.stderr
        result = run(home,env,'outcome','--harness','agy','--session',suffixed['session_id'],
                     '--tool-use-id',suffixed['tool_use_id'])
        assert result.returncode==0 and 'pass' in result.stdout,result
        result = run(home,env,'tally','--harness','agy')
        counts=[json.loads(s) for s in result.stdout.splitlines()]
        assert [(r['model'],r['tier'],r['accepted'],r['n']) for r in counts]==[
            ('gemini-4-carbon','high',1,1),('tally-model','high',1,1)],counts
        (home/'call.json').unlink()
        result = run(home,env,'outcome','--harness','agy','--session',checked['session_id'],
                     '--tool-use-id',checked['tool_use_id'])
        assert result.returncode==0 and 'fail' in result.stdout,result
        result = run(home,env,'activate','--harness','agy','--session','not-a-native-harness')
        assert result.returncode!=0
    print('agy backend: argv/stdin, permissions, resume, failures, timeout, outcome and tally passed.')
