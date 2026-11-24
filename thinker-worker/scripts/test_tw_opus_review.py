"""User-authorized Opus 5.5 review admission; existing guards remain intact."""
import json
import tw
from test_tw_routes import claude, codex, N, R
from test_tw_receipt import AUTH, REV, W

assert 'claude-opus-5-5' in R['harnesses']['claude']['roles']['independent-review']['models']
assert 'opus' not in R['harnesses']['claude']['roles']['independent-review']['models']   # the alias maps in decide()
assert R['harnesses']['claude']['roles']['independent-review']['tiers']==list(tw.TIERS)
for tier in tw.TIERS:
    assert claude(REV,tier,'claude-opus-5-5').admitted
    assert claude(REV,tier,'opus').model=='claude-opus-5-5'
assert not claude(REV,'low','claude-opus-5-5',N).admitted   # a tier outside a narrowed ladder
assert not claude(REV.replace(AUTH,''),'high','claude-opus-5-5').admitted
assert claude(W,'high','claude-opus-5-5').admitted
assert not codex(REV,'claude-opus-5-5','high').admitted
assert R['harnesses']['claude']['roles']['independent-review']['models'][0]=='fable'
assert (tw.source_root()/'routes.json').read_text()==tw.dump_routes(json.loads((tw.source_root()/'routes.json').read_text()))
print('PASS Opus review low..max (full ID or alias opus); narrowed low, absent authorization, native Codex denied')
