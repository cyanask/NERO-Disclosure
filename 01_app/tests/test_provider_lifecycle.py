"""Provider lifecycle regressions; isolated vault/config and bounded synthetic network replies."""
import asyncio
import copy
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from backend import chat_api
from backend.model_settings import ModelSettings
from test_model_settings import setup, GO_ROW, CLOUD, add_row, snapshot, put
from test_pi_runtime import client


def prepare(c,runtime):
    add_row(c,GO_ROW)
    runtime.settings.catalog_cache={'providers':[{'id':'opencode-go','auth_types':['api_key'],'models':copy.deepcopy(CLOUD)}]}
    original=runtime.settings.command
    runtime.settings.command=lambda packet,**kw:({'status':'ok','source':'endpoint','models':copy.deepcopy(CLOUD)} if packet['operation']=='models' else original(packet,**kw))
    return runtime.settings


def test_existing_key_sync_promotes_before_new_models_can_resolve(setup):
    c,runtime,_=setup;s=prepare(c,runtime)
    s.vault.values['model:og-flash']={'type':'api_key','key':'synthetic-legacy'}
    response=c.post('/api/model-settings/providers/opencode-go/sync',json={'expected_revision':s.read()['revision']})
    assert response.status_code==200
    imported=next(row for row in s.rows() if row['id']=='kimi-k3')
    assert s.vault.values['provider:opencode-go']['key']=='synthetic-legacy'
    assert s.resolve_model(imported['key'])['apiKey']=='synthetic-legacy'
    assert 'pending' not in s.read()['provider_catalogs']['opencode-go']
    assert 'synthetic-legacy' not in json.dumps(response.json())+s.path.read_text()
    # Reload the persisted inventory, without a new network read.
    runtime.config_override=None
    assert ModelSettings(runtime,vault=s.vault).read()['provider_catalogs']['opencode-go']['listed']==3


def test_legacy_status_is_not_cached_across_unauthorized_siblings(setup):
    c,runtime,_=setup;s=prepare(c,runtime)
    add_row(c,{**GO_ROW,'key':'og-other','id':'kimi-k3'})
    s.vault.values['model:og-flash']={'type':'api_key','key':'synthetic-legacy'}
    states={row['key']:row['credential_configured'] for row in s.public_models()}
    assert states['og-flash'] and not states['og-other']


def test_repeated_status_endpoints_never_read_secret_values(setup):
    c,runtime,_=setup;s=prepare(c,runtime)
    s.vault.values['model:og-flash']={'type':'api_key','key':'synthetic-legacy'}
    def forbidden(*args):raise AssertionError('Background status requested secret data')
    s.vault.get=forbidden
    for _ in range(4):
        for path in ('/api/model-settings','/api/chat/models'):
            response=c.get(path)
            assert response.status_code==200
            assert 'synthetic-legacy' not in response.text
    assert next(row for row in snapshot(c)['models'] if row['key']=='og-flash')['credential_configured']


def test_noninteractive_locked_status_does_not_fall_back_to_legacy(setup):
    c,runtime,_=setup;s=prepare(c,runtime);lookups=[]
    def status(account):
        lookups.append(account)
        return {'type':'locked','env_keys':None} if account=='provider:opencode-go' else None
    s.vault.status=status
    rows=s.public_models()
    assert not next(row for row in rows if row['key']=='og-flash')['configured']
    assert 'model:og-flash' not in lookups


def test_conflicting_legacy_credentials_do_not_silently_select_an_account(setup):
    c,runtime,_=setup;s=prepare(c,runtime)
    add_row(c,{**GO_ROW,'key':'og-other','id':'kimi-k3'})
    s.vault.values.update({'model:og-flash':{'type':'api_key','key':'synthetic-one'},'model:og-other':{'type':'api_key','key':'synthetic-two'}})
    before=s.path.read_bytes()
    with pytest.raises(HTTPException,match='多份不同'):s.sync_provider('opencode-go')
    assert 'provider:opencode-go' not in s.vault.values and s.path.read_bytes()==before
    # Explicitly saving the chosen key resolves the ambiguity for all models.
    s.save_key('og-flash','synthetic-chosen')
    assert s.resolve_model('og-other')['apiKey']=='synthetic-chosen'


