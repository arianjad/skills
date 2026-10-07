"""Pinned native review avoids alias coercion, verifies definition and actual identity."""
from pathlib import Path
import tempfile
from unittest.mock import patch
import tw
from test_tw_receipt import REV, AUTH, W

R=tw.load_routes(tw.source_root()/'routes.json')

def decision(agent, model=None, brief=REV):
    return tw.decide('claude',{'tool_name':'Agent','tool_input':dict(subagent_type=agent,model=model,prompt=brief)},R)

for tier in ('medium','high','xhigh'):
    d=decision(f'tw-independent-review-{tier}-opus55')
    assert d.admitted and d.model=='claude-opus-5-5' and d.tier==tier
assert not decision('tw-independent-review-low-opus55').admitted
assert not decision('tw-independent-review-high-opus55','opus').admitted
assert not decision('tw-independent-review-high-opus55','fable').admitted
assert not decision('tw-independent-review-high-opus55',brief=REV.replace(AUTH,'')).admitted
assert not decision('tw-worker-high-opus55',brief=W).admitted
assert not decision('tw-independent-review-high-opus99').admitted

with tempfile.TemporaryDirectory() as tmp:
    home=Path(tmp); cd=home/'project'; cd.mkdir()
    brief=cd/'brief.txt'; brief.write_text(REV)
    agent='tw-independent-review-high-opus55'
    definition=home/'.claude/agents'/f'{agent}.md'
    definition.parent.mkdir(parents=True)
    definition.write_bytes(tw.agent_files(R)[f'{agent}.md'])
    def execute(model='claude-opus-5-5',effort='high'):
        with patch.object(tw,'load_routes',return_value=R),patch.object(tw.shutil,'which',return_value='fake'), \
             patch.object(tw,'activate'),patch.object(tw,'run_bounded',return_value=dict(out='review',code=0,timed_out=False,kill_failed=False)) as run, \
             patch.object(tw,'read_rows',return_value=[]),patch.object(tw,'dispatch_state',return_value=({'tool_use_id':'t'},'admit')), \
             patch.object(tw,'record_cost',return_value=dict(kind='cost',model=model,effort=effort,agent_type=agent)):
            code,result=tw.claude_run(home,'independent-review','high',brief,cd,'claude-opus-5-5',permission_mode='auto')
            relay=run.call_args.args[2].decode()
            assert f'subagent_type: {agent}\n' in relay and '\nmodel:' not in relay
            assert run.call_args.args[0][-1]=='auto'
            return code,result
    assert execute()[0]==0
    assert execute('claude-fable-5-1')[0]==1
    assert execute(effort='medium')[0]==1
    definition.write_text('model: opus')
    try: execute(); raise AssertionError('changed pin admitted')
    except tw.Conflict: pass
    definition.write_bytes(tw.agent_files(R)[f'{agent}.md'])
    shadow=cd/'.claude/agents'/f'{agent}.md'; shadow.parent.mkdir(parents=True); shadow.write_bytes(definition.read_bytes())
    try: execute(); raise AssertionError('local shadow admitted')
    except tw.Conflict: pass
print('PASS pinned review admission, override/role/auth/tier denials, exact definition/no shadow, auto relay and executed identity failures')
