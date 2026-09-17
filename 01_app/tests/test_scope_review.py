from internal_workflow import route as internal_route
from internal_workflow import context as read_context
"""V1 checks of corrected board membership and unsupported evidence rejection."""
import copy
import hashlib
import json
import pytest
from collections import defaultdict
from pathlib import Path

from backend.domain import Seeds
from test_agent_tasks import env, event, claimed, submit, candidate, post, advance, confirm_stage, plan_candidate

ROOT = Path(__file__).resolve().parents[1]


def test_exclusive_articles_and_mixed_requirements_use_the_current_board(env):
    client,_,root,_=env
    for board in ('base','innovation'):
        for identity in ('neeq-disclosure-2025-a37','neeq-disclosure-2025-a38','neeq-governance-2025-a83'):
            assert client.get('/api/library/items/'+identity,params={'board':board}).status_code==409
        assert not (root/'data/public/boards'/board).exists()
    row=client.get('/api/library/items/szse-chinext-2026-4.1.7',params={'board':'chinext'}).json()
    assert '董事会决议' in row['text']
    assert client.get('/api/library/items/neeq-disclosure-2025-a37',params={'board':'chinext'}).status_code==404


@pytest.mark.knowledge_pack
def test_unknown_publication_layer_is_not_counted_or_sent_as_admitted_evidence(env):
    client, tokens, _, _ = env
    for board, pending in [('chinext', 19)]:
        current = client.get('/api/library/search', params={'board': board, 'collection': 'cases'}).json()
        assert current['total'] == 100
        assert all(r['eligible_as_case_evidence'] is True for r in current['items'])
        assert current['case_scope_summary']['candidates'] == pending
        candidates = client.get('/api/library/search', params={'board': board, 'collection': 'cases', 'view': 'candidates'}).json()
        assert candidates['total'] == pending
        assert all(r['eligible_as_case_evidence'] is False for r in candidates['items'])
    assert client.get('/api/library/search', params={'board': 'chinext', 'collection': 'laws', 'view': 'candidates'}).status_code == 422
    routed = internal_route(client,tokens[0],{'operation': 'library.search', 'args': {'board': 'chinext', 'collection': 'cases', 'view': 'candidates'}})
    assert routed.status_code == 200 and routed.json()['data']['total'] == 19
    e = event(client)
    task, lease = claimed(client, e, tokens[0])
    context = read_context(client,e,task,tokens[0]).json()
    assert context['cases'] == [] and context['case_candidates']
    assert all('text' not in c for c in context['case_candidates'])
    assert submit(client, e, task, lease, tokens[0], candidate()).status_code == 200
    assert post(client, e, f"agent-tasks/{task['id']}/adopt", tokens[0]).status_code == 200
    assert advance(client, e, 'assessment').status_code == 200
    assert confirm_stage(client, e, 'assessment', 'prepare_mandatory').status_code == 200
    task, lease = claimed(client, e, tokens[0], 'plan')
    context = read_context(client,e,task,tokens[0]).json()
    # Use the current complete plan schema; vary only the prohibited case source.
    plan = plan_candidate(context)
    invalid = copy.deepcopy(plan)
    invalid['items'][0]['source_ids'] = [context['case_candidates'][0]['id']]
    assert submit(client, e, task, lease, tokens[0], invalid).status_code == 422
    assert submit(client, e, task, lease, tokens[0], plan).status_code == 200


def test_long_imported_provisions_preserve_every_retrieved_chunk_and_parent_article():
    evidence_dir = ROOT / 'docs/qa/scope-review-20260910/evidence'
    required = ('chinext-kb.json', 'src-csrc-listed-disclosure-226-kb.json')
    missing = [name for name in required if not (evidence_dir / name).is_file()]
    if missing:
        pytest.skip('缺少历史 QA 原件，无法执行逐块全文比较：' + ', '.join(missing))
    catalog = Seeds(ROOT, 'chinext').catalog()
    sources = {r['id']: r for r in catalog['sources']}
    full = json.loads((ROOT / 'docs/qa/scope-review-20260910/evidence/chinext-kb.json').read_text())['fulltext_document']
    groups = defaultdict(list)
    for unit in full['units']:
        groups[unit['label']].append(unit)
    assert len(full['units']) == 394 and len(groups) == 390
    for article in ('4.2.2', '10.5.2', '13.1'):
        row = sources['szse-chinext-2026-' + article]
        assert row['text'] == ''.join(u['text'] for u in sorted(groups[article], key=lambda u: u['ordinal']))
        assert row['text_sha256'] == hashlib.sha256(row['text'].encode()).hexdigest()
    full = json.loads((ROOT / 'docs/qa/scope-review-20260910/evidence/src-csrc-listed-disclosure-226-kb.json').read_text())['fulltext_document']
    for node in full['nodes']:
        if node['node_type'] == 'article':
            assert sources['csrc-listed-2025-' + node['label']]['text'] == node['text']
    instruments = {r['id']: r for r in catalog['instruments']}
    assert instruments['src-csrc-listed-disclosure-226']['article_count'] == 67
    assert instruments['src-szse-chinext-listing-2026']['article_count'] == 390
