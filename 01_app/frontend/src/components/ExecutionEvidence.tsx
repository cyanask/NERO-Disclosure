import {useEffect,useState} from 'react';
import {Alert,Button,Checkbox,Empty,Modal,Select,Spin,Table} from 'antd';
import {api} from '../api';
import {nodeLabels,runLabels} from '../chat';
import {evidenceLabels,evidenceState,sourceLines,sourceUrl} from '../evidence';
import type {EvidenceSummary,SourceItem} from '../evidence';
import './ExecutionEvidence.css';

function Sources({items}:{items:SourceItem[]}){
 return <ul className="source-summary-list">{sourceLines(items).map(({item,articles})=><li key={item.key}>
  <div>{sourceUrl(item.url)?<a href={sourceUrl(item.url)} target="_blank" rel="noreferrer">{item.title}</a>:<span>{item.title}</span>}
   {articles.length>0&&<span className="source-articles">　{articles.map(a=>/^\d+(\.\d+)+$/.test(a)?`第 ${a} 条`:a).join('、')}</span>}
   <span className="source-use-state">{evidenceLabels[evidenceState(item)]}</span></div>
  {(item.version||item.effective_from||item.published_at||item.decision_number||item.stock_code||item.pages.length>0)&&<small>
   {[item.stock_code,item.version?`版本 ${item.version}`:item.effective_from?`生效 ${item.effective_from}`:'',item.published_at,item.decision_number,item.pages.length?`已读 ${item.pages.length} 页`:''].filter(Boolean).join(' · ')}
  </small>}
 </li>)}</ul>;
}

export function EvidenceContent({value}:{value:EvidenceSummary}){
 return <div className="execution-evidence">
  <p className="evidence-scope">{value.scope==='session'?'本会话累计查阅':'本轮查阅'} <span>{runLabels[value.status]||'尚未执行'}</span></p>
  {value.groups.map(group=>{
   const showNames=group.key==='cases'||group.key==='blacklist_cases';
   const primary=group.items.filter(i=>showNames||!['provided','searched'].includes(evidenceState(i)));
   const candidates=showNames?[]:group.items.filter(i=>['provided','searched'].includes(evidenceState(i)));
   const check=group.checks.at(-1);
   const initiated=group.initiated_actions||[];
   return <section className="evidence-category" key={group.key} aria-label={group.label}>
    <h3>{group.label}</h3><div>
     {check&&<div className="history-check">已比对本公司库内全部公告的{check.fields.join('、')}（{check.count} 份）
      {(check.coverage?.from||check.coverage?.through)&&<small>库内登记范围：{check.coverage.from||'未记录'} 至 {check.coverage.through||'未记录'}</small>}
      <details><summary>查看本次比对范围</summary><ul>{check.items.map(i=><li key={i.id}>{i.title}{i.published_at&&` · ${i.published_at}`}</li>)}</ul></details>
     </div>}
     {primary.length>0?<Sources items={primary}/>:!check&&!initiated.length&&<p className="evidence-empty">{candidates.length?'已取得资料，尚无正文查阅或引用记录':group.unavailable?'资料库未连接':group.incomplete?'已发起查阅':group.failed?'查阅未完成':group.searched?'已检索，未命中':'本次未查阅'}</p>}
     {initiated.map(action=><p className="evidence-empty" key={action}>{action}</p>)}
     {group.key==='history'&&primary.length>0&&<p className="evidence-note">以上为已查阅公告；读取记录不代表全文核对通过。</p>}
     {candidates.length>0&&<details className="evidence-candidates"><summary>其他检索及提供的资料（{candidates.length} 条）</summary><Sources items={candidates}/></details>}
     {(group.failed||group.unavailable)&&(primary.length>0||candidates.length>0||!!check)&&<p className="evidence-warning">{group.failed?'部分查阅失败。':''}{group.unavailable?'有资料接口未连接。':''}</p>}
    </div>
   </section>;
  })}
  <p className="evidence-note">{value.notice}{value.legacy?' 历史记录按已有回执还原，未补写查阅过程。':''}{value.unresolved_citations>0?` 有 ${value.unresolved_citations} 条引用的名称或版本记录不足。`:''}{!!value.unclassified_failures&&' 有资料读取失败，尚不能确定所属资料库。'}</p>
 </div>;
}

