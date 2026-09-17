"""Reuse NERO Banker's existing Google authorization and Pi Responses transport.

Reference: Banker pi_profile_contracts.py and provider_adapters.mjs.
Only public model IDs are read. OAuth credentials remain owned by OpenCodex.
"""
import json
import threading
import time
import urllib.request
from fastapi import HTTPException

PROVIDER='nero-opencodex-loopback'
BASE_URL='http://127.0.0.1:10100/v1'
MODEL_IDS=('google-antigravity/gemini-3.8-flash','google-antigravity/gemini-3.7-flash')


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None


def profiles():
    return [{'key':'gemini-'+version.replace('.','-')+'-flash','label':'Gemini '+version+' Flash',
        'id':'google-antigravity/gemini-'+version+'-flash','provider':PROVIDER,'api':'openai-responses',
        'baseUrl':BASE_URL,'auth_type':'google_oauth','api_key_env':'','contextWindow':1048576,'maxTokens':32768,
        'thinking_levels':['low','high'],'reasoning_effort':'high','thinking_level_map':{'low':'low','high':'high'},
        'visible':True,'enabled':True,'source':'banker_google_auth'} for version in ('3.8','3.7')]


def provider_catalog():
    return {'id':PROVIDER,'name':'Google / agy 账号授权','baseUrl':BASE_URL,'auth_types':['google_oauth'],
        'dynamic':False,'models':[{**{k:row[k] for k in ('id','label','api','baseUrl','contextWindow','maxTokens','thinking_levels','thinking_level_map')},
                                  'reasoning':True,'input':['text']} for row in profiles()]}


class GeminiBroker:
    def __init__(self):
        self.cached=None;self.checked=0.;self.lock=threading.Lock()

    def model_ids(self):
        # Fixed loopback endpoint, with no proxy, redirect or authorization export.
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
        request=urllib.request.Request(BASE_URL+'/models',headers={'Accept':'application/json'},method='GET')
        # The local broker may cold-load its provider catalog on the first request.
        # Keep a bounded check without making users resend a failed business round.
        with opener.open(request,timeout=5) as response:body=response.read(1000001)
        if len(body)>1000000:raise ValueError('oversized catalog')
        data=json.loads(body)
        if not isinstance(data,dict) or not isinstance(data.get('data'),list):raise ValueError('invalid catalog')
        return sorted({row['id'] for row in data['data'] if isinstance(row,dict) and isinstance(row.get('id'),str)
            and row['id'].startswith('google-antigravity/gemini-')})

    def status(self,refresh=False):
        with self.lock:
            if not refresh and self.cached is not None and time.monotonic()-self.checked<10:return self.cached
            try:
                self.cached={'status':'delegated_unverified','model_ids':self.model_ids(),
                    'message':'复用 Banker 的 Google 授权；连接效果以模型测试为准'}
            except (OSError,ValueError,TypeError):
                self.cached={'status':'unavailable','model_ids':[],
                    'message':'请启动 Banker 共用的 OpenCodex 服务，再检查连接'}
            self.checked=time.monotonic()
            return self.cached

    def resolve(self,row):
        if row['id'] not in self.status(refresh=True)['model_ids']:
            raise HTTPException(409,'Banker 共用的 Gemini 通道未就绪，或目录中没有所选模型；不会自动改用其他模型')
        # This is Banker's non-secret local placeholder, not a Google credential.
        return {**row,'configured':True,'apiKey':'nero-opencodex-local','private_headers':{}}
