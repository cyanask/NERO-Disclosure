"""Settings public interfaces; isolated config and fake vault, no real credentials."""
import copy
import json
import time
from pathlib import Path
import pytest
from backend.model_settings import APIS, ModelSettings
from backend.model_credentials import ModelCredentialVault,credential_metadata
from test_pi_runtime import client, new_session, send, settled


class FakeVault:
    available=True;label='隔离测试凭据库'
    def __init__(self):self.values={};self.reads=[]
    def has(self,key):return key in self.values
    def status(self,key):
        return credential_metadata(self.values[key]) if key in self.values else None
    def get(self,key):self.reads.append(key);return copy.deepcopy(self.values.get(key))
    def set(self,key,value):self.values[key]=copy.deepcopy(value)
    def delete(self,key):self.values.pop(key,None)


@pytest.fixture
def setup(client):
    c,runtime,tmp=client;runtime.settings.vault=FakeVault()
    return c,runtime,tmp


def snapshot(c):return c.get('/api/model-settings').json()


def put(c,state):
    rows=[{k:v for k,v in row.items() if k not in ('configured','credential_configured','reason')} for row in state['models']]
    return c.put('/api/model-settings',json={'expected_revision':state['revision'],'models':rows,'routes':state['routes']})


def key_profile(c):
    state=snapshot(c);state['models'][0].update(auth_type='api_key',api_key_env='',thinking_levels=['off','low','medium','high','xhigh','max'],reasoning_effort='max')
    state['routes']={'default':'fixture-a','plan':'fixture-b'}
    result=put(c,state);assert result.status_code==200,result.text
    return result.json()


def test_settings_cas_routes_and_backup(setup):
    c,runtime,tmp=setup;state=snapshot(c)
    assert state['revision']==0 and len(state['models'])==2
    changed=key_profile(c);assert changed['routes']['default']=='fixture-a'
    assert put(c,state).status_code==409
    changed['models'][0]['label']='新版配置';assert put(c,changed).status_code==200
    config=runtime.settings.path;assert config.stat().st_mode&0o777==0o600
    assert len(list((config.parent/'model-config-history').glob('*.json')))==1


def test_key_never_echoes_or_enters_config_history_journal(setup):
    c,runtime,tmp=setup;key_profile(c);secret='synthetic-sensitive-sentinel-12345'
    result=c.post('/api/model-settings/fixture-a/credential',json={'api_key':secret})
    assert result.status_code==200 and secret not in result.text
    assert secret not in json.dumps(snapshot(c))
    observed=[]
    def runner(packet,emit,bridge,stop):
        observed.append(packet);emit({'type':'started'});emit({'type':'assistant','message':0,'text':secret});emit({'type':'done'})
    runtime.runner=runner;s,e=new_session(c);result,_=send(c,s,e);done=settled(c,result)
    assert done['run']['model']['reasoning_effort']=='max'
    assert observed[0]['reasoning_effort']=='max' and observed[0]['apiKey']==secret
    assert observed[0]['model']['thinkingLevelMap']['max']=='max'
    assert secret not in json.dumps(done)
    assert not any(secret in path.read_text() for path in runtime.directory.rglob('*.json'))


def test_invalid_secret_requests_do_not_echo_input(setup):
    c,_,_=setup;key_profile(c);secret='too-short'
    r=c.post('/api/model-settings/fixture-a/credential',json={'api_key':secret,'unexpected':secret})
    assert r.status_code==422 and secret not in r.text
    r=c.post('/api/model-settings/fixture-a/credential',json={'api_key':'x'*3000})
    assert r.status_code==422 and 'xxxx' not in r.text


@pytest.mark.parametrize('patch',[{'baseUrl':'https://user:secret@example.org/v1'},{'baseUrl':'https://example.org/v1?api_key=secret'},{'baseUrl':'http://remote.example/v1'},{'api_key_env':'OPENAI_API_KEY'},{'reasoning_effort':'max','thinking_levels':['off','high']},{'auth_type':'local','baseUrl':'https://example.org'},{'auth_type':'oauth','provider':'unregistered'}])
def test_bad_endpoints_auth_or_effort_are_rejected(setup,patch):
    c,_,_=setup;state=snapshot(c);state['models'][0].update(patch)
    assert put(c,state).status_code==422
    assert snapshot(c)['revision']==0


