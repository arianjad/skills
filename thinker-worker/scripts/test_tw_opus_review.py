"""User-authorized Opus 5.5 review admission; existing guards remain intact."""
import json
import tw
from test_tw_routes import claude, codex, R
from test_tw_receipt import AUTH, REV, W

assert 'claude-opus-5-5' in R['harnesses']['claude']['roles']['independent-review']['models']
assert R['harnesses']['claude']['roles']['independent-review']['tiers']==['medium','high','xhigh']
for tier in ('medium','high','xhigh'):
    assert claude(REV,f'tw-independent-review-{tier}','claude-opus-5-5').admitted
assert not claude(REV,'tw-independent-review-low','claude-opus-5-5').admitted
assert not claude(REV.replace(AUTH,''),'tw-independent-review-high','claude-opus-5-5').admitted
assert not claude(W,'tw-independent-review-high','claude-opus-5-5').admitted
assert claude(W,'tw-worker-high','claude-opus-5-5').admitted
assert not claude(REV,'tw-independent-review-high','opus').admitted
assert not codex(REV,'claude-opus-5-5','high').admitted
assert R['router']['defaults']['independent-review']=='gpt-6-astra'
assert R['harnesses']['claude']['roles']['independent-review']['models'][0]=='fable'
assert (tw.source_root()/'routes.json').read_text()==tw.dump_routes(json.loads((tw.source_root()/'routes.json').read_text()))
print('PASS Opus review medium/high/xhigh; low, absent authorization, role mismatch, alias/native Codex denied')
