"""Shared event-state primitives: timestamps and the invalidation of stale stage inputs."""
from datetime import datetime, timezone


def now():
    return datetime.now(timezone.utc).isoformat()


def invalidate(event, start='assessment', reason='输入或产物变化'):
    stages=('assessment','plan','template','draft','word')
    affected=stages[stages.index(start):]
    event['verified_stages'] = {k:v for k,v in event.get('verified_stages',{}).items() if k not in affected}
    for record in event.get('approval_records',[]):
        if record['node'] in affected and record.get('state')=='current':
            record.update(state='invalidated', invalidated_at=now(), invalidation_reason=reason)
    for key in affected:
        if event.get(key):
            event[key]['approved'] = False
            event[key]['verified'] = False
    if 'plan' in affected:
        for record in (event.get('drafting_supplements') or {}).values():
            if record.get('state')=='current':
                record.update(state='invalidated', invalidated_at=now(), invalidation_reason=reason)
    event['stage'] = 'needs_reassessment' if start=='assessment' else start+'_revision_required'