def test_default_route_cannot_be_unknown_or_disabled(setup):
    c,_,_=setup;state=snapshot(c);state['routes']={'default':'missing'};assert put(c,state).status_code==422
    state['routes']={'default':'fixture-a'};state['models'][0]['enabled']=False;assert put(c,state).status_code==422


def test_settings_mutations_require_web_csrf_and_block_agent(setup):
    c,runtime,_=setup;state=snapshot(c);csrf=c.headers.pop('X-CSRF-Token');assert put(c,state).status_code==403;c.headers['X-CSRF-Token']=csrf
    token='retired-external-credential'
    assert c.get('/api/model-settings',headers={'Authorization':'Bearer '+token}).status_code==403
    assert c.post('/api/model-settings/catalog/refresh',json={},headers={'Authorization':'Bearer '+token}).status_code==403
    assert c.get('/api/model-settings',headers={'Authorization':'Bearer invalid-agent'}).status_code==403


def test_connection_probe_is_fixed_text_and_stale_after_config_change(setup):
    c,runtime,_=setup;state=key_profile(c);c.post('/api/model-settings/fixture-a/credential',json={'api_key':'synthetic-only-key'})
    packets=[]
    def probe(packet):
        packets.append(packet);return {'status':'passed','model':packet['model']['id'],'provider':packet['model']['provider'],'reasoning_effort':packet['reasoning_effort'],'reply':'not persisted'}
    runtime.settings.probe_runner=probe
    r=c.post('/api/model-settings/fixture-a/test',json={});assert r.status_code==200 and r.json()['status']=='passed'
    assert packets[0]['reasoning_effort']=='max' and not packets[0]['history'] and not packets[0]['tools']
    assert '本轮绑定上下文' not in packets[0]['system']
    state=snapshot(c);state['models'][0]['reasoning_effort']='high';assert put(c,state).status_code==200
    assert snapshot(c)['checks']['fixture-a']['status']=='stale'
    c.post('/api/model-settings/fixture-a/credential',json={'api_key':'synthetic-replaced-key'})
    assert 'fixture-a' not in snapshot(c)['checks']


def test_wrong_effort_probe_never_marks_success(setup):
    c,runtime,_=setup;key_profile(c);c.post('/api/model-settings/fixture-a/credential',json={'api_key':'synthetic-only-key'})
    runtime.settings.probe_runner=lambda packet:{'status':'passed','model':packet['model']['id'],'reasoning_effort':'high'}
    result=c.post('/api/model-settings/fixture-a/test',json={}).json();assert result['status']=='failed'


def test_only_selected_vault_model_is_resolved(setup):
    c,runtime,_=setup;key_profile(c);c.post('/api/model-settings/fixture-a/credential',json={'api_key':'synthetic-only-key'})
    runtime.settings.vault.reads.clear()
    runtime.settings.resolve_model('fixture-a');assert runtime.settings.vault.reads==['provider:fixture']
    assert c.delete('/api/model-settings/fixture-a/credential').status_code==200
    with pytest.raises(Exception):runtime.settings.resolve_model('fixture-a')


def test_os_vault_namespaces_do_not_share_project_credentials(tmp_path):
    assert ModelCredentialVault(tmp_path/'a').service!=ModelCredentialVault(tmp_path/'b').service


def test_actual_pi_builtin_catalog_is_used_without_network(setup):
    c,runtime,_=setup;r=c.get('/api/model-settings/catalog');assert r.status_code==200
    catalog=r.json();assert catalog['source']=='pi_builtin' and catalog['version']==runtime.settings.pi_version
    provider=next(p for p in catalog['providers'] if p['id']=='openai-codex')
    assert 'oauth' in provider['auth_types'] and provider['models']
    ids={p['id'] for p in catalog['providers']}
    # The page mirrors Pi's built-in provider directory: no allow-list, OpenCode included.
    assert {'opencode','opencode-go','openrouter','xai'} <= ids and len(ids)>=35
    go=next(p for p in catalog['providers'] if p['id']=='opencode-go')
    assert go['auth_types']==['api_key'] and len(go['models'])>=10
    assert all(m['api'] in APIS for p in catalog['providers'] for m in p['models'])
    # Providers whose every model uses a protocol this runner cannot execute stay listed and empty.
    empty={p['id'] for p in catalog['providers'] if not p['models']}
    assert empty=={'radius'}


