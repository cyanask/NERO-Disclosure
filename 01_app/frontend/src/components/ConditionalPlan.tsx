import type {PlanningView} from '../types';

export default function ConditionalPlan({plan,compact=false}:{plan?:PlanningView|null;compact?:boolean}){
 if(!plan)return null;
 const purposes:Record<string,string>={public:'公开披露',filing:'报送或备查',internal:'内部支持'};
 return <section aria-label="条件性文件与内容要求" className="conditional-plan">
  <h3>条件性文件与内容要求</h3>
  <p className="muted">以下用于比较适用分支和准备资料。正式文件范围仍需结合已确认事实，在规划节点采纳。</p>
  {compact?<div className="message-table"><table><thead><tr><th>文件与用途</th><th>适用条件与时点</th><th>内容颗粒度</th></tr></thead><tbody>{plan.documents.map(doc=><tr key={doc.document_id}><td><strong>{doc.title}</strong><br/>{purposes[doc.purpose]||doc.purpose} · {doc.producer}</td><td>{doc.applicability}<br/>{doc.timing}</td><td>{plan.requirements.filter(r=>r.document_id===doc.document_id).map(r=><p key={r.requirement_id}>{r.topic}：{r.granularity}{r.applicability_status==='not_applicable'&&<><br/>不写入本次正文，终稿时核对：{r.applicability}</>}</p>)}</td></tr>)}</tbody></table></div>:plan.documents.map(doc=><article className="candidate-item" key={doc.document_id}>
   <h4>{doc.title}</h4><p>{purposes[doc.purpose]||doc.purpose} · {doc.producer} · {doc.stage==='later_trigger'?'后续触发':'条件性准备'}</p>
   <p className="preserve">适用条件：{doc.applicability}</p><p className="preserve">时间安排：{doc.timing}</p>
   {plan.requirements.filter(r=>r.document_id===doc.document_id).map(r=><div key={r.requirement_id}><strong>{r.topic}</strong><p className="preserve">{r.granularity}</p>{r.applicability_status==='not_applicable'&&<p>不写入本次正文，终稿时核对：{r.applicability}</p>}</div>)}
  </article>)}
  {!!plan.drafting_gaps?.length&&<><h4>资料缺口与后续待办</h4><ul>{plan.drafting_gaps.map(g=><li key={g.key}>{g.description}；影响：{({assessment:'义务判断',plan:'文件范围',draft:'正文内容',content_review:'终稿人工复核',publication:'定稿后发布准备'} as Record<string,string>)[g.impact]||g.impact}；提供方：{g.owner}</li>)}</ul></>}
  {!!plan.blocking_questions?.length&&<><h4>仍需确认</h4><ul>{plan.blocking_questions.map((q,i)=><li key={i}>{q}</li>)}</ul></>}
  {plan.limitations?.map((note,i)=><p className="muted" key={i}>{note}</p>)}
 </section>;
}
