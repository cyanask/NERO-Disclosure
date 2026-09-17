"""Resolve only the explicitly selected model; credentials remain in its vault."""
import os
from fastapi import HTTPException
from .model_contract import ENV_FIELDS


def account(row):
    """One credential per provider: every model of a provider shares the authorized key."""
    return 'oauth:'+row['provider'] if row['auth_type']=='oauth' else 'provider:'+row['provider']


def legacy_account(row):
    """Earlier builds stored one API Key per model; read-only fallback for upgrades."""
    return 'model:'+row['key']


def credential(vault,row):
    shared=vault.get(account(row))
    # A revocation marker also blocks orphaned legacy records after a restart.
    if shared is not None:return None if shared.get('type')=='revoked' else shared
    return vault.get(legacy_account(row)) if row['auth_type']=='api_key' else None


def credential_status(vault,row,cache):
    """Metadata-only status path, distinct from explicit execution/authorization reads."""
    def read(name):
        if name not in cache:cache[name]=vault.status(name)
        return cache[name]
    shared=read(account(row))
    if shared is not None:return None if shared.get('type')=='revoked' else shared
    return read(legacy_account(row)) if row['auth_type']=='api_key' else None


def provider_env(provider,value):
    import re
    from pathlib import Path
    from urllib.parse import urlsplit
    allowed=ENV_FIELDS.get(provider,())
    if not isinstance(value,dict) or set(value)-set(allowed):raise HTTPException(422,'供应商参数不受支持')
    result={}
    for name,item in value.items():
        if not isinstance(item,str) or len(item)>8192 or any(ord(c)<32 for c in item):raise HTTPException(422,'供应商参数格式不正确')
        item=item.strip()
        if not item:continue
        if name=='AZURE_OPENAI_BASE_URL':
            url=urlsplit(item)
            if url.scheme!='https' or not url.hostname or url.username or url.password or url.query or url.fragment:raise HTTPException(422,'Azure 接口地址须为不含凭据的 HTTPS 地址')
        elif name=='GOOGLE_APPLICATION_CREDENTIALS':
            path=Path(item).expanduser()
            if not path.is_absolute() or not path.is_file():raise HTTPException(422,'请填写现有 Google 凭据文件的绝对路径')
            item=str(path.resolve())
        elif name=='AZURE_OPENAI_DEPLOYMENT_NAME_MAP':
            if any(part.count('=')!=1 or not all(side.strip() for side in part.split('=')) for part in item.split(',')):raise HTTPException(422,'Azure 部署映射请使用“模型 ID=部署名”，多项以逗号分隔')
        elif name=='AZURE_OPENAI_RESOURCE_NAME' or provider.startswith('cloudflare-'):
            if not re.fullmatch(r'[A-Za-z0-9_-]{1,128}',item):raise HTTPException(422,'供应商资源标识格式不正确')
        elif name not in ('AWS_SECRET_ACCESS_KEY','AWS_SESSION_TOKEN','AWS_PROFILE') and not re.fullmatch(r'[A-Za-z0-9_.:-]{1,256}',item):raise HTTPException(422,'供应商参数格式不正确')
        result[name]=item
    if provider.startswith('cloudflare-') and any(not result.get(k) for k in allowed):raise HTTPException(422,'请补齐供应商账号和网关标识')
    return result


def keyless_configured(provider,env):
    if provider=='amazon-bedrock':return bool(env.get('AWS_PROFILE') or env.get('AWS_ACCESS_KEY_ID') and env.get('AWS_SECRET_ACCESS_KEY'))
    if provider=='google-vertex':return all(env.get(k) for k in ('GOOGLE_CLOUD_PROJECT','GOOGLE_CLOUD_LOCATION','GOOGLE_APPLICATION_CREDENTIALS'))
    return False


def resolve(row,vault,command,gemini):
    if row['auth_type']=='google_oauth':return gemini.resolve(row)
    auth=row['auth_type'];headers={};env={};native_resolved=False
    if auth=='environment':secret=os.environ.get(row['api_key_env'],'')
    elif auth=='local':secret='disclosure-local'
    else:
        stored=credential(vault,row)
        if not stored:raise HTTPException(409,'所选模型尚未授权，请在模型设置中完成授权')
        result=command({'operation':'resolve','provider':row['provider'],'model':row,'credential':stored},timeout=40)
        if result.get('credential') and result['credential']!=stored:vault.set(account(row),result['credential'])
        resolved=result.get('auth',{})
        native_resolved='auth' in result
        # Header-only auth still needs the original key for redaction, not logging.
        secret=resolved.get('apiKey') or (stored.get('key','') if resolved.get('headers') else '')
        headers=resolved.get('headers',{});env=result.get('env',{})
        if resolved.get('baseUrl'):row={**row,'baseUrl':resolved['baseUrl']}
    if not secret and not native_resolved:raise HTTPException(409,'所选模型尚未配置，不会自动改用其他模型')
    if row['api']=='azure-openai-responses' and not row['baseUrl'] and not (env.get('AZURE_OPENAI_BASE_URL') or env.get('AZURE_OPENAI_RESOURCE_NAME')):raise HTTPException(409,'请先填写 Azure 接口地址或资源名称')
    return {**row,'configured':True,'apiKey':secret,'private_headers':headers,'private_env':env}
