"""Production cannot select legacy policy to bypass the full-body Word gate."""
from uuid import uuid4
from fastapi.testclient import TestClient
from backend.app import create_app
from conftest import isolated_root
from test_agent_tasks import ROOT


def test_production_creates_continuous_and_rejects_legacy_opt_out(tmp_path):
    app=create_app(tmp_path/'var',isolated_root(tmp_path),{'allowed_hosts':['testserver']})
    with TestClient(app) as client:
        token=client.get('/api/session').json()['csrf_token']
        client.headers.update({'Origin':'http://testserver','X-CSRF-Token':token})
        body={'company_name':'隔离工程测试','board':'chinext','kind':'unclassified','title':'门禁测试','summary':'仅工程验证','request_id':str(uuid4())}
        made=client.post('/api/events',json=body)
        assert made.status_code==200,made.text
        event=made.json();assert event['workflow_policy']=='continuous-v1'
        assert client.post('/api/events',json={**body,'request_id':str(uuid4()),'workflow_policy':'legacy-v1'}).status_code==422
        assert client.get('/api/events/'+event['id']+'/word/context').status_code==409
        # Existing history remains readable, but cannot be used as a production opt-out.
        with app.state.store.transaction() as conn:
            old=app.state.store.get(conn,event['id']);old['workflow_policy']='legacy-v1';old['revision']+=1
            app.state.store.save(conn,old)
        result=client.get('/api/events/'+event['id']+'/word/context')
        assert result.status_code==409 and '旧事项' in result.text
