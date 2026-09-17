"""Browser-owned Pi model settings, catalog, OAuth and bounded connection checks."""
import hashlib
import json
import os
import re
import threading
import time
from urllib.parse import urlsplit
from uuid import uuid4
from fastapi import HTTPException
from .model_credentials import ModelCredentialVault
from .model_login import LoginJobs
from . import model_control, model_authorization
from .model_contract import APIS, LEVELS, DEFAULTS, supports_oauth
from .gemini_broker import GeminiBroker, PROVIDER as GEMINI_PROVIDER, BASE_URL as GEMINI_BASE_URL, MODEL_IDS as GEMINI_MODEL_IDS, profiles as gemini_profiles, provider_catalog as gemini_catalog

STAGES={'chat','assessment','plan','template','draft','word'}
MAX_CONFIG_BYTES=10000000
MODEL_FIELDS={'key','label','provider','api','id','baseUrl','api_key_env','contextWindow','maxTokens','enabled','auth_type','reasoning_effort','thinking_levels','thinking_level_map','visible','source','compat','input'}


def fingerprint(row):return hashlib.sha256(json.dumps(row,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def validate_compat(value,depth=0):
    """Accept Pi's structured JSON compatibility flags without prototype-bearing keys."""
    if depth>8:raise ValueError()
    if value is None or isinstance(value,(bool,int,float)):return
    if isinstance(value,str):
        if len(value)>1024:raise ValueError()
        return
    if isinstance(value,list):
        if len(value)>256:raise ValueError()
        for item in value:validate_compat(item,depth+1)
        return
    if not isinstance(value,dict) or len(value)>128:raise ValueError()
    for key,item in value.items():
        if not isinstance(key,str) or not re.fullmatch(r'\$?[A-Za-z][A-Za-z0-9_]{0,79}',key) or key in ('__proto__','constructor','prototype'):raise ValueError()
        if key=='maxTokensField' and item not in ('max_tokens','max_completion_tokens',None):raise ValueError()
        validate_compat(item,depth+1)


class ModelSettings:
    def __init__(self, runtime, vault=None):
        self.runtime=runtime;self.directory=runtime.directory;self.code_root=runtime.code_root
        self.path=self.directory/'pi-models.json';self.vault=vault or ModelCredentialVault(self.directory)
        self.lock=threading.RLock();self.logins=LoginJobs(self);self.jobs=self.logins.jobs;self.catalog_cache=None;self.probe_runner=None
        self.gemini=GeminiBroker()

    def read(self):
        value=self.runtime.config()
        if not isinstance(value,dict) or set(value)-{'models','revision','routes','workflow_policy','semantic_review','provider_catalogs'}:raise HTTPException(409,'模型设置格式不受支持')
        if value.get('workflow_policy','continuous-v1') not in ('legacy-v1','continuous-v1'):raise HTTPException(409,'流程策略无效')
        return {'models':value.get('models',[]),'revision':value.get('revision',0),'routes':value.get('routes',{}),'provider_catalogs':value.get('provider_catalogs',{})}

    @staticmethod
    def normalize(row):
        try:
            if not isinstance(row,dict) or set(row)-MODEL_FIELDS:raise ValueError()
            key=row['key'];provider=row['provider'];url=urlsplit(row['baseUrl']);model=row['id'];api=row['api']
            if not re.fullmatch(r'[a-zA-Z0-9_-]{1,80}',key) or not re.fullmatch(r'[a-zA-Z0-9_.-]{1,80}',provider):raise ValueError()
            if api not in APIS or not isinstance(model,str) or not model.strip() or len(model)>160:raise ValueError()
            azure_default=provider=='azure-openai-responses' and api=='azure-openai-responses' and row['baseUrl']==''
            if not azure_default:
                if url.username or url.password or url.query or url.fragment or not url.hostname:raise ValueError()
                if url.scheme!='https' and not(url.scheme=='http' and url.hostname in ('localhost','127.0.0.1','::1')):raise ValueError()
            if len(row['baseUrl'])>400:raise ValueError()
            auth=row.get('auth_type','environment');env=row.get('api_key_env','')
            if auth not in ('environment','api_key','oauth','local','google_oauth'):raise ValueError()
            if auth=='environment' and not re.fullmatch(r'DISCLOSURE_[A-Z0-9_]{2,90}',env):raise ValueError()
            if auth=='local' and (url.scheme!='http' or url.hostname not in ('localhost','127.0.0.1','::1')):raise ValueError()
            if api=='openai-codex-responses' and (provider!='openai-codex' or auth!='oauth' or row['baseUrl'].rstrip('/')!='https://chatgpt.com/backend-api'):raise ValueError()
            if auth=='oauth' and not supports_oauth(provider):raise ValueError()
            if auth=='google_oauth' or provider==GEMINI_PROVIDER:
                if (auth,provider,api,row['baseUrl'].rstrip('/'))!=('google_oauth',GEMINI_PROVIDER,'openai-responses',GEMINI_BASE_URL):raise ValueError()
                if model not in GEMINI_MODEL_IDS:raise ValueError()
            context=int(row.get('contextWindow',DEFAULTS['contextWindow']));maximum=int(row.get('maxTokens',DEFAULTS['maxTokens']))
            if not 0<context<=9007199254740991 or not 0<maximum<=9007199254740991:raise ValueError()
            levels=row.get('thinking_levels',['off']);effort=row.get('reasoning_effort','off')
            if not isinstance(levels,list) or not levels or len(set(levels))!=len(levels) or any(x not in LEVELS for x in levels) or effort not in levels:raise ValueError()
            if not isinstance(row.get('enabled',False),bool) or not isinstance(row.get('visible',True),bool):raise ValueError()
            level_map=row.get('thinking_level_map',{})
            if not isinstance(level_map,dict) or any(k not in LEVELS or v is not None and (not isinstance(v,str) or len(v)>24) for k,v in level_map.items()):raise ValueError()
            if any(level_map.get(level,level) is None for level in levels if not(level=='off' and levels==['off'])):raise ValueError()
            if auth=='google_oauth' and (levels!=['low','high'] or any(level_map.get(level,level)!=level for level in levels)):raise ValueError()
            compat=row.get('compat',{})
            if not isinstance(compat,dict) or len(json.dumps(compat,separators=(',',':'),allow_nan=False))>32768:raise ValueError()
            validate_compat(compat)
            inputs=row.get('input',list(DEFAULTS['input']))
            if not isinstance(inputs,list) or not inputs or any(value not in ('text','image','audio','video') for value in inputs):raise ValueError()
            return {'key':key,'label':str(row.get('label',model))[:100],'provider':provider,'id':model.strip(),'api':api,'baseUrl':row['baseUrl'].rstrip('/'),
                    'api_key_env':env if auth=='environment' else '', 'auth_type':auth,'contextWindow':context,'maxTokens':maximum,
                    'enabled':row.get('enabled',False),'visible':row.get('visible',True),'reasoning_effort':effort,'thinking_levels':levels,'thinking_level_map':level_map,'source':str(row.get('source','custom'))[:100],
                    'input':inputs,**({'compat':compat} if compat else {})}
        except (KeyError,TypeError,ValueError):raise HTTPException(422,'模型字段、授权方式、端点或推理档位不受支持；未保存设置') from None

    def rows(self):
        raw=self.read()['models']
        if not isinstance(raw,list):raise HTTPException(409,'模型配置列表无效')
        rows=[self.normalize(row) for row in raw]
        if len({row['key'] for row in rows})!=len(rows):raise HTTPException(409,'模型配置标识重复')
        return rows

    def public_models(self):
        output=[];credentials={}
        for row in self.rows():
            auth=row['auth_type'];configured=False;reason='尚未启用'
            if auth=='environment':configured=bool(os.environ.get(row['api_key_env']));reason='未设置专用环境变量'
            elif auth=='local':configured=True;reason='本机服务凭据由该服务管理'
            elif auth=='google_oauth':
                state=self.gemini.status();configured=row['id'] in state['model_ids']
                reason=state['message'] if state['status']=='unavailable' else '本机通道未提供所选 Gemini 模型'
            else:
                stored=model_authorization.credential_status(self.vault,row,credentials)
                required=model_authorization.ENV_FIELDS.get(row['provider'],()) if auth=='api_key' and row['provider'].startswith('cloudflare-') else ()
                configured=bool(stored) and stored.get('type')!='locked' and all(k in (stored.get('env_keys') or []) for k in required)
                reason='系统凭据库需要授权，请在使用模型或同步时处理' if stored and stored.get('type')=='locked' else '请补齐供应商账号和网关标识' if stored and not configured else '需要完成供应商登录' if auth=='oauth' else '需要保存供应商凭据'
                if configured and row['api']=='azure-openai-responses' and not row['baseUrl'] and not set(stored.get('env_keys') or [])&{'AZURE_OPENAI_BASE_URL','AZURE_OPENAI_RESOURCE_NAME'}:
                    configured=False;reason='请填写 Azure 接口地址或资源名称'
            output.append({**row,'credential_configured':configured,'configured':configured and row['enabled'],
                           'reason':'可选择，连接结果见测试记录' if configured and row['enabled'] else reason if row['enabled'] else '已停用'})
        return output

    @staticmethod
    def account(row):return model_authorization.account(row)

    def snapshot(self):
        config=self.read()
        config['provider_catalogs']={provider:{key:value for key,value in inventory.items() if key!='pending'} for provider,inventory in config['provider_catalogs'].items()}
        checks=self.checks()
        for row in self.rows():
            if row['key'] in checks and checks[row['key']].get('profile_sha256')!=fingerprint(row):checks[row['key']]={**checks[row['key']],'status':'stale'}
        return {**config,'models':self.public_models(),'vault':{'available':self.vault.available,'label':self.vault.label},
                'pi_version':self.pi_version,'fallback':False,'checks':checks,'running':bool(self.runtime.active),
                'gemini_broker':self.gemini.status() if any(row['auth_type']=='google_oauth' for row in self.rows()) else None}

    @property
    def pi_version(self):
        return json.loads((self.code_root/'runtime/pi/node_modules/@earendil-works/pi-ai/package.json').read_text())['version']

    def available_for_write(self):
        if self.runtime.active:raise HTTPException(409,'当前有模型执行，请待本轮结束后修改设置')

    def save(self, expected_revision, models, routes, *, provider_catalogs=None):
        with self.lock:
            self.available_for_write();current=self.read()
            if current['revision']!=expected_revision:raise HTTPException(409,'模型设置已变化，请重新读取后保存')
            if not isinstance(models,list):raise HTTPException(422,'模型列表无效')
            normalized=[self.normalize(row) for row in models];keys={row['key'] for row in normalized}
            if len(keys)!=len(normalized):raise HTTPException(422,'模型标识重复')
            if not isinstance(routes,dict) or set(routes)-({'default'}|STAGES) or any(value and value not in keys for value in routes.values()):raise HTTPException(422,'默认路由引用了未登记模型')
            if any(value and not next(row for row in normalized if row['key']==value)['enabled'] for value in routes.values()):raise HTTPException(422,'默认路由不能指向已停用模型')
            result={'revision':expected_revision+1,'models':normalized,'routes':routes}
            stored=self.runtime.config()
            for field in ('semantic_review','workflow_policy','provider_catalogs'):
                if field in stored:result[field]=stored[field]
            if provider_catalogs is not None:result['provider_catalogs']=provider_catalogs
            if self.path.exists():
                history=self.directory/'model-config-history';history.mkdir(exist_ok=True)
                old=self.path.read_bytes();target=history/f"r{expected_revision}-{hashlib.sha256(old).hexdigest()[:12]}.json"
                if not target.exists():target.write_bytes(old)
            if len(json.dumps(result,ensure_ascii=False).encode())>MAX_CONFIG_BYTES:raise HTTPException(422,'模型配置数据过大，未保存')
            self.atomic(self.path,result)
            if self.runtime.config_override is not None:self.runtime.config_override=result
            return self.snapshot()

    @staticmethod
    def atomic(path,value):
        temporary=path.with_name(path.name+'.'+str(uuid4())+'.tmp')
        try:
            fd=os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
            with os.fdopen(fd,'w',encoding='utf-8') as file:
                json.dump(value,file,ensure_ascii=False,indent=2);file.write('\n');file.flush();os.fsync(file.fileno())
            os.replace(temporary,path)
        finally:
            if temporary.exists():temporary.unlink()

    def selected(self,key):
        row=next((row for row in self.rows() if row['key']==key),None)
        if row is None:raise HTTPException(404,'未找到模型配置')
        return row

    def save_key(self,key,secret,provider_env=None):
        with self.lock:
            self.available_for_write();row=self.selected(key)
            if row['auth_type']!='api_key':raise HTTPException(422,'此模型未选择 API Key 授权')
            previous=(model_authorization.credential(self.vault,row) or {}) if provider_env is None and row['provider'] in model_authorization.ENV_FIELDS else {}
            env=model_authorization.provider_env(row['provider'],provider_env if provider_env is not None else previous.get('env',{}))
            if not isinstance(secret,str) or secret.strip() and not 8<=len(secret.strip())<=2048:raise HTTPException(422,'API Key 格式或长度不正确')
            if not secret.strip() and not model_authorization.keyless_configured(row['provider'],env):raise HTTPException(422,'请填写 API Key 或完整的云端凭据参数')
            self.vault.set(self.account(row),{'type':'api_key','key':secret.strip(),'env':env,'generation':str(uuid4())})
            self.clear_credential_checks(self.account(row))
        # Network I/O must hold neither the settings lock nor the ASGI event loop.
        return {'status':'saved','storage':self.vault.label,'sync':self.sync_result(row['provider'])}

    def remove_credential(self,key):
        with self.lock:
            self.available_for_write();row=self.selected(key)
            if row['auth_type'] not in ('api_key','oauth'):raise HTTPException(422,'此授权方式没有本项目凭据')
            if any(job['status']=='waiting' and job['account']==self.account(row) for job in self.jobs.values()):raise HTTPException(409,'请先取消当前登录')
            # Write the authoritative revocation first. Even orphaned legacy keys cannot revive.
            self.vault.set(self.account(row),{'type':'revoked','generation':str(uuid4())})
            self.clear_credential_checks(self.account(row))
            return {'status':'removed'}

    def clear_credential_checks(self,account):
        checks=self.checks()
        for row in self.rows():
            if self.account(row)==account:checks.pop(row['key'],None)
        self.atomic(self.directory/'pi-model-checks.json',checks)

    def resolve_model(self,key):
        with self.lock:
            if any(job['status']=='waiting' for job in self.jobs.values()):raise HTTPException(409,'供应商登录尚未结束，请完成或取消登录后再调用模型')
            try:row=self.selected(key)
            except HTTPException as error:
                if error.status_code==404:raise HTTPException(409,'所选模型尚未配置，不会自动改用其他模型') from None
                raise
            if not row['enabled']:raise HTTPException(409,'所选模型已停用，不会自动替换')
            return model_authorization.resolve(row,self.vault,self.command,self.gemini)


    @staticmethod
    def model_packet(row):
        return {'id':row['id'],'name':row['label'],'provider':row['provider'],'api':row['api'],'baseUrl':row['baseUrl'],
                'reasoning':any(level!='off' for level in row['thinking_levels']),'thinkingLevelMap':{level:row.get('thinking_level_map',{}).get(level,level) if level in row['thinking_levels'] else None for level in LEVELS},
                'input':row.get('input',['text']),'contextWindow':row['contextWindow'],'maxTokens':row['maxTokens'],
                **({'compat':row['compat']} if row.get('compat') else {}),
                'cost':{'input':0,'output':0,'cacheRead':0,'cacheWrite':0}}

    def command(self,packet,timeout=15,process_hook=None,event_hook=None,input_hook=None):
        return model_control.command(self.code_root,packet,timeout,process_hook,event_hook,input_hook)

    def catalog(self,reload=False):
        if reload or self.catalog_cache is None:self.catalog_cache=self.command({'operation':'catalog'})
        return {**self.catalog_cache,'providers':self.catalog_cache['providers']+[gemini_catalog()]}

    def provider_credential(self,provider):
        """Called under lock. Promote only an unambiguous legacy key, before importing models."""
        rows=[row for row in self.rows() if row['provider']==provider and row['auth_type']=='api_key']
        if not rows:return None
        shared=self.vault.get(self.account(rows[0]))
        if shared is not None:return None if shared.get('type')=='revoked' else shared
        candidates={}
        for row in rows:
            stored=self.vault.get(model_authorization.legacy_account(row))
            if stored and stored.get('type')=='api_key' and stored.get('key'):
                candidates[fingerprint({'key':stored['key'],'env':stored.get('env',{})})]=stored
        if len(candidates)>1:raise HTTPException(409,'该供应商存在多份不同的旧密钥，请重新保存要共用的密钥')
        if not candidates:return None
        shared={**next(iter(candidates.values())),'generation':str(uuid4())}
        self.vault.set(self.account(rows[0]),shared)
        self.clear_credential_checks(self.account(rows[0]))
        return shared

    def sync_result(self,provider,expected_revision=None):
        try:return self.sync_provider(provider,expected_revision)
        except HTTPException as error:
            return {'status':'failed','provider':provider,'reason':str(error.detail)[:120],'added':0}
        except Exception:return {'status':'failed','provider':provider,'reason':'云端模型列表读取失败，原模型配置保留','added':0}

    def sync_provider(self,provider,expected_revision=None,cached=False):
        entry=next((item for item in self.catalog()['providers'] if item['id']==provider),None)
        if entry is None:raise HTTPException(404,'模型目录中没有该供应商')
        if not set(entry['auth_types'])&{'api_key','oauth'}:raise HTTPException(422,'供应商未提供可用授权方式')
        with self.lock:
            self.available_for_write();current=self.read()
            if expected_revision is not None and current['revision']!=expected_revision:raise HTTPException(409,'模型设置已变化，请重新读取后同步')
            if cached:
                previous=current.get('provider_catalogs',{}).get(provider)
                if previous is None:raise HTTPException(409,'尚无已保存的供应商目录，请同步云端模型')
                packet={'operation':'models_cached','provider':provider,'models':previous.get('models',[])}
            else:
                auth_account='provider:'+provider
                credential=self.provider_credential(provider)
                if not credential:
                    auth_account='oauth:'+provider;credential=self.vault.get(auth_account)
                if not credential or credential.get('type')=='revoked':raise HTTPException(409,'请先完成供应商授权，再同步云端模型')
                stamp=fingerprint(credential)
                packet={'operation':'models','provider':provider,'credential':credential}
        result=self.command(packet,timeout=30)
        if not isinstance(result,dict) or result.get('status')!='ok':
            return {'status':'failed','provider':provider,'reason':str(result.get('reason') if isinstance(result,dict) else '云端返回无效')[:120],'added':0}
        with self.lock:
            self.available_for_write()
            if self.read()['revision']!=current['revision']:raise HTTPException(409,'同步期间配置已变化，本次结果未写入，请重新同步')
            if not cached:
                shared=self.vault.get(auth_account)
                if not shared or shared.get('type')=='revoked' or fingerprint(shared)!=stamp:raise HTTPException(409,'同步期间授权已变化，本次结果未写入')
                if result.get('credential') and result['credential']!=credential:self.vault.set(auth_account,result['credential'])
            rows=self.rows();available=result.get('models')
            if not isinstance(available,list) or len(available)>5000:raise HTTPException(409,'云端目录格式或数量不受支持')
            # Keep a complete bounded inventory, including unknown capabilities, outside executable profiles.
            inventory=[];seen=set()
            for item in available:
                if not isinstance(item,dict) or not isinstance(item.get('id'),str) or not item['id'].strip() or len(item['id'])>160:raise HTTPException(409,'云端模型标识无效')
                if item['id'] not in seen:inventory.append(item);seen.add(item['id'])
            if len(json.dumps(inventory,ensure_ascii=False).encode())>2500000:raise HTTPException(409,'云端目录超过保存上限')
            configured={row['id'] for row in rows if row['provider']==provider};keys={row['key'] for row in rows}
            added=[];updated=0;skipped=0
            for item in inventory:
                model_id=item['id']
                if model_id in configured:
                    skipped+=1
                    for row in rows:
                        if row['provider']!=provider or row['id']!=model_id or item.get('catalog') is not True:continue
                        if row.get('source') in ('pi_builtin','provider_sync'):
                            # Refresh native metadata, preserving user choices and custom profiles.
                            native=self.candidate(provider,model_id,item,set())
                            if native is None:raise HTTPException(409,'Pi 模型定义无法加载，本次同步未写入')
                            candidate={**row,**{key:native[key] for key in ('api','baseUrl','contextWindow','thinking_levels','thinking_level_map','input')}}
                            candidate['compat']=native.get('compat',{})
                            if candidate['reasoning_effort'] not in native['thinking_levels']:candidate['reasoning_effort']=native['reasoning_effort']
                            candidate=self.normalize(candidate)
                            if candidate!=row:row.update(candidate);updated+=1
                        elif not row.get('compat') and item.get('compat'):
                            candidate=self.normalize({**row,'compat':item['compat']})
                            row.update(candidate);updated+=1
                    continue
                mode=credential['type'] if not cached else next((r['auth_type'] for r in rows if r['provider']==provider),'api_key')
                candidate=self.candidate(provider,model_id,item,keys,mode)
                if candidate is None:raise HTTPException(409,'供应商返回的模型定义无法加载，本次同步未写入')
                added.append(candidate);keys.add(candidate['key']);configured.add(model_id)
            state={'source':str(result.get('source',''))[:40],'endpoint':str(result.get('endpoint',''))[:400],
                   'models':inventory,'listed':len(inventory)}
            catalogs={**current.get('provider_catalogs',{}),provider:state}
            changed=bool(added or updated or catalogs!=current.get('provider_catalogs',{}))
            if changed:self.save(current['revision'],rows+added,current['routes'],provider_catalogs=catalogs)
            return {'status':'synced' if changed else 'unchanged','provider':provider,
                    'source':state['source'],'endpoint':state['endpoint'],'listed':len(inventory),'added':len(added),'updated':updated,
                    'skipped':skipped,'models':[row['label'] for row in added][:20]}

    @staticmethod
    def candidate(provider,model_id,item,keys,auth_type='api_key'):
        try:
            levels=item['thinking_levels']
            context=int(item['contextWindow'])
            maximum=int(item['maxTokens'])
            key=(re.sub(r'[^a-zA-Z0-9_-]','-',provider+'-'+model_id).strip('-')[:72] or 'model');base=key;suffix=2
            while key in keys:key=base+'-'+str(suffix);suffix+=1
            return ModelSettings.normalize({'key':key,'label':item.get('label',model_id),'provider':provider,'id':model_id,
                'api':item['api'],'baseUrl':item['baseUrl'],'api_key_env':'','auth_type':'oauth' if provider=='openai-codex' else auth_type,
                'enabled':True,'visible':True,'contextWindow':context,'maxTokens':maximum,
                'reasoning_effort':'medium' if 'medium' in levels else levels[0],
                'thinking_levels':levels,'thinking_level_map':item.get('thinking_level_map',{}),'source':'provider_sync','input':item.get('input',['text']),'compat':item.get('compat',{})})
        except (HTTPException,KeyError,ValueError,TypeError,IndexError):return None

    def connect_gemini(self,expected_revision):
        with self.lock:
            self.available_for_write();current=self.read()
            if current['revision']!=expected_revision:raise HTTPException(409,'模型设置已变化，请重新读取后连接')
            models=self.rows();ids={row['id'] for row in models if row['auth_type']=='google_oauth'};keys={row['key'] for row in models}
            for row in gemini_profiles():
                if row['id'] in ids:continue
                if row['key'] in keys:row['key']+='-'+uuid4().hex[:8]
                models.append(row)
            self.gemini.status(refresh=True)
            return self.save(expected_revision,models,current['routes'])

    def begin_login(self,key):
        return self.logins.begin(key)

    def login_status(self,identity):
        return self.logins.status(identity)

    def cancel_login(self,identity):
        return self.logins.cancel(identity)

    def checks(self):
        path=self.directory/'pi-model-checks.json'
        if not path.exists():return {}
        try:return json.loads(path.read_text())
        except ValueError:return {}

    def probe(self,key):
        row=self.resolve_model(key);start=time.time()
        packet={'model':self.model_packet(row),'apiKey':row['apiKey'],'headers':row['private_headers'],'providerEnv':row.get('private_env',{}),'reasoning_effort':row['reasoning_effort'],'maxTokens':256,
                'system':'This is a connection test. Reply only PI_CONNECTION_OK. Do not use tools.','prompt':'Reply PI_CONNECTION_OK.','session_id':str(uuid4()),'history':[],'tools':[]}
        try:
            result=self.probe_runner(packet) if self.probe_runner else self.command({'operation':'probe','packet':packet},timeout=120)
            if result.get('status')!='passed' or result.get('model')!=row['id'] or result.get('reasoning_effort')!=row['reasoning_effort']:raise HTTPException(409,'模型或推理档位与连接回执不一致')
            result={k:v for k,v in result.items() if k in ('status','model','provider','reasoning_effort','scope')}
        except Exception:result={'status':'failed','model':row['id'],'reasoning_effort':row['reasoning_effort'],'message':'未获得所选模型和档位的完整回执，请检查授权、网络与模型 ID。'}
        result.update(at=time.time(),seconds=round(time.time()-start,2),profile_sha256=fingerprint({k:v for k,v in row.items() if k not in ('apiKey','private_headers','private_env','configured')}))
        with self.lock:
            checks=self.checks();checks[key]=result;self.atomic(self.directory/'pi-model-checks.json',checks)
        return result

    def close(self):
        self.logins.close()
