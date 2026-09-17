"""Stage-level gate checks: law/timing, layout and source integrity."""
import hashlib
from backend import gate_checks

TEXT='4.1.7 上市公司应当依据法律法规和公司章程召开董事会。'


def catalog(**overrides):
    base={'sources':[{'id':'s1','source_kind':'official_rule','title':'规则','text':TEXT,
                      'effective_from':'2026-01-01','effective_to':None,'text_sha256':hashlib.sha256(TEXT.encode()).hexdigest(),
                      'as_of':'2026-09-01'}],
          'cases':[],'profiles':[],'rules':[],'templates':[],'layout_profiles':[],'asset_state':{}}
    base.update(overrides)
    return base


def event(**overrides):
    base={'facts':{'event_date':'2026-06-18'},'layer':'chinext','kind':'board_resolution','intake_mode':'open','law_bindings':{}}
    base.update(overrides)
    return base


def codes(issues):
    return [item['code'] for item in issues]


def test_source_within_period_and_intact_text_passes():
    assert gate_checks.source_issues(event(),catalog(),['s1'])==[]


def test_event_date_before_effective_from_is_blocked():
    assert codes(gate_checks.source_issues(event(facts={'event_date':'2025-12-31'}),catalog(),['s1']))==['law_out_of_period']


def test_unregistered_source_is_blocked():
    assert codes(gate_checks.source_issues(event(),catalog(),['s9']))==['law_missing']


def test_changed_source_text_is_detected():
    broken=catalog(sources=[{**catalog()['sources'][0],'text':'被改写'}])
    assert 'law_integrity' in codes(gate_checks.source_issues(event(),broken,['s1']))


def test_case_records_cannot_stand_in_for_a_law():
    case=catalog(sources=[{**catalog()['sources'][0],'source_kind':'case'}])
    assert 'not_a_law' in codes(gate_checks.source_issues(event(),case,['s1'],legal_only=True))
    assert 'not_a_law' not in codes(gate_checks.source_issues(event(),case,['s1']))


def test_missing_event_date_is_reported_once():
    assert codes(gate_checks.source_issues(event(facts={}),catalog(),['s1']))==['event_date_invalid']


def test_stale_verification_record_is_a_note_not_a_blocker():
    stale=catalog(sources=[{**catalog()['sources'][0],'as_of':'2026-01-01'}])
    notes=gate_checks.review_notes(event(),stale,['s1'])
    assert codes(notes)==['law_review_due'] and gate_checks.source_issues(event(),stale,['s1'])==[]


def test_unreviewed_imported_layout_is_blocked():
    profiles=catalog(templates=[{'id':'t1','layout_profile_id':'lp1'}],
                     layout_profiles=[{'id':'lp1','scope_review_status':'layout_scope_review_required'}])
    assert codes(gate_checks.layout_issues(event(template={'template_id':'t1'}),profiles))==['layout_scope_review_required']


def test_layout_source_observations_hash_must_match():
    profiles=catalog(templates=[{'id':'t1','layout_profile_id':'lp1'}],
                     layout_profiles=[{'id':'lp1','source_observations_path':'data/lp1.json','source_observations_sha256':'a'*64}],
                     asset_state={'data/lp1.json':'b'*64})
    assert codes(gate_checks.layout_issues(event(draft={'template_id':'t1'}),profiles))==['layout_integrity']


def test_layout_checks_ignore_an_unrelated_profile():
    profiles=catalog(templates=[{'id':'t1','layout_profile_id':'lp9'}],
                     layout_profiles=[{'id':'lp1','scope_review_status':'layout_scope_review_required'}])
    assert gate_checks.layout_issues(event(template={'template_id':'t1'}),profiles)==[]