def test_real_pi_deepseek_descriptors_survive_backend_validation(setup):
    c,runtime,_=setup
    go=next(provider for provider in runtime.settings.catalog()['providers'] if provider['id']=='opencode-go')
    for identity in ('deepseek-v4-flash','deepseek-v4-pro','deepseek-v4.1-flash'):
        descriptor=next(model for model in go['models'] if model['id']==identity)
        row=ModelSettings.candidate('opencode-go',identity,descriptor,set())
        assert row is not None,identity
        assert row['compat']['requiresReasoningContentOnAssistantMessages'] is True
        assert row['contextWindow']==1000000
        assert row['maxTokens']==descriptor['maxTokens']
        assert row['thinking_levels']==descriptor['thinking_levels']
        assert 'high' in row['thinking_levels'] and 'max' in row['thinking_levels']
        assert runtime.settings.model_packet(row)['id']==identity


def test_native_protocols_and_structured_compat_are_not_filtered(setup):
    c,runtime,_=setup
    row={**GO_ROW,'api':'bedrock-converse-stream','provider':'amazon-bedrock',
         'contextWindow':4000000,'maxTokens':65536,'compat':{'allowedFallbackModels':['native-fallback'],'chatTemplateArgs':{'enable_thinking':True}}}
    normalized=ModelSettings.normalize(row)
    assert normalized['contextWindow']==4000000 and normalized['maxTokens']==65536
    assert normalized['compat']==row['compat']


def test_every_native_catalog_definition_survives_configuration(setup):
    _,runtime,_=setup
    for provider in runtime.settings.catalog()['providers']:
        if provider['id']=='nero-opencodex-loopback':continue
        for item in provider['models']:
            row={**GO_ROW,'provider':provider['id'],'id':item['id'],'api':item['api'],'baseUrl':item['baseUrl'],
                 'thinking_levels':item['thinking_levels'],'reasoning_effort':item['thinking_levels'][0],
                 'thinking_level_map':item['thinking_level_map'],'compat':item['compat'],'input':item['input'],
                 'auth_type':'oauth' if provider['id']=='openai-codex' else 'api_key'}
            normalized=ModelSettings.normalize(row)
            assert normalized.get('compat',{})==item['compat'],(provider['id'],item['id'])
            assert normalized['thinking_level_map']==item['thinking_level_map']


def test_scoped_cloud_credentials_and_empty_azure_default(setup,tmp_path):
    from backend import model_authorization as auth
    from fastapi import HTTPException
    assert auth.provider_env('amazon-bedrock',{'AWS_PROFILE':'work-profile','AWS_REGION':'us-west-2'})['AWS_PROFILE']=='work-profile'
    path=tmp_path/'adc.json';path.write_text('{}')
    env=auth.provider_env('google-vertex',{'GOOGLE_APPLICATION_CREDENTIALS':str(path),'GOOGLE_CLOUD_PROJECT':'test-project','GOOGLE_CLOUD_LOCATION':'us-central1'})
    assert auth.keyless_configured('google-vertex',env)
    assert auth.provider_env('azure-openai-responses',{'AZURE_OPENAI_BASE_URL':'https://audit.openai.azure.com/openai/v1'})
    with pytest.raises(HTTPException):auth.provider_env('amazon-bedrock',{'UNRELATED_SECRET':'private'})
    with pytest.raises(HTTPException):auth.provider_env('azure-openai-responses',{'AZURE_OPENAI_BASE_URL':'https://user:secret@host.invalid'})
    assert ModelSettings.normalize({**GO_ROW,'provider':'azure-openai-responses','api':'azure-openai-responses','baseUrl':''})['baseUrl']==''


def test_other_native_oauth_providers_can_be_selected(setup):
    from backend.model_contract import native_providers
    for provider in native_providers().values():
        if 'oauth' not in provider['auth_types'] or not provider['models']:continue
        item=provider['models'][0]
        assert ModelSettings.normalize({**GO_ROW,'provider':provider['id'],'api':item['api'],'baseUrl':item['baseUrl'],'auth_type':'oauth'})['auth_type']=='oauth'


