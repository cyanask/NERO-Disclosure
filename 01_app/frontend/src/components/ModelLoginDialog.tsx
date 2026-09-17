import {useEffect,useState} from 'react';
import {Alert,Button,Input,Modal,Select,Spin} from 'antd';
import type {LoginJob} from '../modelSettings';

export default function ModelLoginDialog({login,busy,error,onClose,onCancel,onAnswer}:{login?:LoginJob;busy:boolean;error?:string;onClose:()=>void;onCancel:()=>unknown;onAnswer:(value:string)=>unknown}){
 const [value,setValue]=useState('');
 useEffect(()=>setValue(''),[login?.prompt_id,login?.status]);
 const waiting=login?.status==='waiting',prompt=login?.prompt;
 return <Modal className="model-settings-dialog" title="使用 Pi 登录供应商账号" open={!!login} maskClosable={false} keyboard={!waiting} closable={!waiting} onCancel={onClose}
  footer={<Button onClick={()=>waiting?onCancel():onClose()}>{waiting?'取消登录':'关闭'}</Button>}>
  {error&&<Alert type="error" message={error}/>}
  {waiting?<div className="model-device-login">
   {login.url&&<><p>请使用自己的账号完成供应商授权。</p><a href={login.url} target="_blank" rel="noreferrer">打开供应商授权页 ↗</a></>}
   {login.user_code&&<><p>设备码仅用于本次授权：</p><strong>{login.user_code}</strong></>}
   {prompt&&<div><p>{prompt.message}</p>{prompt.type==='select'?<Select aria-label="登录选项" style={{width:'100%'}} value={value||undefined} onChange={setValue} options={prompt.options?.map(item=>({value:item.id,label:item.label}))}/>:
    <Input.Password aria-label="登录回复" autoComplete="off" visibilityToggle={false} value={value} placeholder={prompt.placeholder} onChange={e=>setValue(e.target.value)} onPressEnter={()=>value&&!busy&&onAnswer(value)}/>}
    <Button disabled={!value||busy} loading={busy} onClick={()=>onAnswer(value)}>继续授权</Button></div>}
   {!prompt&&!login.url&&!login.user_code&&<Spin tip="正在准备供应商授权"/>}
  </div>:login?.status==='completed'?<Alert type="success" message="授权已保存，可以测试模型连接"/>:<Alert type="warning" message={login?.message||'登录已取消'}/>}
 </Modal>;
}
