"""Pi provider OAuth jobs: cancellable interactive login, credentials in the vault."""
import threading
import time
from uuid import uuid4
from fastapi import HTTPException
from .model_contract import supports_oauth


class LoginJobs:
    """Owns the login registry for one ModelSettings host."""

    def __init__(self,settings):
        self.settings=settings
        self.jobs={}

    def begin(self,key=None,provider=None):
        settings=self.settings
        with settings.lock:
            settings.available_for_write();row=settings.selected(key) if key else {'provider':provider,'auth_type':'oauth'}
            if row['auth_type']!='oauth' or not supports_oauth(row['provider']):raise HTTPException(422,'此模型未选择供应商账号登录')
            if not settings.vault.available:raise HTTPException(409,'安全凭据库尚不可用')
            if any(job['status']=='waiting' for job in self.jobs.values()):raise HTTPException(409,'已有登录进行中，请完成或取消后重试')
            identity=str(uuid4());job={'id':identity,'model_key':key,'provider':row['provider'],'account':settings.account(row),'status':'waiting','created':time.time(),'expires_at':time.time()+600,'process':None,'cancelled':False}
            self.jobs[identity]=job
            def attach(process):
                with settings.lock:
                    job['process']=process
                    if job['cancelled']:process.terminate()
            def run():
                try:
                    result=settings.command({'operation':'login','provider':row['provider']},timeout=600,process_hook=attach,event_hook=lambda e:self.event(identity,e),input_hook=lambda send:job.update(send=send))
                    with settings.lock:
                        if job['cancelled']:return
                        current=settings.selected(key) if key else row
                        if current['auth_type']!='oauth' or current['provider']!=row['provider']:raise HTTPException(409,'登录期间配置已变化，请重新登录')
                        settings.vault.set(job['account'],result['credential']);settings.clear_credential_checks(job['account']);job.update(status='completed')
                except Exception:
                    job.update(status='cancelled' if job['cancelled'] else 'failed',message='登录未完成。请检查网络、账户授权和系统凭据库后重试。')
                finally:
                    for field in ('user_code','url','prompt','prompt_id','send'):job.pop(field,None)
                    job['process']=None
            thread=threading.Thread(target=run,daemon=True,name='disclosure-model-login');job['thread']=thread;thread.start()
            return self.status(identity)

    def status(self,identity):
        job=self.jobs.get(identity)
        if not job:raise HTTPException(404,'登录会话已结束，请重新发起')
        return {key:value for key,value in job.items() if key in ('id','model_key','provider','status','created','expires_at','user_code','url','message','prompt','prompt_id')}

    def event(self,identity,event):
        with self.settings.lock:
            job=self.jobs[identity]
            if job['status']!='waiting':return
            if event.get('type')=='auth_prompt':job.update(prompt=event['prompt'],prompt_id=event['id'])
            elif event.get('type')=='auth_prompt_cancelled':
                if job.get('prompt_id')==event['id']:job.pop('prompt',None);job.pop('prompt_id',None)
            elif event.get('url'):
                from urllib.parse import urlsplit
                if urlsplit(event['url']).scheme!='https':return
                job.update(url=event['url'])
                if event.get('user_code'):job.update(user_code=event['user_code'])

    def answer(self,identity,prompt_id,value):
        with self.settings.lock:
            job=self.jobs.get(identity)
            if not job or job['status']!='waiting' or job.get('prompt_id')!=prompt_id or not job.get('send'):raise HTTPException(409,'登录步骤已变化，请重新读取')
            prompt=job['prompt']
            if not isinstance(value,str) or not value or len(value)>16384:raise HTTPException(422,'请输入本步骤所需内容')
            if prompt['type']=='select' and value not in {item['id'] for item in prompt['options']}:raise HTTPException(422,'登录选项无效')
            try:job['send']({'type':'auth_response','id':prompt_id,'value':value})
            except (OSError,ValueError):raise HTTPException(409,'登录连接已结束，请重新发起登录') from None
            job.pop('prompt',None);job.pop('prompt_id',None)
            return self.status(identity)

    def cancel(self,identity):
        with self.settings.lock:
            job=self.jobs.get(identity)
            if not job:raise HTTPException(404,'登录会话不存在')
            if job['status']=='waiting':
                job['cancelled']=True;job['status']='cancelled'
                if job.get('process') and job['process'].poll() is None:job['process'].terminate()
            return self.status(identity)

    def close(self):
        for identity,job in list(self.jobs.items()):
            if job['status']=='waiting':self.cancel(identity)
        for job in self.jobs.values():
            if job.get('thread'):job['thread'].join(timeout=4)
