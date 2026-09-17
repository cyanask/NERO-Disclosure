"""Work-draft progression policy; pure predicates over the event, no stores or gates."""
POLICY='continuous-v1'


def enabled(event):return event.get('workflow_policy')==POLICY


def assessment_exception(event):
    result=event.get('assessment') or {}
    return result.get('status')!='disclose' or result.get('disagreements') or any(
        m.get('special_review')=='required' or m.get('specialist_required') or m.get('urgency','normal')!='normal'
        for m in result.get('matters',[]))


def requires_human(event,stage):
    if not enabled(event):return stage in ('assessment','plan','template','word')
    return stage in ('draft','word') or stage=='assessment' and bool(assessment_exception(event))


def next_stage(event):
    if not enabled(event):return None
    return {'planning':'plan','selecting_template':'template','drafting':'draft','draft_verified':'word'}.get(event.get('stage'))