export function EvidencePanel({sessionId,board,company,initialRunId=''}:{sessionId:string;board:string;company:string;initialRunId?:string}){
 const [selected,setSelected]=useState(initialRunId),[value,setValue]=useState<EvidenceSummary>(),[error,setError]=useState(''),[retry,setRetry]=useState(0);
 useEffect(()=>{let active=true;let timer:ReturnType<typeof setTimeout>;setValue(undefined);setError('');
  const read=async()=>{try{const result=await api<EvidenceSummary>(`/chat/sessions/${encodeURIComponent(sessionId)}/evidence?${new URLSearchParams({board,company,run_id:selected})}`);if(!active)return;setValue(result);setError('');if(result.live)timer=setTimeout(read,2000);}catch(e){if(active)setError((e as Error).message);}};
  void read();return()=>{active=false;clearTimeout(timer);};
 },[sessionId,board,company,selected,retry]);
 return <>{error&&<Alert type="error" message={error} action={<Button onClick={()=>setRetry(n=>n+1)}>重试</Button>}/>}
  {value?<><Select className="evidence-scope-select" aria-label="依据查阅范围" value={selected} onChange={setSelected} options={[{value:'',label:'整个会话'},...value.runs.map((r,i)=>({value:r.id,label:`第 ${value.runs.length-i} 轮 · ${nodeLabels[r.stage]||'会话处理'} · ${new Date(r.created*1000).toLocaleString('zh-CN')} · ${runLabels[r.status]||r.status}`}))]}/><EvidenceContent value={value}/></>:!error&&<div className="evidence-loading"><Spin/><span>正在汇总查阅依据</span></div>}
 </>;
}

type SessionRow={id:string;title:string;updated:number;event_id:string;run_count:number;status:string};
export default function ExecutionEvidence({board,company,onSession}:{board:string;company:string;onSession:(sid:string)=>void}){
 const [rows,setRows]=useState<SessionRow[]>([]),[selected,setSelected]=useState<SessionRow>(),[error,setError]=useState(''),[loading,setLoading]=useState(false),[reload,setReload]=useState(0),[archived,setArchived]=useState(false),[page,setPage]=useState(1),[total,setTotal]=useState(0);
 useEffect(()=>{let active=true;setLoading(true);setError('');
  api<{items:SessionRow[];total:number}>(`/chat/evidence-sessions?${new URLSearchParams({board,company,archived:String(archived),offset:String((page-1)*20),limit:'20'})}`).then(r=>{if(active){setRows(r.items);setTotal(r.total);}}).catch(e=>active&&setError(e.message)).finally(()=>active&&setLoading(false));return()=>{active=false;};
 },[board,company,reload,archived,page]);
 return <section className="session-evidence-list"><div className="audit-heading"><p>按会话查看法规条款、案例、历史公告和模板。</p><div><Checkbox checked={archived} onChange={e=>{setArchived(e.target.checked);setPage(1);}}>已归档会话</Checkbox><Button onClick={()=>setReload(n=>n+1)} loading={loading}>刷新</Button></div></div>
  {error&&<Alert type="error" message={error}/>}
  <Table<SessionRow> rowKey="id" dataSource={rows} loading={loading} pagination={{current:page,pageSize:20,total,onChange:setPage,showSizeChanger:false}} columns={[
   {title:'会话',dataIndex:'title',render:(title,r)=><Button type="link" className="evidence-title-button" onClick={()=>setSelected(r)}>{title}</Button>},
   {title:'最近状态',dataIndex:'status',width:120,render:s=>runLabels[s]||'尚未执行'},
   {title:'更新时间',dataIndex:'updated',width:175,render:t=>new Date(t*1000).toLocaleString('zh-CN')},
   {title:'依据',width:110,render:(_,r)=><Button type="link" onClick={()=>setSelected(r)}>查看依据</Button>}
  ]} locale={{emptyText:<Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无会话执行记录"/>}}/>
  <Modal title={selected?.title||'会话依据'} open={!!selected} width={900} destroyOnClose onCancel={()=>setSelected(undefined)} footer={<><Button onClick={()=>{if(selected){onSession(selected.id);setSelected(undefined);}}}>打开会话</Button><Button onClick={()=>setSelected(undefined)}>关闭</Button></>}>
   {selected&&<EvidencePanel key={selected.id} sessionId={selected.id} board={board} company={company}/>}</Modal>
 </section>;
}