def test_provider_revocation_blocks_all_legacy_keys_after_reload(setup):
    c,runtime,_=setup;s=prepare(c,runtime)
    add_row(c,{**GO_ROW,'key':'og-other','id':'kimi-k3'})
    s.vault.values.update({'model:og-flash':{'type':'api_key','key':'synthetic-one'},'model:og-other':{'type':'api_key','key':'synthetic-two'},'provider:opencode-go':{'type':'api_key','key':'synthetic-shared'}})
    s.remove_credential('og-flash')
    # Includes an orphaned legacy record reintroduced with a restored model configuration.
    s.vault.values['model:og-restored']={'type':'api_key','key':'synthetic-orphan'}
    add_row(c,{**GO_ROW,'key':'og-restored','id':'restored'})
    reloaded=ModelSettings(runtime,vault=s.vault)
    assert not any(row['credential_configured'] for row in reloaded.public_models() if row['provider']=='opencode-go')
    for key in ('og-flash','og-other','og-restored'):
        with pytest.raises(HTTPException):reloaded.resolve_model(key)
    with pytest.raises(HTTPException):reloaded.sync_provider('opencode-go')


@pytest.mark.parametrize('change',['config','revoke','rotate','running'])
def test_sync_releases_lock_and_rejects_stale_results(setup,change):
    c,runtime,_=setup;s=prepare(c,runtime)
    s.vault.values['provider:opencode-go']={'type':'api_key','key':'synthetic-shared'}
    started=threading.Event();release=threading.Event()
    def command(packet,**kw):
        started.set();assert release.wait(3)
        return {'status':'ok','source':'endpoint','models':copy.deepcopy(CLOUD)}
    s.command=command
    with ThreadPoolExecutor() as executor:
        task=executor.submit(s.sync_provider,'opencode-go')
        try:
            assert started.wait(1)
            assert s.lock.acquire(timeout=.2), 'Network read held the settings lock'
            try:
                if change=='config':
                    state=s.read();rows=s.rows();rows[-1]['label']='User revision';s.save(state['revision'],rows,state['routes'])
                elif change=='revoke':s.remove_credential('og-flash')
                elif change=='rotate':s.vault.set('provider:opencode-go',{'type':'api_key','key':'synthetic-replaced'})
                else:runtime.active={'active':{}}
                before=s.path.read_bytes()
            finally:s.lock.release()
        finally:release.set()
        try:
            with pytest.raises(HTTPException):task.result(timeout=2)
            assert s.path.read_bytes()==before
        finally:
            if change=='running':runtime.active={}


@pytest.mark.parametrize('path,body',[
    ('/api/model-settings/model/credential',{'api_key':'synthetic-key'}),
    ('/api/model-settings/providers/example/sync',{})])
def test_network_wait_does_not_block_asgi_event_loop(path,body):
    entered=threading.Event();release=threading.Event()
    def slow(*args):entered.set();release.wait(2);return {'status':'ok'}
    app=FastAPI()
    settings=SimpleNamespace(save_key=slow,sync_provider=slow,snapshot=lambda:{'responsive':True})
    chat_api.mount(app,SimpleNamespace(settings=settings,own=lambda:None),SimpleNamespace(actor=lambda request:{'channel':'web'}))
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app),base_url='http://testserver') as client:
            started=time.monotonic();task=asyncio.create_task(client.post(path,json=body))
            try:
                for _ in range(100):
                    if entered.is_set():break
                    await asyncio.sleep(.005)
                assert entered.is_set()
                response=await client.get('/api/model-settings')
                assert response.json()=={'responsive':True} and time.monotonic()-started<1
            finally:release.set();await task
    asyncio.run(scenario())