def test_oauth_result_is_vault_only_and_public_status_contains_no_tokens(setup):
    c,runtime,_=setup;state=snapshot(c)
    state['models'][0].update(provider='openai-codex',api='openai-codex-responses',baseUrl='https://chatgpt.com/backend-api',auth_type='oauth',api_key_env='')
    assert put(c,state).status_code==200
    credential={'type':'oauth','access':'synthetic-access-ONLY','refresh':'synthetic-refresh-ONLY','expires':9999999999999}
    def command(packet,**options):
        assert packet['operation']=='login'
        options['event_hook']({'user_code':'DEMO-CODE','url':'https://auth.openai.com/codex/device'})
        return {'credential':credential}
    runtime.settings.command=command
    job=c.post('/api/model-settings/fixture-a/login',json={}).json()
    deadline=time.monotonic()+2
    while job['status']=='waiting' and time.monotonic()<deadline:
        time.sleep(.01);job=c.get('/api/model-settings/login/'+job['id']).json()
    assert job['status']=='completed'
    assert runtime.settings.vault.values['oauth:openai-codex']==credential
    assert 'synthetic-access' not in json.dumps(job)+json.dumps(snapshot(c))
    assert not any('synthetic-access' in p.read_text() for p in runtime.directory.rglob('*.json'))


def test_native_interactive_login_answers_are_private_and_step_bound(setup):
    import threading
    c,runtime,_=setup;state=snapshot(c)
    state['models'][0].update(provider='anthropic',api='anthropic-messages',baseUrl='https://api.anthropic.com',auth_type='oauth',api_key_env='')
    assert put(c,state).status_code==200
    received=[];answered=threading.Event()
    def command(packet,**options):
        options['input_hook'](lambda value:(received.append(value),answered.set()))
        options['event_hook']({'type':'auth_prompt','id':'step-1','prompt':{'type':'secret','message':'Enter code'}})
        assert answered.wait(3)
        return {'credential':{'type':'oauth','access':'private-token','refresh':'private-refresh','expires':9999999999999}}
    runtime.settings.command=command
    job=c.post('/api/model-settings/fixture-a/login',json={}).json()
    for _ in range(100):
        job=c.get('/api/model-settings/login/'+job['id']).json()
        if job.get('prompt_id'):break
        time.sleep(.01)
    assert c.post('/api/model-settings/login/'+job['id']+'/answer',json={'prompt_id':'wrong','value':'secret-code'}).status_code==409
    result=c.post('/api/model-settings/login/'+job['id']+'/answer',json={'prompt_id':'step-1','value':'secret-code'})
    assert result.status_code==200 and 'secret-code' not in result.text
    for _ in range(100):
        job=c.get('/api/model-settings/login/'+job['id']).json()
        if job['status']!='waiting':break
        time.sleep(.01)
    assert job['status']=='completed' and received[0]['value']=='secret-code'
    assert 'private-token' not in json.dumps(job)+json.dumps(snapshot(c))


def test_running_round_blocks_settings_and_secret_mutations(setup):
    c,runtime,_=setup;state=key_profile(c);original=runtime.active
    try:
        runtime.active={'test-active':{}}
        assert snapshot(c)['running']
        assert put(c,state).status_code==409
        assert c.post('/api/model-settings/fixture-a/credential',json={'api_key':'synthetic-only-key'}).status_code==409
    finally:runtime.active=original


GO_ROW={'key':'og-flash','label':'DeepSeek V4 Flash','provider':'opencode-go','api':'openai-completions','id':'deepseek-v4-flash',
 'baseUrl':'https://opencode.ai/zen/go/v1','api_key_env':'','auth_type':'api_key','enabled':True,'visible':True,'contextWindow':1000000,'maxTokens':8192,
 'reasoning_effort':'high','thinking_levels':['off','high','max'],'thinking_level_map':{'high':'high','max':'max'},'source':'pi_builtin'}

