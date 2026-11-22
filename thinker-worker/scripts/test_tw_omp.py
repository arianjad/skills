"""Configured OMP backend through the real CLI, with a disposable executable/config/session."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

import tw

TW = str(Path(__file__).with_name("tw.py"))
BRIEF = "TW-Role: worker\nTW-Class: C-coding\nTW-Deliverable: result\nTW-Accept: verify result\nTW-Risk: none\nDo the bounded task."
FAKE = r'''
import json, os, sys, time
from pathlib import Path
args = sys.argv[1:]
home = Path(os.environ['FAKE_OMP_HOME'])
prompt = sys.stdin.buffer.read().decode('utf-8')
count_path = home/'call-count.txt'
count = int(count_path.read_text() or '0') + 1 if count_path.exists() else 1
count_path.write_text(str(count),encoding='utf-8')
(home/'call.json').write_text(json.dumps({'args':args,'prompt':prompt,'cwd':os.getcwd(),'count':count}),encoding='utf-8')
def value(flag, default=None):
    return args[args.index(flag)+1] if flag in args else default
if '--resume' in args:
    session = Path(value('--resume'))
    records = [json.loads(s) for s in session.read_text(encoding='utf-8').splitlines()]
    sid = records[0]['id']
else:
    sid = 'saved-worker-123'
    session = Path(value('--session-dir'))/('2026-11-15_'+sid+'.jsonl')
    session.parent.mkdir(parents=True,exist_ok=True)
    records = [{'type':'session','id':sid}]
models = [r['model'] for r in records if r.get('type')=='model_change']
levels = [r['thinkingLevel'] for r in records if r.get('type')=='thinking_level_change']
selected = value('--model',models[-1] if models else os.environ.get('FAKE_MODEL','configured-a/alpha'))
provider, model = selected.split('/',1)
thinking = value('--thinking',levels[-1] if levels else os.environ.get('FAKE_THINKING','medium'))
records += [{'type':'model_change','model':selected},{'type':'thinking_level_change','thinkingLevel':thinking}]
if not os.environ.get('FAKE_NO_SESSION'):
    session.write_text('\n'.join(json.dumps(r) for r in records)+'\n',encoding='utf-8')
    print(json.dumps({'type':'session','id':sid}),flush=True)
if os.environ.get('FAKE_PARTIAL_BEFORE_SLEEP') and '--resume' not in args:
    print(json.dumps({'type':'message_end','message':{'role':'assistant','provider':provider,'model':model,
     'stopReason':'stop','content':[{'type':'text','text':'partial answer from the timed-out attempt'}]}}),flush=True)
    print(json.dumps({'type':'agent_end','isTerminal':True,'yielded':True}),flush=True)
sleep = float(os.environ.get('FAKE_SLEEP','0'))
if os.environ.get('FAKE_SLEEP_ONCE'):
    marker = home/'sleep-once.marker'
    if not marker.exists():
        marker.write_text('slept',encoding='utf-8')
        time.sleep(sleep)
else:
    time.sleep(sleep)
print('not-json diagnostic')
if os.environ.get('FAKE_NO_RESULT_ON_RESUME') and '--resume' in args:
    sys.exit(0)
if os.environ.get('FAKE_NO_RESULT'):
    sys.exit(0)
print(json.dumps({'type':'message_end','message':{'role':'assistant','provider':provider,'model':model,
 'stopReason':'error' if os.environ.get('FAKE_MODEL_ERROR') else 'stop',
 'content':[{'type':'thinking','thinking':'PRIVATE REASONING DO NOT RETURN'},
            {'type':'text','text':'Result claims a different prose-model; use metadata.'}],
 'usage':{'input':12,'output':4,'cacheRead':3}}}))
if not os.environ.get('FAKE_NO_END'):
    print(json.dumps({'type':'agent_end','isTerminal':True,'yielded':True}))
print('{torn final event')
sys.exit(int(os.environ.get('FAKE_EXIT','0')))
'''


def run(home, env, *args):
    return subprocess.run([sys.executable, TW, *args, '--home', str(home)], env=env,
                          capture_output=True, text=True, encoding='utf-8', timeout=45)


if __name__ == '__main__':
    with tempfile.TemporaryDirectory(prefix='omp backend ') as temp:
        home = Path(temp) / 'test home'
        home.mkdir()
        executable = home / 'bin'
        executable.mkdir()
        (executable/'fake_omp.py').write_text(FAKE,encoding='utf-8')
        if os.name == 'nt':
            (executable/'omp.cmd').write_text(f'@"{sys.executable}" "%~dp0fake_omp.py" %*\n',encoding='utf-8')
        else:
            launcher = executable/'omp'
            launcher.write_text(f'#!/bin/sh\nexec "{sys.executable}" "$(dirname "$0")/fake_omp.py" "$@"\n')
            launcher.chmod(0o755)
        env = {k:v for k,v in os.environ.items() if k not in ('CODEX_THREAD_ID','CLAUDE_SESSION_ID')}
        env.update(PATH=str(executable)+os.pathsep+env['PATH'],FAKE_OMP_HOME=str(home))
        brief = home/'assignment unicode-λ.md'
        brief.write_text(BRIEF,encoding='utf-8')

        def dispatch(*extra, text=BRIEF, variables=None):
            brief.write_text(text,encoding='utf-8')
            result = run(home,{**env,**(variables or {})},'omp','--role','worker','--brief-file',str(brief),
                         '--cd',str(home),*extra)
            return result, json.loads(result.stdout) if result.stdout.strip() else None

        result, first = dispatch()
        assert result.returncode == 0, result.stderr
        assert first['completed'] and first['effective_model']=='alpha' and first['provider']=='configured-a',first
        assert first['timeout_seconds']==7200 and first['retry_enabled'] and not first['retry_used'],first
        assert first['requested_model'] is None and first['requested_thinking'] is None,first
        assert first['observed_thinking']=='medium' and Path(first['session_file']).is_file(),first
        call = json.loads((home/'call.json').read_text(encoding='utf-8'))
        assert '--model' not in call['args'] and '--thinking' not in call['args'],call
        assert '--approval-mode' not in call['args'] and '--auto-approve' not in call['args'],call
        assert '--no-extensions' not in call['args'] and '--no-skills' not in call['args'],call
        assert '--wait-async' in call['args'] and call['prompt'].endswith(BRIEF),call
        assert 'Assignment contract:' in call['prompt'] and 'Deliverable: result' in call['prompt'],call
        assert 'Use only the ownership and boundaries stated in the assignment body.' in call['prompt'],call
        assert not any(arg.startswith('@') for arg in call['args']),call
        assert f'Working directory: {home}' in call['prompt'],call
        assert 'PRIVATE' not in Path(first['last_message']).read_text(encoding='utf-8')
        assert first['usage']['input']==12 and first['usage']['output']==4,first
        assert not (home/'.thinker-worker/state').exists(),'OMP unexpectedly requires native activation'

        large_brief = BRIEF + '\n' + 'λ " & | < > ^ % !\n' * 5000
        result, large = dispatch(text=large_brief)
        assert result.returncode==0,result.stderr
        call = json.loads((home/'call.json').read_text(encoding='utf-8'))
        assert call['prompt'].endswith(large_brief),len(call['prompt'])
        assert max(map(len,call['args']))<1000,call['args']

        # Changing the configured model requires no caller/native-registry change.
        result, changed = dispatch(variables={'FAKE_MODEL':'different-backend/beta','FAKE_THINKING':'off'})
        assert result.returncode==0 and changed['provider']=='different-backend' and changed['effective_model']=='beta',changed
        assert changed['observed_thinking']=='off' and changed['requested_model'] is None,changed
        result, env_bounded = dispatch(variables={'TW_OMP_TIMEOUT':'12'})
        assert result.returncode==0 and env_bounded['timeout_seconds']==12,env_bounded
        assert env_bounded['retry_enabled'],'A set time limit keeps the automatic continuation'
        result, override = dispatch('--model','third/gamma','--thinking','high','--approval-mode','write')
        assert result.returncode==0 and override['effective_model']=='gamma',override
        assert override['requested_model']=='third/gamma' and override['observed_thinking']=='high',override
        call = json.loads((home/'call.json').read_text(encoding='utf-8'))
        assert call['args'][call['args'].index('--approval-mode')+1]=='write',call

        result, resumed = dispatch('--resume',first['session_file'],
                                   variables={'FAKE_MODEL':'new-config/not-the-saved-model','FAKE_THINKING':'off'})
        assert result.returncode==0 and resumed['worker_session_id']==first['worker_session_id'],resumed
        assert resumed['effective_model']=='alpha' and resumed['observed_thinking']=='medium',resumed
        assert resumed['session_id']!=first['session_id'] and resumed['session_file']==first['session_file'],resumed
        call = json.loads((home/'call.json').read_text(encoding='utf-8'))
        assert '--session-dir' not in call['args'] and '--resume' in call['args'],call
        assert call['prompt'].endswith(BRIEF),call

        # Fail before launch on structurally invalid assignments.
        (home/'call.json').unlink()
        result, invalid = dispatch(text=BRIEF.replace('TW-Class: C-coding','TW-Class: unknown'))
        assert result.returncode==2 and invalid is None and not (home/'call.json').exists(),result
        result, invalid = dispatch('--timeout','nan')
        assert result.returncode==2 and not (home/'call.json').exists(),result
        result = run(home,env,'omp','--role','independent-review','--brief-file',str(brief),'--cd',str(home))
        assert result.returncode==2 and not (home/'call.json').exists(),result
        brief.write_text(BRIEF.replace('TW-Role: worker','TW-Role: independent-review'),encoding='utf-8')
        result = run(home,env,'omp','--role','independent-review','--brief-file',str(brief),'--cd',str(home))
        assert result.returncode==2 and 'TW-Authorization' in result.stderr,result
        empty_path = home/'empty path'
        empty_path.mkdir()
        brief.write_text(BRIEF,encoding='utf-8')
        result = run(home,{**env,'PATH':str(empty_path)},'omp','--role','worker',
                     '--brief-file',str(brief),'--cd',str(home))
        assert result.returncode==2 and 'OMP executable not found' in result.stderr,result
        if os.name == 'nt':
            result, invalid = dispatch('--model','third/gamma&echo.BAD>bad-launch')
            assert result.returncode==2 and not (home/'bad-launch').exists() and not (home/'call.json').exists(),result

        for variables in ({'FAKE_MODEL_ERROR':'1'},{'FAKE_NO_RESULT':'1'},{'FAKE_NO_END':'1'},{'FAKE_EXIT':'7'}):
            result, failed = dispatch(variables=variables)
            assert result.returncode!=0 and not failed['completed'],(variables,failed)
            assert Path(failed['events']).is_file() and Path(failed['stderr']).is_file(),failed

        result, timeout = dispatch('--timeout','0.1',variables={'FAKE_SLEEP':'10'})
        assert result.returncode!=0 and timeout['timed_out'] and timeout['exited'] and not timeout['completed'],timeout
        assert timeout['retry_enabled'],'An explicit time limit keeps the automatic continuation'
        if timeout['kill_failed']:
            assert 'resume_command' not in timeout,'A tree that may still run must not be handed to a second writer'
        else:
            # Still out of time after the continuation: the result hands back a command that resumes the saved session.
            assert timeout['retry_used'] and len(timeout['attempts'])==2 and timeout['attempts'][1]['timed_out'],timeout
            continuation = Path(timeout['resume_command'].split('--brief-file "')[1].split('"')[0])
            text = continuation.read_text(encoding='utf-8')
            assert text.startswith('TW-Role: worker\n') and 'TW-Accept:' in text,text
            assert 'previous attempt reached its time allowance' in text,text
            assert f'--resume "{timeout["session_file"]}"' in timeout['resume_command'],timeout
            resumed = subprocess.run(timeout['resume_command'],shell=True,env=env,capture_output=True,text=True,
                                     encoding='utf-8',timeout=120)
            assert resumed.returncode==0 and json.loads(resumed.stdout)['completed'],resumed
            call = json.loads((home/'call.json').read_text(encoding='utf-8'))
            assert '--resume' in call['args'] and 'previous attempt reached its time allowance' in call['prompt'],call

        # Normal retry is the same saved OMP session, with explicit continuity constraints. It runs at most once.
        structured = BRIEF.replace('TW-Risk: none',
            'TW-Risk: none\nTW-Scope: only result.txt\nTW-Checkpoint: preserve result.txt before timeout\nTW-Stop: stop after the check passes')
        (home/'sleep-once.marker').unlink(missing_ok=True)
        result, retried = dispatch('--timeout','5','--retry-on-timeout',text=structured,
                                   variables={'FAKE_SLEEP':'10','FAKE_SLEEP_ONCE':'1'})
        assert retried['initial_timed_out'],(result,retried)
        if retried['retry_used']:
            assert result.returncode==0 and retried['completed'],(result,retried)
            assert len(retried['attempts'])==2 and not retried['timed_out'],retried
            assert retried['attempts'][0]['timed_out'] and not retried['attempts'][1]['timed_out'],retried
            assert all(Path(a['events']).is_file() and Path(a['stderr']).is_file() for a in retried['attempts']),retried
            call = json.loads((home/'call.json').read_text(encoding='utf-8'))
            assert '--resume' in call['args'] and call['count']>=2,call
            assert 'previous attempt reached its time allowance' in call['prompt'],call
            assert 'Scope: only result.txt' in call['prompt'] and 'Stop: stop after the check passes' in call['prompt'],call
        else:
            # Windows taskkill can deny/not-find the disposable .cmd tree. A retry must then be skipped, not forced.
            assert retried['kill_failed'] and retried['retry_skipped_reason']=='first process tree did not verifiably exit',retried

        # A resumed attempt without its own final answer cannot borrow the first attempt's answer or terminal event.
        (home/'sleep-once.marker').unlink(missing_ok=True)
        result, no_final = dispatch('--timeout','5','--retry-on-timeout',text=structured,
                                    variables={'FAKE_SLEEP':'10','FAKE_SLEEP_ONCE':'1',
                                               'FAKE_NO_RESULT_ON_RESUME':'1',
                                               'FAKE_PARTIAL_BEFORE_SLEEP':'1'})
        assert result.returncode!=0 and not no_final['completed'],no_final
        if no_final['retry_used']:
            assert Path(no_final['last_message']).read_text(encoding='utf-8')=='',no_final
        else:
            assert no_final['kill_failed'] and no_final['retry_skipped_reason']=='first process tree did not verifiably exit',no_final

        # A hard total budget caps even the first attempt and cannot be silently doubled by retry.
        (home/'sleep-once.marker').unlink(missing_ok=True)
        result, bounded = dispatch('--timeout','5','--total-timeout','0.5',text=structured,
                                   variables={'FAKE_SLEEP':'10','FAKE_SLEEP_ONCE':'1'})
        assert result.returncode!=0 and bounded['total_timeout_seconds']==0.5,bounded
        assert bounded['attempts'][0]['timeout_seconds']==0.5 and bounded['initial_timed_out'],bounded
        assert not bounded['retry_used'] and bounded['retry_skipped_reason'] in {
            'hard total timeout was exhausted',
            'first process tree did not verifiably exit'},bounded

        # No session, uncertain process cleanup, and external/destructive risk never replay work.
        result, no_session = dispatch('--timeout','0.5','--retry-on-timeout',text=structured,
                                      variables={'FAKE_SLEEP':'10','FAKE_NO_SESSION':'1'})
        assert result.returncode!=0 and not no_session['retry_used'],no_session
        assert no_session['retry_skipped_reason'] in {
            'no saved OMP session was available for continuity',
            'first process tree did not verifiably exit'},no_session
        (home/'call.json').unlink()
        external = structured.replace('TW-Risk: none','TW-Risk: external')
        result, invalid = dispatch('--retry-on-timeout',text=external)
        assert result.returncode==2 and invalid is None and not (home/'call.json').exists(),result

        # Outcome reuses the actual dispatch's cwd and keeps model evidence in tally.
        text = BRIEF.replace('TW-Risk: none','TW-Risk: none\nTW-Check: test -f call.json')
        result, checked = dispatch(text=text)
        assert result.returncode==0,result.stderr
        result = run(home,env,'outcome','--harness','omp','--session',checked['session_id'],
                     '--tool-use-id',checked['tool_use_id'])
        assert result.returncode==0 and 'pass' in result.stdout,result
        result = run(home,env,'tally','--harness','omp')
        counts=[json.loads(s) for s in result.stdout.splitlines()]
        assert any(r['model']=='alpha' and r['accepted']==1 and r['n']==1 for r in counts),counts
        (home/'call.json').unlink()
        result = run(home,env,'outcome','--harness','omp','--session',checked['session_id'],
                     '--tool-use-id',checked['tool_use_id'])
        assert result.returncode==0 and 'fail' in result.stdout,result
        result = run(home,env,'activate','--harness','omp','--session','not-a-native-harness')
        assert result.returncode!=0 and not (home/'.thinker-worker/state').exists()
    print('OMP backend: configured-model/caller independence, overrides, resume, failures, timeout and outcome controls passed.')
