"""Restart safety uses isolated stores and fake launcher callbacks, never this service."""
import threading
from test_system_governance import client

PATH='/api/governance/service/restart'


def configure(c):
    control=c.app.state.service_control
    calls=[]
    control.restart=lambda:calls.append('restart')
    return control,calls,{'instance_id':control.instance_id}


def test_launcher_required_and_csrf_preserved(client):
    c,_,_=client
    state=c.get(PATH).json()
    assert not state['supported'] and not state['can_restart']
    assert c.post(PATH,json={'instance_id':state['instance_id']}).status_code==409
    control,calls,body=configure(c)
    assert c.post(PATH,json=body,headers={'X-CSRF-Token':'wrong'}).status_code==403
    assert c.post(PATH,json=body,headers={'Origin':'https://other.example'}).status_code==403
    assert not control.pending and calls==[]


def test_only_one_restart_and_no_mutations_during_handoff(client):
    c,_,_=client;control,calls,body=configure(c)
    assert c.post(PATH,json={'instance_id':'previous-boot'}).status_code==409
    assert c.post(PATH,json=body).status_code==202
    assert c.post(PATH,json=body).status_code==202
    assert calls==['restart']
    assert c.post('/api/governance/version/scan').status_code==503
    assert c.get(PATH).json()['pending']
    assert c.get('/api/session').status_code==200


def test_running_model_is_not_interrupted(client):
    c,runtime,_=client;control,calls,body=configure(c)
    runtime.active['test']={}
    try:
        assert c.post(PATH,json=body).status_code==409
        assert not control.pending and not calls
    finally:runtime.active.clear()


def test_background_workers_block_restart_including_settlement(client):
    c,_,_=client;control,calls,body=configure(c)
    for name in ('version-verify','disclosure-model-login','disclosure-pi-test-settling'):
        stop=threading.Event();thread=threading.Thread(target=stop.wait,name=name)
        thread.start()
        try:
            assert not c.get(PATH).json()['can_restart']
            assert c.post(PATH,json=body).status_code==409
        finally:stop.set();thread.join()
    assert not control.pending and not calls


def test_inflight_write_cannot_race_restart(client):
    c,_,_=client;control,calls,body=configure(c)
    entered=threading.Event();release=threading.Event()
    @c.app.post('/api/test-inflight-write')
    def hold():
        entered.set();release.wait(5);return {'ok':True}
    thread=threading.Thread(target=lambda:c.post('/api/test-inflight-write'))
    thread.start()
    try:
        assert entered.wait(2)
        assert c.post(PATH,json=body).status_code==409
        assert not control.pending and not calls
    finally:release.set();thread.join()
    assert control.writes==0
    assert c.post(PATH,json=body).status_code==202


def test_launcher_failure_releases_reservation(client):
    c,_,_=client;control,_,body=configure(c)
    def fail():raise OSError('fixture')
    control.restart=fail
    assert c.post(PATH,json=body).status_code==202
    state=c.get(PATH).json()
    assert not state['pending'] and state['error']
    assert c.get('/api/meta?board=chinext').status_code==200