CLOUD=[{'id':'deepseek-v4-flash','label':'DeepSeek V4 Flash','api':'openai-completions','baseUrl':'https://opencode.ai/zen/go/v1','reasoning':True,
        'thinking_levels':['off','high','max'],'thinking_level_map':{'high':'high','max':'max'},'contextWindow':1000000,'maxTokens':384000,'input':['text'],
        'compat':{'maxTokensField':'max_tokens','thinkingFormat':'deepseek'},'catalog':True},
       {'id':'kimi-k3','label':'Kimi K3','api':'openai-completions','baseUrl':'https://opencode.ai/zen/go/v1','reasoning':True,'thinking_levels':['max'],
        'thinking_level_map':{},'contextWindow':1048576,'maxTokens':131072,'input':['text'],'compat':{'supportsStore':False,'maxTokensField':'max_tokens'},'catalog':True},
       {'id':'qwen3.8-max','label':'qwen3.8-max','api':'openai-completions','baseUrl':'https://opencode.ai/zen/go/v1','reasoning':False,'thinking_levels':['off'],
        'thinking_level_map':{},'contextWindow':128000,'maxTokens':8192,'input':['text'],'compat':{},'catalog':False}]


def stub_catalog(runtime,providers=()):
    original=runtime.settings.command
    runtime.settings.command=lambda packet,**options:({'version':'test','generated_at':0,'source':'pi_builtin','providers':list(providers)} if packet['operation']=='catalog' else original(packet,**options))


def cloud_models(entries=CLOUD):
    return lambda packet,**options:{'status':'ok','source':'endpoint','endpoint':'https://opencode.ai/zen/go/v1/models','models':copy.deepcopy(entries)}


def add_row(c,row):
    state=snapshot(c);state['models'].append(copy.deepcopy(row));result=put(c,state);assert result.status_code==200,result.text
    return result.json()


def test_api_key_is_stored_once_per_provider(setup):
    c,runtime,_=setup;stub_catalog(runtime);state=snapshot(c)
    state['models'][0].update(auth_type='api_key',api_key_env='')
    state['models'].append({'key':'fixture-c','label':'离线模型 C','provider':'fixture','api':'openai-completions','id':'offline-c',
        'baseUrl':'http://127.0.0.1:1','api_key_env':'','auth_type':'api_key','enabled':True,'visible':True,'contextWindow':200000,'maxTokens':1024,
        'reasoning_effort':'off','thinking_levels':['off'],'source':'test'})
    assert put(c,state).status_code==200
    result=c.post('/api/model-settings/fixture-a/credential',json={'api_key':'synthetic-shared-key'})
    assert result.status_code==200 and result.json()['sync']['status']=='failed'
    assert set(runtime.settings.vault.values)=={'provider:fixture'}
    assert runtime.settings.vault.values['provider:fixture']['key']=='synthetic-shared-key'
    configured={row['key']:row['credential_configured'] for row in snapshot(c)['models']}
    assert configured['fixture-a'] is True and configured['fixture-c'] is True
    assert c.delete('/api/model-settings/fixture-c/credential').status_code==200
    assert snapshot(c)['models'][0]['credential_configured'] is False


def test_legacy_per_model_key_still_resolves_and_migrates(setup):
    c,runtime,_=setup;stub_catalog(runtime);key_profile(c)
    runtime.settings.vault.values['model:fixture-a']={'type':'api_key','key':'legacy-synthetic-key'}
    runtime.settings.vault.reads.clear()
    assert runtime.settings.resolve_model('fixture-a')['apiKey']=='legacy-synthetic-key'
    assert runtime.settings.vault.reads==['provider:fixture','model:fixture-a']
    c.post('/api/model-settings/fixture-a/credential',json={'api_key':'synthetic-replacement-key'})
    assert runtime.settings.resolve_model('fixture-a')['apiKey']=='synthetic-replacement-key'
    assert runtime.settings.vault.values['provider:fixture']['key']=='synthetic-replacement-key'


