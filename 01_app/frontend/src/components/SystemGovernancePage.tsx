import {useEffect,useState} from 'react';
import type {ReactNode} from 'react';
import PiRunAudit from './PiRunAudit';
import VersionPanel from './governance/VersionPanel';
import {useVersionChecks} from './governance/useVersionChecks';
import type {Version,Verify} from './governance/versionTypes';
import {size,stamp,liveBatch as live} from './governance/display';
import type {Laws,Model,Backup,Action,Quarantine,Inventory,Preview,Batch,Health,Finding} from './governance/types';
import LawPanel from './governance/LawPanel';
import HealthPanel from './governance/HealthPanel';
import {DatabasePanel,CachePanel} from './governance/StoragePanels';
import {Alert,Button,Checkbox,Modal,Space,Table,Tabs} from 'antd';
import {api,requestId} from '../api';
import type {Board} from '../companyWorkspace';

type Saved={laws?:Laws;models?:Model[];modelKey?:string;inventory?:Inventory;batch?:Batch;health?:Health;version?:Version;verify?:Verify};
const saved:Record<string,Saved>={};

export default function SystemGovernancePage({board,companyCode='',eventRecords,activeTab:tab,onTabChange:setTab,onOpenSession,onOpenRuns,onOpenEvent}:{board:Board;companyCode?:string;eventRecords?:ReactNode;activeTab:string;onTabChange:(tab:string)=>void;onOpenSession:(sid:string)=>void;onOpenRuns:()=>void;onOpenEvent:(id:string)=>void}){
 const key=board.layer||'';
 try{if(!saved[key])saved[key]=JSON.parse(window.localStorage.getItem('nero:governance:'+key)||'{}');}catch{/* no prior view */}
 const initial=saved[key]||{};
 const [laws,setLaws]=useState(initial.laws);const [models,setModels]=useState(initial.models||[]);
 const [modelKey,setModelKey]=useState(initial.modelKey||'');const [inventory,setInventory]=useState(initial.inventory);
 const [batch,setBatch]=useState(initial.batch);const [watch,setWatch]=useState(false);const [busy,setBusy]=useState(false);
 const [error,setError]=useState('');const [notice,setNotice]=useState('');const [preview,setPreview]=useState<Preview>();const [confirmed,setConfirmed]=useState(false);
 const [health,setHealth]=useState(initial.health);
 const versionControl=useVersionChecks(initial,tab==='version');
 const {version,verify}=versionControl;
 const [quarantineAction,setQuarantineAction]=useState<{item:Quarantine;action:'restore'|'purge'}>();
 // Retain prior scan results; version-tab entry reconnects to existing progress only.
 useEffect(()=>{saved[key]={laws,models,modelKey,inventory,batch,health,version,verify};try{window.localStorage.setItem('nero:governance:'+key,JSON.stringify(saved[key]));}catch{/* quota is optional */}},[key,laws,models,modelKey,inventory,batch,health,version,verify]);
 const refreshLaws=async()=>{
  const [data,caps,current]=await Promise.all([api<Laws>(`/law-lifecycle?board=${key}`),api<{models:Model[];routes:Record<string,string>}>('/chat/models'),api<Batch|null>(`/governance/laws/current?board=${key}`)]);
  setBatch(current||undefined);setWatch(live(current||undefined));
  setLaws(data);const options=caps.models.filter(m=>m.configured&&m.enabled&&m.visible!==false);setModels(options);
  setModelKey(previous=>options.some(m=>m.key===previous)?previous:options.find(m=>m.key===caps.routes.default)?.key||options[0]?.key||'');
 };
 const scan=async()=>{setInventory(await api<Inventory>('/governance/scan','POST',{}));};
 const act=async(fn:()=>Promise<void>)=>{setBusy(true);setError('');setNotice('');try{await fn();}catch(e){setError((e as Error).message);}finally{setBusy(false);}};
 useEffect(()=>{
  if(!watch||!batch)return;let cancelled=false;let timer:number;
  const poll=async()=>{try{
    const value=await api<Batch>(`/governance/laws/runs/${batch.batch_id}`);if(cancelled)return;setBatch(value);
    if(live(value)){timer=window.setTimeout(poll,2500);}else{setWatch(false);await refreshLaws();}
   }catch(e){if(!cancelled){setError((e as Error).message);setWatch(false);}}};
  void poll();return()=>{cancelled=true;window.clearTimeout(timer);};
  // Polling is enabled only after a user starts or explicitly reconnects a batch.
 },[watch,batch?.batch_id]);
 const start=async(ids?:string[])=>{
  if(!modelKey)throw new Error('请先刷新清单并选择核验模型');
  const result=await api<Batch>('/governance/laws/runs','POST',{board:key,model_key:modelKey,request_id:requestId(),instrument_ids:ids});
  setBatch(result);setWatch(true);
 };
 const prepare=async(category:string,ids:string[])=>{setPreview(await api<Preview>('/governance/cleanup-preview','POST',{category,ids}));setConfirmed(false);};
 const cleanup=async()=>{
  if(!preview||!confirmed)return;
  const result=await api<Action & {quarantined_bytes?:number;errors:{reason:string}[]}>('/governance/cleanup','POST',{preview_id:preview.id,confirmed:true});
  setPreview(undefined);await scan();setNotice(`${result.quarantined_bytes?`已将 ${result.count} 个副本移入隔离区，占用 ${size(result.quarantined_bytes)}，可在下方恢复或永久清理`:`已清理 ${result.count} 个文件，释放 ${size(result.released_bytes)}`}。${result.errors.length?'部分文件未处理：'+result.errors.map(e=>e.reason).join('；'):''}`);
 };
 const handleQuarantine=async()=>{
  if(!quarantineAction||!confirmed)return;
  const result=await api<Action & {errors?:{reason:string}[]}>(`/governance/cleanup/${quarantineAction.action}`,'POST',{preview_id:quarantineAction.item.id,confirmed:true});
  setNotice(result.errors?.length?result.errors.map(e=>e.reason).join('；'):quarantineAction.action==='restore'?`已恢复 ${result.count} 个副本`:`已永久清理 ${result.count} 个副本，释放 ${size(result.released_bytes)}`);
  setQuarantineAction(undefined);await scan();
 };
 const scanHealth=async()=>{setHealth(await api<Health>('/governance/health/scan','POST',{}));};
 // Recovery reuses the existing audited entries: the execution cancel and the node-task finish.
 const stopRun=async(runId:string)=>{await api(`/chat/runs/${runId}/cancel`,'POST',{});setNotice('已请求停止该轮执行；已发生的动作保留在执行记录中。');await scanHealth();};
 const stale=inventory&&(Date.now()-Date.parse(inventory.scanned_at))>7*86400000;
 const header=<div className="page-heading gov-heading"><div><span className="page-kicker">SYSTEM GOVERNANCE</span><h1>系统治理</h1>
  <p className="muted">手动检查法规、运行状态、存储空间与版本。异常可进入对应执行记录处理，文件清理前核对具体清单。</p></div></div>;
 // Findings point at the existing entries; business blockers stay in the workflow.
 const findingAction=(finding:Finding)=>{
  if(finding.action==='open_session'){const row=health?.runs.rows.find(r=>finding.ids?.includes(r.run_id));return <Button size="small" disabled={!row} onClick={()=>{if(row)onOpenSession(row.session_id);}}>打开会话</Button>;}
  if(finding.action==='open_runs'||finding.action==='cancel_task')return <Button size="small" onClick={onOpenRuns}>前往执行记录</Button>;
  if(finding.action==='databases')return <Button size="small" onClick={()=>setTab('databases')}>查看数据库副本</Button>;
  if(finding.action==='caches')return <Button size="small" onClick={()=>setTab('caches')}>查看缓存与空间</Button>;
  if(finding.action==='version')return <Button size="small" onClick={()=>setTab('version')}>查看版本与变更</Button>;
  return undefined;
 };

return <section className="resource-page governance-page">{header}
  {error&&<Alert type="error" closable onClose={()=>setError('')} message={error}/>}{notice&&<Alert type="info" closable onClose={()=>setNotice('')} message={notice}/>}
 <Tabs activeKey={tab} onChange={setTab} items={[{key:'records',label:'技术记录',children:<PiRunAudit board={board.layer} companyCode={companyCode}/>},{key:'events',label:'事项办理记录',children:eventRecords},{key:'laws',label:'法规有效性',children:<LawPanel laws={laws} models={models} modelKey={modelKey} batch={batch} busy={busy} onModel={setModelKey} onRefresh={()=>void act(refreshLaws)} onStart={ids=>void act(()=>start(ids))} onCancel={()=>void act(async()=>{if(batch){setBatch(await api<Batch>(`/governance/laws/runs/${batch.batch_id}/cancel`,'POST',{}));setWatch(true);}})} onOpenSession={onOpenSession}/>},{key:'health',label:'运行健康与恢复',children:<HealthPanel health={health} busy={busy} onScan={()=>void act(scanHealth)} onStop={id=>void act(()=>stopRun(id))} findingAction={findingAction} onOpenSession={onOpenSession} onOpenEvent={onOpenEvent}/>},{key:'databases',label:'数据库副本',children:<DatabasePanel inventory={inventory} busy={busy} onScan={()=>void act(scan)} onPrepare={(category,ids)=>void act(()=>prepare(category,ids))} onQuarantine={(item,action)=>{setConfirmed(false);setQuarantineAction({item,action});}}/>},{key:'caches',label:'缓存与空间',children:<CachePanel inventory={inventory} busy={busy} onScan={()=>void act(scan)} onPrepare={(category,ids)=>void act(()=>prepare(category,ids))} onQuarantine={(item,action)=>{setConfirmed(false);setQuarantineAction({item,action});}}/>},{key:'version',label:'版本与变更',children:<VersionPanel control={versionControl} visible={tab==='version'} busy={busy} act={act} setNotice={setNotice} setError={setError}/>}]}/>
  {['databases','caches'].includes(tab)&&<p className="gov-policy">{inventory?.notice||'清理范围仅限本项目已识别的历史副本及可重建缓存。'} 建议每 7 天手动检查一次。{stale?' 距上次扫描已超过 7 天，请更新检查。':''}</p>}
  {!!inventory?.history?.length&&['databases','caches'].includes(tab)&&<details className="gov-history"><summary>最近治理记录</summary>{inventory.history.map((r,i)=><p key={`${r.id}-${r.at}-${i}`}>{stamp(r.at)} · {r.category==='caches'?'缓存':'历史副本'} · {r.count} 个文件 · 释放 {size(r.released_bytes)} · {({completed:'已处理',restored:'已恢复',purged:'已永久清理',partial:'部分完成'} as Record<string,string>)[r.status]||r.status}</p>)}</details>}
  <Modal title="核对清理清单" open={!!preview} width={920} onCancel={()=>{if(!busy)setPreview(undefined);}} footer={<Space><Button disabled={busy} onClick={()=>setPreview(undefined)}>取消</Button><Button danger type="primary" loading={busy} disabled={!confirmed} onClick={()=>act(cleanup)}>{preview?.category==='databases'?'确认移入隔离区':'确认永久清理'}</Button></Space>}>
   {preview&&<><p>{preview.notice}</p><p>共 {preview.count} 个文件，{preview.category==='databases'?'移入隔离区后仍占用':'预计释放'} {size(preview.bytes)}。文件发生变化时系统会停止，要求重新扫描。</p>
    <Table<Backup> size="small" rowKey="path" dataSource={preview.entries} pagination={{pageSize:8}} columns={[{title:'将删除的具体文件',dataIndex:'path',render:v=><span className="gov-path">{v}</span>},{title:'大小',width:130,render:(_,r)=>size(r.bytes)}]}/>
    <Checkbox checked={confirmed} onChange={e=>setConfirmed(e.target.checked)}>{preview.category==='databases'?'我已核对清单，确认将以上副本移入可恢复隔离区':'我已核对清单，确认永久删除以上可重建缓存'}</Checkbox></>}
  </Modal>
  <Modal title={quarantineAction?.action==='restore'?'恢复隔离区副本':'永久清理隔离区'} open={!!quarantineAction} width={920} onCancel={()=>{if(!busy)setQuarantineAction(undefined);}} footer={<Space><Button disabled={busy} onClick={()=>setQuarantineAction(undefined)}>取消</Button><Button danger={quarantineAction?.action==='purge'} type="primary" disabled={!confirmed} loading={busy} onClick={()=>act(handleQuarantine)}>确认{quarantineAction?.action==='restore'?'恢复':'永久清理'}</Button></Space>}>
   {quarantineAction&&<><p>{quarantineAction.action==='restore'?'恢复到原位置，已有同名文件时不会覆盖。':'永久删除以下隔离区副本，删除后不可恢复。'}</p><p>{quarantineAction.item.count} 个文件 · {size(quarantineAction.item.bytes)}</p>
    <Table size="small" rowKey="path" dataSource={quarantineAction.item.entries||[]} pagination={{pageSize:8}} columns={[{title:'副本原位置',dataIndex:'path',render:v=><span className="gov-path">{v}</span>},{title:'大小',render:(_,r)=>size(r.bytes)}]}/>
    <Checkbox checked={confirmed} onChange={e=>setConfirmed(e.target.checked)}>我已核对以上具体文件与操作</Checkbox></>}
  </Modal>
 </section>;
}
