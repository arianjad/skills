"""Opus 5.5 review: the Agent model parameter takes an alias, so independent-review `model: "opus"` requests
claude-opus-5-5; `tw.py claude --model claude-opus-5-5` relays the alias and accepts the result only when the child's
files show Opus 5.5, the requested effort and the built-in general-purpose agent."""
from pathlib import Path
import tempfile
from unittest.mock import patch
import tw
from test_tw_receipt import REV, AUTH, W
from test_tw_routes import narrowed

R=tw.load_routes(tw.source_root()/'routes.json')

def decision(model='opus', effort='high', brief=REV, routes=R, st='general-purpose'):
    return tw.decide('claude',{'tool_name':'Agent','tool_input':dict(subagent_type=st,model=model,effort=effort,prompt=brief)},routes)

for tier in tw.TIERS:
    d=decision(effort=tier)
    assert d.admitted and d.model=='claude-opus-5-5' and d.tier==tier
assert not decision(effort='low',routes=narrowed(R)).admitted   # outside a narrowed ladder
assert not decision(effort='ultra').admitted
assert not decision(brief=REV.replace(AUTH,'')).admitted
assert decision(brief=W).model=='opus'                          # only review maps the alias to the Opus 5.5 ID
assert 'model: "opus", effort: "high"' in decision(model=None,effort=None,st='tw-independent-review-high-opus55').reason

with tempfile.TemporaryDirectory() as tmp:
    home=Path(tmp); cd=home/'project'; cd.mkdir()
    brief=cd/'brief.txt'; brief.write_text(REV)
    def execute(model='claude-opus-5-5',effort='high',built_in=True):
        with patch.object(tw,'load_routes',return_value=R),patch.object(tw.shutil,'which',return_value='fake'), \
             patch.object(tw,'activate'),patch.object(tw,'run_bounded',return_value=dict(out='review',code=0,timed_out=False,kill_failed=False)) as run, \
             patch.object(tw,'read_rows',return_value=[]),patch.object(tw,'dispatch_state',return_value=({'tool_use_id':'t'},'admit')), \
             patch.object(tw,'record_cost',return_value=dict(kind='cost',model=model,effort=effort,agent_type='general-purpose',built_in=built_in)):
            code,result=tw.claude_run(home,'independent-review','high',brief,cd,'claude-opus-5-5',permission_mode='auto')
            relay=run.call_args.args[2].decode()
            assert 'subagent_type: general-purpose\nmodel: opus\neffort: high\n' in relay, relay
            assert tw.role_text('independent-review') in relay        # the relay carries the role paragraph itself
            assert run.call_args.args[0][-1]=='auto'
            return code,result
    assert execute()[0]==0
    assert execute('claude-fable-5-1')[0]==1
    assert execute(effort='medium')[0]==1
    code,result=execute(built_in=False)                               # a same-name user/project agent ran instead
    assert code==1 and 'built-in' in result['identity_error'], result
print('PASS Opus review via alias opus: low..max, narrowed/tier/auth denials, worker opus unmapped; relay alias+effort+role text; executed identity and built-in checks')