def test_cloud_sync_merges_provider_models(setup):
    c,runtime,_=setup;runtime.settings.catalog()
    state=snapshot(c);state['models'].append(copy.deepcopy(GO_ROW));state['routes']={'default':'fixture-a'}
    before=put(c,state).json()['revision']
    runtime.settings.command=cloud_models()
    sync=c.post('/api/model-settings/og-flash/credential',json={'api_key':'synthetic-shared-key'}).json()['sync']
    assert (sync['status'],sync['listed'],sync['added'],sync['updated'],sync['skipped'])==('synced',3,2,1,1)
    assert sync['source']=='endpoint' and sync['endpoint'].endswith('/models') and sync['models']==['Kimi K3','qwen3.8-max']
    state=snapshot(c);rows={row['id']:row for row in state['models'] if row['provider']=='opencode-go'}
    assert set(rows)=={'deepseek-v4-flash','kimi-k3','qwen3.8-max'}
    assert rows['kimi-k3']['compat']=={'supportsStore':False,'maxTokensField':'max_tokens'} and rows['kimi-k3']['thinking_levels']==['max']
    assert rows['deepseek-v4-flash']['compat']=={'maxTokensField':'max_tokens','thinkingFormat':'deepseek'}
    assert 'pending' not in state['provider_catalogs']['opencode-go']
    assert rows['qwen3.8-max']['enabled'] and rows['qwen3.8-max']['visible']
    assert all(row['source']=='provider_sync' for key,row in rows.items() if key!='deepseek-v4-flash')
    assert state['routes']=={'default':'fixture-a'} and state['revision']==before+1
    assert 'synthetic-shared-key' not in json.dumps(state)


def test_cloud_sync_failure_keeps_configuration(setup):
    c,runtime,_=setup;runtime.settings.catalog()
    before=add_row(c,GO_ROW)['revision']
    runtime.settings.command=lambda packet,**options:{'status':'failed','reason':'供应商拒绝了该 API Key'}
    sync=c.post('/api/model-settings/og-flash/credential',json={'api_key':'synthetic-shared-key'}).json()['sync']
    assert sync['status']=='failed' and sync['reason']=='供应商拒绝了该 API Key' and sync['added']==0
    state=snapshot(c);assert state['revision']==before and len(state['models'])==3


def test_sync_endpoint_and_revision_guard(setup):
    c,runtime,_=setup;runtime.settings.catalog()
    revision=add_row(c,GO_ROW)['revision']
    runtime.settings.command=cloud_models()
    c.post('/api/model-settings/og-flash/credential',json={'api_key':'synthetic-shared-key'})
    after=snapshot(c)['revision']
    assert c.post('/api/model-settings/providers/opencode-go/sync',json={'expected_revision':revision}).status_code==409
    fresh=c.post('/api/model-settings/providers/opencode-go/sync',json={'expected_revision':after})
    assert fresh.status_code==200
    body=fresh.json();assert body['sync']['status']=='unchanged' and body['sync']['added']==0 and body['settings']['revision']==after
    assert c.post('/api/model-settings/providers/not-a-provider/sync',json={}).status_code==404


def test_compat_is_validated_and_passed_to_pi(setup):
    c,runtime,_=setup
    add_row(c,{**copy.deepcopy(GO_ROW),'key':'og-compat','id':'deepseek-v4-pro','label':'DeepSeek V4 Pro',
        'compat':{'maxTokensField':'max_tokens','thinkingFormat':'deepseek'}})
    packet=runtime.settings.model_packet(runtime.settings.selected('og-compat'))
    assert packet['compat']=={'maxTokensField':'max_tokens','thinkingFormat':'deepseek'}
    assert packet['reasoning'] is True and packet['thinkingLevelMap']['high']=='high' and packet['thinkingLevelMap']['low'] is None
    state=snapshot(c);assert put(c,state).status_code==200
    assert runtime.settings.selected('og-compat')['compat']=={'maxTokensField':'max_tokens','thinkingFormat':'deepseek'}
    for hostile in ({'__proto__':'x'},{'a'*81:'x'},{'maxTokensField':'x'*81},{'jobs':'x'*1200}):
        state=snapshot(c);state['models'][-1]['compat']=hostile
        assert put(c,state).status_code==422


def test_sync_imports_beyond_the_old_eighty_model_limit(setup):
    c,runtime,_=setup;runtime.settings.catalog()
    state=snapshot(c);state['models'].append(copy.deepcopy(GO_ROW))
    while len(state['models'])<80:
        index=len(state['models'])
        state['models'].append({**copy.deepcopy(GO_ROW),'key':'og-seed-'+str(index),'id':'seed-'+str(index),'label':'种子模型 '+str(index)})
    assert put(c,state).status_code==200
    runtime.settings.command=cloud_models()
    sync=c.post('/api/model-settings/og-flash/credential',json={'api_key':'synthetic-shared-key'}).json()['sync']
    assert sync['added']==2 and sync['skipped']==1 and 'limited' not in sync
    assert len(snapshot(c)['models'])==82
