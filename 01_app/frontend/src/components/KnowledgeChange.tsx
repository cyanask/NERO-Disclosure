import {useState} from 'react';
import {Alert,Button,Checkbox} from 'antd';
import type {PiRun} from '../chat';
import {api} from '../api';
const labels:Record<string,string>={edit:'编辑',delete:'删除',admit:'入库',template:'制作模板',laws:'法规',cases:'案例',profiles:'内容模板',title:'标题',text:'正文',effective_from:'生效日',effective_to:'失效日',url:'来源',sections:'章节与内容要求',normative_source_ids:'法源依据',case_evidence:'参考案例',layout_profile_id:'版式依据',article:'条款位置',as_of:'核对时点'};
Object.assign(labels,{file_import_batch:'批量入库',file_import:'新增入库',file_delete:'删除',template_replace:'替换模板',history:'历史公告'});
export default function KnowledgeChange({run,busy,onDone}:{run:PiRun;busy:boolean;onDone:(r:PiRun)=>void}){
 const [saving,setSaving]=useState(false),[error,setError]=useState('');const value=run.knowledge_change!;
 const [publication,setPublication]=useState(false),[extraction,setExtraction]=useState(false);
 const apply=async(accept:boolean)=>{setSaving(true);setError('');try{await api(`/chat/runs/${run.id}/knowledge-confirmation`,'POST',{fingerprint:value.fingerprint,accept,declarations:{publication_confirmed:publication,company_confirmed:publication,extraction_confirmed:extraction}});const next=await api<{run:PiRun}>(`/chat/runs/${run.id}`);onDone(next.run);}catch(e){setError((e as Error).message);}finally{setSaving(false);}};
 return <section className="inline-panel" aria-label="知识库变更确认"><h3>{labels[value.operation]||value.operation}{labels[value.collection]||value.collection}</h3><p>{value.summary}</p><ul>{value.objects.map(o=><li key={o.id}>{o.title}</li>)}</ul>
 {value.operation==='delete'&&<p>删除当前库条目及相关索引；历史依据版本和官方原件保留。</p>}
 {value.references.length>0&&<details><summary>引用及可能复核范围（{value.references.length}）</summary>{value.references.map((r,i)=><p key={i}>{r.kind}：{r.title}</p>)}</details>}
 <details><summary>核对具体变更内容</summary>{value.items.map((item,i)=><article key={i}>{Object.entries(item).map(([key,v])=><div key={key}><strong>{labels[key]||key}</strong>{value.operation==='edit'&&key!=='id'&&<div className="muted">原值：<pre className="preserve">{JSON.stringify(value.before.find(x=>x.id===item.id)?.[key]??null,null,2)}</pre>拟改为：</div>}<pre className="preserve">{typeof v==='string'?v:JSON.stringify(v,null,2)}</pre></div>)}</article>)}{value.operation==='delete'&&value.before.map((r,i)=><article key={i}><strong>{String(r.title)} {String(r.article||'')}</strong><pre className="preserve">{typeof r.text==='string'?r.text:JSON.stringify(r.sections||{},null,2)}</pre></article>)}</details>
 {!!value.source?.empty_pages?.length&&<Alert type="warning" message={`原件第 ${value.source.empty_pages.join("、")} 页无可提取文本，可能为空白或扫描页，需核对原件；不能视为全文提取完成。`}/>}
 {!!value.source&&<p><a href={`/api/chat/runs/${run.id}/source-candidate`}>下载本轮官方原件，核对正文与日期</a></p>}
 {!!value.basis?.length&&<details><summary>模板依据</summary>{value.basis.map(x=><p key={x.id}><a href={/^https?:\/\//.test(x.url)?x.url:undefined} target="_blank" rel="noreferrer">{x.title} {x.article}</a></p>)}</details>}
 {!!value.template&&<p><a href={`/api/chat/runs/${run.id}/template-candidate`}>下载模板候选，核对内容和格式</a></p>}
 {error&&<Alert type="error" message={error}/>}{value.status==='partial'&&<Alert type="warning" message={value.operation==='file_import_batch'?`已完成 ${String(value.result?.completed||0)} 份，剩余 ${String(value.result?.remaining||0)} 份；重试仅处理未完成文件。`:'内容模板已入库，Word模板登记尚未完成；点击确认重试登记，不重复写入内容。'}/>}
 {value.requires_publication_confirmation&&<p><Checkbox checked={publication} onChange={e=>setPublication(e.target.checked)}>我已核对公司归属及官方发布依据，确认这是已正式发布的公告</Checkbox></p>}
 {value.requires_extraction_confirmation&&<p><Checkbox checked={extraction} onChange={e=>setExtraction(e.target.checked)}>我已结合原件核对 OCR、图片或修订部分的抽取结果</Checkbox></p>}
 {value.file_operation&&value.operation!=='file_delete'&&<div>{value.objects.map(o=><p key={o.id}><a href={`/api/library/imports/${o.id}/original?${new URLSearchParams({board:run.board,company:value.company||''})}`} target="_blank" rel="noreferrer">核对原件：{o.title}</a></p>)}</div>}
 {value.source_preview&&<details><summary>查看原文摘录</summary><pre className="preserve">{value.source_preview}</pre></details>}
 {Array.isArray(value.result?.projection_warnings)&&<Alert type="warning" message={value.result.projection_warnings.join('；')}/>}
 {['pending','partial'].includes(value.status)?<div className="inline-actions"><Button disabled={busy||saving} onClick={()=>apply(false)}>取消本次变更</Button><Button type="primary" danger={value.operation==='delete'} loading={saving} disabled={busy} onClick={()=>apply(true)}>确认{labels[value.operation]||'执行'}以上对象</Button></div>:<p>{value.status==='applied'?'已执行；专业与格式审阅状态以登记结果为准。':'本次变更已取消。'}</p>}
 </section>;
}