def test_new_cloud_ids_load_automatically_with_pi_defaults(setup):
    c,runtime,_=setup;s=prepare(c,runtime)
    new_model={'id':'cloud-new','label':'Cloud New','catalog':False,'contextWindow':128000,'maxTokens':16384,'input':['text'],
               'api':'openai-completions','baseUrl':GO_ROW['baseUrl'],'thinking_levels':['off'],'thinking_level_map':{}}
    s.command=lambda *a,**k:{'status':'ok','source':'endpoint','models':[new_model,new_model]}
    s.vault.values['provider:opencode-go']={'type':'api_key','key':'synthetic-shared'}
    sync=s.sync_provider('opencode-go')
    assert sync['status']=='synced' and sync['listed']==1 and sync['added']==1 and 'pending' not in sync
    added=next(row for row in s.rows() if row['id']=='cloud-new')
    assert added['enabled'] and added['visible'] and added['maxTokens']==16384
    assert 'pending' not in s.read()['provider_catalogs']['opencode-go']


def test_large_native_model_configuration_survives_reload(setup):
    c,runtime,_=setup;s=prepare(c,runtime)
    state=s.read();rows=s.rows()
    rows.extend({**GO_ROW,'key':'catalog-'+str(i),'id':'catalog-model-'+str(i),'label':'Native catalog model '+str(i)} for i in range(240))
    s.save(state['revision'],rows,state['routes'])
    assert s.path.stat().st_size>100000
    runtime.config_override=None
    assert len(s.rows())==243


def test_saved_cloud_inventory_reloads_without_keys_or_manual_confirmation(setup):
    c,runtime,_=setup;s=prepare(c,runtime)
    state=s.read()
    # Reproduce a catalog stored by the older confirmation-gated implementation.
    inventory={'models':[{'id':'new-cloud-only','label':'new-cloud-only','catalog':False}],
               'pending':[{'id':'new-cloud-only','reason':'old gate'}]}
    s.save(state['revision'],s.rows(),state['routes'],provider_catalogs={'opencode-go':inventory})
    from backend import model_control
    s.command=lambda packet,**options:model_control.command(s.code_root,packet,**options)
    s.vault.get=lambda *args:(_ for _ in ()).throw(AssertionError('Cached reload must not read credentials'))
    result=c.post('/api/model-settings/providers/opencode-go/sync',json={'cached':True,'expected_revision':s.read()['revision']})
    assert result.status_code==200,result.text
    assert result.json()['sync']['added']==1
    assert 'pending' not in s.read()['provider_catalogs']['opencode-go']
    assert next(row for row in s.rows() if row['id']=='new-cloud-only')['enabled']


def test_invalid_cloud_result_leaves_last_successful_inventory_and_routes(setup):
    c,runtime,_=setup;s=prepare(c,runtime)
    s.vault.values['provider:opencode-go']={'type':'api_key','key':'synthetic-shared'}
    s.sync_provider('opencode-go');before=s.path.read_bytes()
    s.command=lambda *a,**k:{'status':'ok','models':[{'id':None}]}
    assert s.sync_result('opencode-go')['status']=='failed'
    assert s.path.read_bytes()==before


def test_cloudflare_native_auth_parameters_remain_private(setup):
    c,runtime,_=setup
    row={**GO_ROW,'key':'cf','provider':'cloudflare-ai-gateway','id':'gpt-4o','baseUrl':'https://gateway.ai.cloudflare.com/v1/{CLOUDFLARE_ACCOUNT_ID}/{CLOUDFLARE_GATEWAY_ID}/openai'}
    add_row(c,row)
    env={'CLOUDFLARE_ACCOUNT_ID':'account_fixture','CLOUDFLARE_GATEWAY_ID':'gateway_fixture'}
    result=c.post('/api/model-settings/cf/credential',json={'api_key':'synthetic-cf-key','provider_env':env})
    assert result.status_code==200
    resolved=runtime.settings.resolve_model('cf')
    assert resolved['private_headers']['cf-aig-authorization']=='Bearer synthetic-cf-key'
    assert resolved['private_headers']['Authorization'] is None and resolved['private_env']==env
    assert not any(value in json.dumps(snapshot(c))+runtime.settings.path.read_text() for value in (*env.values(),'synthetic-cf-key'))
    invalid=c.post('/api/model-settings/cf/credential',json={'api_key':'synthetic-cf-key','provider_env':{'PATH':'bad'}})
    assert invalid.status_code==422
