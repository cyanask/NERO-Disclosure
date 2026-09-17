from fastapi import HTTPException
import pytest
from test_pi_runtime import client, new_session, send, settled
from test_agent_tasks import candidate, latest


def test_result_snapshot_and_closing_failure_keep_registered_outcome(client):
    c,runtime,_=client;s,e=new_session(c)
    def runner(packet,emit,bridge,stop):
        emit({'type':'started'})
        response=bridge('submit_candidate',{'result':candidate()})
        assert response['finalize'] is True
        assert response['data']['result_snapshot']['result']['summary']==candidate()['summary']
        with pytest.raises(HTTPException) as exc:bridge('read_event',{})
        assert exc.value.status_code==409
        raise RuntimeError('closing transport failed')
    runtime.runner=runner
    r,_=send(c,s,e,'assessment');result=settled(c,r)
    assert result['run']['status']=='waiting_approval'
    assert result['run']['finalization_status']=='failed'
    snapshot=next(x['body'] for x in result['events'] if x['kind']=='result_snapshot')
    old_revision=snapshot['revision'];old_summary=snapshot['result']['summary']
    current=latest(c,e)
    assert not current.get('approval_records')
    changed=c.patch('/api/events/'+e['id'],json={'expected_revision':current['revision'],'summary':'Changed input after this run'})
    assert changed.status_code==200
    reread=c.get('/api/chat/runs/'+result['run']['id']).json()
    saved=next(x['body'] for x in reread['events'] if x['kind']=='result_snapshot')
    assert saved['revision']==old_revision and saved['result']['summary']==old_summary
    assert changed.json()['revision']>old_revision


def test_closing_receipts_do_not_confirm_business_result(client):
    c,runtime,_=client;s,e=new_session(c)
    def runner(packet,emit,bridge,stop):
        emit({'type':'started'})
        bridge('submit_candidate',{'result':candidate()})
        emit({'type':'finalization_started'})
        emit({'type':'assistant','phase':'final','message':1,'text':'请审阅本轮判断。','stopReason':'stop'})
        emit({'type':'finalization_completed'})
        emit({'type':'done'})
    runtime.runner=runner;r,_=send(c,s,e,'assessment');result=settled(c,r)
    assert result['run']['status']=='waiting_approval'
    assert result['run']['finalization_status']=='completed'
    assert not latest(c,e).get('approval_records')
