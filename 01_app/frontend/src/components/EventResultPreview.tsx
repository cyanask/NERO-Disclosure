import {Button,Modal,Table} from 'antd';
import type {AgentTask,DisclosureEvent,Knowledge} from '../types';
import {display,prose} from '../api';
import Evidence from './Evidence';
import ConditionalPlan from './ConditionalPlan';

export function CandidateContent({result,sources=[]}:{result:AgentTask['result'];sources?:Knowledge[]}){
 if(!result)return null;
 const status:Record<string,string>={disclose:'应当披露',no_disclosure:'无需披露',review_required:'待专业复核',needs_info:'事实待补充'};
 return <div className="candidate-content">
  {result.status&&<p className="status-text">{status[result.status]||result.status}</p>}
  {result.summary&&<p className="preserve">{prose(result.summary)}</p>}
  <ConditionalPlan plan={result.preliminary_plan}/>
  {([['reasons','判断依据'],['missing','待补事项'],['limitations','适用限制']] as const).map(([key,label])=>!!result[key]?.length&&<section key={key}><h3>{label}</h3><ul>{result[key]!.map((text,i)=><li key={i}>{text}</li>)}</ul></section>)}
  {!!result.items?.length&&<section><h3>披露清单</h3>{result.items.map((item,i)=><article className="candidate-item" key={item.id||i}><h4>{i+1}. {item.title}</h4><p className="preserve">{item.requirement}</p>{item.detail&&<p className="preserve">{item.detail}</p>}<p className="muted">资料状态：{({complete:'已齐备',missing:'待补',pending:'待核对'} as Record<string,string>)[item.evidence_status]||item.evidence_status||'未登记'}{item.notes&&` · ${item.notes}`}</p></article>)}</section>}
  {result.text&&<section><h3>公告正文</h3><div className="candidate-draft preserve">{result.text}</div></section>}
  {result.documents?.filter(d=>!!d.text).map(d=><section key={d.document_id}><h3>文件正文 · {d.document_id}</h3><div className="candidate-draft preserve">{d.text}</div></section>)}
  {!!sources.length&&<details><summary>引用依据（{sources.length} 条）</summary><Evidence items={sources}/></details>}
  <details><summary>完整候选记录</summary><pre className="snapshot">{display(result)}</pre></details>
 </div>;
}

export default function EventResultPreview({event,stage,open,onClose,outdated,confirmed,resultLabel}:{event:DisclosureEvent;stage:string;open:boolean;onClose:()=>void;outdated:boolean;confirmed:boolean;resultLabel:string}){
 return (<Modal className="event-result-modal" title={outdated?`历史${resultLabel}（需重新核验）`:resultLabel} open={open} width={860} onCancel={onClose} footer={<Button onClick={onClose}>关闭</Button>}>
   <p className="muted">{event.title} · r{event.revision} · {confirmed?'当前版本已确认':outdated?'历史结果，需重新核验':'查看已有内容不代表已确认或已发布'}</p>
   {stage==='assessment'&&event.assessment&&<CandidateContent result={event.assessment} sources={event.assessment.citations}/>}
   {stage==='plan'&&event.plan&&<>{!!event.plan.documents?.length&&<Table size="small" rowKey="document_id" pagination={false} dataSource={event.plan.documents} columns={[{title:'文件',dataIndex:'title'},{title:'出具方',dataIndex:'producer'},{title:'适用及时间',render:(_,d)=><>{d.applicability}；{d.timing}</>}]}/>}<CandidateContent result={{items:event.plan.items}} sources={event.plan.cases}/>{event.plan.requirements?.map(r=><section key={r.requirement_id}><h3>{r.topic}</h3><p>{r.granularity}</p><p>适用：{r.applicability}；核对：{r.verify_method}</p></section>)}{!!event.plan.drafting_gaps?.length&&<ul>{event.plan.drafting_gaps.map(g=><li key={g.key}>{g.description}；提供方：{g.owner}</li>)}</ul>}<details><summary>完整规划记录</summary><pre className="snapshot">{display(event.plan)}</pre></details></>}
   {stage==='template'&&event.template&&<><p>模板：{event.template.template_id}</p><ul>{event.template.adaptations.map((item,i)=><li key={i}>{item}</li>)}</ul><pre className="snapshot">{display(event.template.requirement_map)}</pre></>}
   {stage==='draft'&&event.draft&&<CandidateContent result={event.draft}/>}
   {stage==='word'&&event.artifacts?.filter(a=>a.id===event.current_artifact_id).map(a=><div key={a.id}><a href={`/api/events/${event.id}/artifacts/${a.id}/file`} target="_blank" rel="noreferrer">打开 {a.filename}</a><details><summary>文件检查记录</summary><pre className="snapshot">{display(a.verification)}</pre></details></div>)}
  </Modal>);
}
