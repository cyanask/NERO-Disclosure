"""Read-only projection of source receipts, isolated to one session/run snapshot."""
import json
from .evidence_access import CATEGORIES, access, compact
from .evidence_actions import pending_actions

LABELS = dict(zip(CATEGORIES, ('法律法规', '案例库', '黑名单库', '历史公告', '模板')))
KINDS = ('evidence_access', 'evidence_document', 'model_tool_call', 'tool_requested',
         'tool_returned', 'tool_failed', 'model_tool_failed', 'knowledge_requested',
         'knowledge_returned', 'context_loaded', 'result_snapshot', 'verification',
         'documents_created', 'drafts_saved', 'documents_reused', 'capability_unavailable')


def journal(store, run_ids):
    """SQL-filter operational receipts, never load conversation text or streaming deltas."""
    result = []
    with store.connect() as conn:
        for rid in run_ids:
            rows = conn.execute('SELECT seq,run_id,kind,body FROM journal WHERE run_id=? AND kind IN (' +
                                ','.join('?' for _ in KINDS) + ') ORDER BY seq', (rid, *KINDS)).fetchall()
            result.extend({**dict(row), 'body': json.loads(row['body'])} for row in rows)
    return result


def build(runs, rows):
    groups = {key: {'key': key, 'label': LABELS[key], 'items': [], 'searched': False,
                    'empty_search': False, 'failed': False, 'unavailable': False,
                    'incomplete': False, 'checks': [], 'initiated_actions': []} for key in CATEGORIES}
    merged = {}; unknown = set(); legacy = False; unclassified_failures = set()

    def add(item, state, rid):
        if not item or item.get('category') not in groups:
            return
        version = item.get('text_sha256') or item.get('sha256') or item.get('document_sha256') or item.get('version') or item.get('effective_from') or ''
        key = (item['category'], item['id'], str(version))
        row = merged.setdefault(key, {**item, 'key': '|'.join(key), 'states': [], 'run_ids': [], 'pages': []})
        if state not in row['states']: row['states'].append(state)
        if rid not in row['run_ids']: row['run_ids'].append(rid)
        row['pages'] = sorted(set(row['pages']) | set(item.get('pages', [])))

    for run in reversed(runs):  # API order is newest first; names stay bound to each run.
        rid = run['id']; events = [r for r in rows if r['run_id'] == rid]
        known = {}; requests = {}; last_calls = {}; completed = set()
        modern = any(r['kind'] == 'evidence_access' for r in events)
        legacy |= not modern

        def remember(source, collection=''):
            item = compact(source, collection)
            if item: known[item['id']] = item
            return item

        def context(value):
            for collection, key in (('laws', 'sources'), ('cases', 'cases'), ('templates', 'templates'), ('templates', 'profiles')):
                for source in value.get(key, []):
                    if str(source.get('id', '')).startswith(('user:', 'event:', 'document:')): continue
                    item = remember(source, collection)
                    if key in ('sources', 'cases') and (source.get('text') or source.get('pages')):
                        add(item, 'provided', rid)
            for source in value.get('announcement_schedule', {}).get('items', []):
                remember(source, 'history')

        def consume(value):
            key = value.get('category')
            if key not in groups and value.get('item_id') in known:
                key = known[value['item_id']]['category']
            if key not in groups:
                if value.get('action') == 'failed': unclassified_failures.add((rid, value.get('item_id')))
                return
            group = groups[key]; action = value.get('action')
            if action == 'failed': group['failed'] = True; return
            if value.get('status') in ('not_connected', 'unavailable'):
                group['unavailable'] = True; return
            if action == 'search':
                group['searched'] = True
                group['empty_search'] |= value.get('total') == 0
            if value.get('groups_only'): return
            for item in value.get('items', []):
                known[item['id']] = item
                add(item, 'read' if action == 'read' else 'searched', rid)

        # Register snapshot names first; source_ids alone are never title authority.
        for event in events:
            body = event['body']; kind = event['kind']
            if kind == 'context_loaded': context(body.get('context', {}))
            if kind == 'tool_returned' and body.get('name') == 'task.open': context(body.get('result', {}))
            if kind == 'result_snapshot':
                for source in body.get('sources', []): remember(source)
            if kind == 'evidence_access':
                for item in body.get('items', []): known[item['id']] = item
            if kind in ('tool_returned', 'knowledge_returned'):
                data = body.get('result', {})
                if isinstance(data, dict):
                    for source in data.get('items', []) + data.get('articles', []): remember(source, data.get('collection', ''))
                    remember(data)

        for event in events:
            body = event['body']; kind = event['kind']; name = body.get('name', '')
            if kind in ('model_tool_call', 'knowledge_requested', 'tool_requested'):
                args = body.get('args', {}); last_calls[name] = args
                if body.get('id'): requests[body['id']] = (name, args)
            elif kind == 'evidence_access': consume(body)
            elif kind in ('tool_returned', 'knowledge_returned'):
                if body.get('id'): completed.add(body['id'])
                args = requests.get(body.get('id'), (name, last_calls.get(name, {})))[1]
                value = access(name, args, body.get('result'))
                if value: consume(value)
            elif kind in ('tool_failed', 'model_tool_failed'):
                if body.get('id'): completed.add(body['id'])
                args = requests.get(body.get('id'), (name, last_calls.get(name, {})))[1]
                value = access(name, args, failed=True)
                if value: consume(value)
            elif kind == 'capability_unavailable' and name == 'client_history': groups['history']['unavailable'] = True
            if kind == 'result_snapshot':
                # These are recorded candidate citations, not a claim of legal acceptance.
                for source in body.get('sources', []): add(remember(source), 'cited', rid)
                result = body.get('result') or {}
                if result.get('template_id'):
                    item = known.get(result['template_id'])
                    add(item, 'matched', rid)
            if kind == 'evidence_document':
                for sid in body.get('source_ids', []):
                    if sid in known: add(known[sid], 'cited', rid)
                    else: unknown.add((rid, sid))
            if kind in ('documents_created', 'drafts_saved', 'documents_reused'):
                for doc in body.get('documents', []):
                    identity = doc.get('template_id')
                    if identity:
                        item = known.get(identity) or compact({'id': identity, 'title': doc.get('template_name') or '模板名称未记录'}, 'templates')
                        add(item, 'used', rid)
            # Only the verifier's explicit field-check receipt can claim complete coverage.
            gate = body if kind == 'verification' else (body.get('result') or {}).get('gate', {}) if kind == 'tool_returned' else {}
            check = gate.get('history_check') if isinstance(gate, dict) else None
            if check and check.get('performed'):
                receipt = {**check, 'run_id': rid}
                if receipt not in groups['history']['checks']: groups['history']['checks'].append(receipt)
        for category, actions in pending_actions(events,known).items():
            groups[category]['incomplete'] |= bool(actions)
            groups[category]['initiated_actions']=list(dict.fromkeys(groups[category]['initiated_actions']+actions))

    for item in merged.values(): groups[item['category']]['items'].append(item)
    for group in groups.values():
        group['items'].sort(key=lambda r: (r['title'], r.get('article', ''), r['key']))
    return {'groups': list(groups.values()), 'legacy': legacy, 'unresolved_citations': len(unknown),
            'unclassified_failures': len(unclassified_failures),
            'notice': '会话清单汇总查阅记录；已引用指结果中的来源标记，不代表专业核验通过。'}
