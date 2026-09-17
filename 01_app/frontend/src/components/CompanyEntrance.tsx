import {useEffect,useRef,useState} from 'react';
import {Alert,Button,Input,Select,Spin} from 'antd';
import {ArrowRightOutlined,StopOutlined} from '@ant-design/icons';
import {api,requestId} from '../api';
import type {PiRun} from '../chat';
import {live,runLabels} from '../chat';
import type {Company,CompanyResult,CompanyWorkspace} from '../companyWorkspace';
import './CompanyEntrance.css';

type LookupRun=PiRun&{company_lookup?:{company_name:string;stock_code:string};company_result?:CompanyResult};
const lookupKey='nero-disclosure:company-lookup';
const savedLookup=()=>{try{return window.localStorage.getItem(lookupKey)||'';}catch{return '';}};
export default function CompanyEntrance({workspace,onEnter,onSettings,onReturn}:{workspace:CompanyWorkspace;onEnter:(company:Company)=>void;onSettings:()=>void;onReturn?:()=>void}){
 const [name,setName]=useState(''),[code,setCode]=useState(''),[runId,setRunId]=useState(savedLookup);
 const [run,setRun]=useState<LookupRun>(),[error,setError]=useState(''),[busy,setBusy]=useState(false),[retry,setRetry]=useState(0);
 const [existing,setExisting]=useState<string>();const registering=useRef(false),mounted=useRef(true);
 useEffect(()=>{mounted.current=true;return()=>{mounted.current=false;};},[]);
 const rememberLookup=(id:string)=>{setRunId(id);try{if(id)window.localStorage.setItem(lookupKey,id);else window.localStorage.removeItem(lookupKey);}catch{/* Current-page status remains available. */}};
 useEffect(()=>{
  if(!runId)return;let active=true,timer:ReturnType<typeof setTimeout>;
  const read=async()=>{try{
   const data=await api<{run:LookupRun}>(`/chat/runs/${encodeURIComponent(runId)}`);if(!active)return;
   if(data.run.stage!=='company_lookup')throw new Error('保存的记录不属于公司核实，请重新发起。');
   if(workspace.companies.some(c=>c.verification?.run_id===runId)){rememberLookup('');setRun(undefined);return;}
   setRun(data.run);if(data.run.company_lookup){setName(data.run.company_lookup.company_name);setCode(data.run.company_lookup.stock_code);}
   if(live(data.run)){timer=setTimeout(read,1500);return;}
   if(data.run.status==='completed'&&data.run.company_result?.status==='verified'&&data.run.company_result.available&&!registering.current){
    registering.current=true;setBusy(true);
    try{const company=await api<Company>('/company-workspace/register','POST',{run_id:runId});if(active){rememberLookup('');onEnter(company);}}
    finally{registering.current=false;if(active)setBusy(false);}
   }
  }catch(e){if(active)setError((e as Error).message);}
  };void read();return()=>{active=false;clearTimeout(timer);};
 },[runId,retry]);
 const pending=busy||live(run);
 const start=async()=>{
  if(pending)return;setBusy(true);setError('');setRun(undefined);rememberLookup('');
  try{const next=await api<LookupRun>('/company-workspace/lookup','POST',{company_name:name.trim(),stock_code:code.trim(),request_id:requestId()});if(mounted.current){setRun(next);rememberLookup(next.id);}}
  catch(e){if(mounted.current)setError((e as Error).message);}finally{if(mounted.current)setBusy(false);}
 };
 const select=async()=>{const company=workspace.companies.find(c=>`${c.board}:${c.stock_code}`===existing);if(!company)return;setBusy(true);setError('');try{onEnter(await api<Company>('/company-workspace/select','POST',{board:company.board,stock_code:company.stock_code}));}catch(e){setError((e as Error).message);}finally{setBusy(false);}};
 const result=run?.company_result;
 return <div className="company-entrance">
  <header className="company-entry-header"><div className="product-name"><img className="personal-mark" src="/disclosure-window-sidebar.svg" alt="披露之窗"/><span className="brand-two-lines"><span>信息披露</span><span className="second">AI 辅助系统</span></span></div><Button type="text" onClick={onSettings}>模型设置</Button></header>
  <main className="company-entry-main">
   <div className="company-entry-copy"><p className="eyebrow">COMPANY WORKSPACE</p><h1>从本公司开始</h1><p>填写公司全称和证券代码，系统联网核实所属板块后，登记并进入工作台。</p><p>已登记的公司，下次直接进入。</p><div className="company-entry-libraries"><span>法规与案例 · 适用板块</span><span>模板 · 通用与本公司专用</span><span>历史公告 · 本公司</span></div></div>
   <section className="company-entry-form" aria-label="公司登记">
    {workspace.companies.length>0&&<div className="registered-company"><label>已登记公司</label><Select aria-label="选择已登记公司" value={existing} placeholder="选择已有公司" onChange={setExisting} options={workspace.companies.map(c=>({value:`${c.board}:${c.stock_code}`,label:`${c.company_name} · ${c.stock_code}`}))} disabled={pending}/><Button onClick={select} disabled={!existing||pending}>进入工作台</Button><div className="company-entry-divider">登记其他公司</div></div>}
    <form onSubmit={e=>{e.preventDefault();void start();}}>
     <label htmlFor="company-name">公司全称</label><Input id="company-name" aria-label="公司全称" value={name} onChange={e=>setName(e.target.value)} disabled={pending} placeholder="请输入上市公司或挂牌公司全称" maxLength={150} autoComplete="organization"/>
     <label htmlFor="company-code">证券代码</label><Input id="company-code" aria-label="证券代码" value={code} onChange={e=>setCode(e.target.value.replace(/\D/g,''))} disabled={pending} placeholder="六位证券代码" maxLength={6} inputMode="numeric"/>
     <p className="company-entry-hint">根据官方公开资料识别，无需手动选择交易所或板块。当前工作台已接入创业板。</p>
     <Button type="primary" size="large" htmlType="submit" loading={pending} disabled={pending||name.trim().length<2||!/^\d{6}$/.test(code)} icon={<ArrowRightOutlined/>}>联网核实并登记</Button>
    </form>
    {error&&<Alert type="error" showIcon message={error} action={runId?<Button size="small" onClick={()=>{setError('');setRetry(n=>n+1);}}>重新读取</Button>:undefined}/>}
    {run&&<div className="company-lookup-status" role="status">
     <strong>{live(run)?<><Spin size="small"/> 正在核实公司信息</>:runLabels[run.status]||run.status}</strong>
     <p>{result?.reason||run.reason}</p>
     {result?.status==='verified'&&<p>识别板块：<b>{result.board_name}</b>{!result.available&&'。该板块工作台尚未接入，本次未登记；核实依据已保留。'}</p>}
     {!!result?.sources.length&&<details><summary>查看官方依据</summary>{result.sources.map((source,index)=><p key={`${source.download_id}-${index}`}><a href={source.url} target="_blank" rel="noreferrer">官方来源 · 第 {source.page} 页</a><span className="company-source-quote">{source.quote}</span></p>)}</details>}
     {live(run)&&<Button icon={<StopOutlined/>} onClick={async()=>{try{setRun(await api<LookupRun>(`/chat/runs/${run.id}/cancel`,'POST',{}));}catch(e){setError((e as Error).message);}}}>停止核实</Button>}
    </div>}
    {onReturn&&<Button type="text" disabled={pending} onClick={onReturn}>返回本公司工作台</Button>}
   </section>
  </main><footer className="company-entry-footer">信息有据 · 披露有序</footer>
 </div>;
}
