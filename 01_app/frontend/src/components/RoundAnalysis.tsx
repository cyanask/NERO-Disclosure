import type {ResultSnapshot} from '../roundResult';
import ConditionalPlan from './ConditionalPlan';
import MessageMarkdown from './MessageMarkdown';
import type {TextDocument} from '../types';
import {prose} from '../api';

export default function RoundAnalysis({snapshot,hasAnswer}:{snapshot:ResultSnapshot;hasAnswer:boolean}){
 const r=snapshot.result;
 if(!r)return <p className="run-outcome">本轮候选未形成可呈现的分析，请展开执行记录核对。</p>;
 const result=<>
  {r.summary&&<MessageMarkdown text={prose(r.summary)}/>}
  <ConditionalPlan compact plan={r.preliminary_plan||(snapshot.stage==='plan'&&r.documents?{documents:r.documents,requirements:r.requirements||[],drafting_gaps:r.drafting_gaps}:undefined)}/>
  {snapshot.stage==='draft'&&(r.documents as unknown as TextDocument[]|undefined)?.map(d=><MessageMarkdown key={d.document_id} text={d.text}/>)}
  {r.text&&<MessageMarkdown text={r.text}/>}
  {r.template_id&&<p>模板：{r.template_id}</p>}{r.adaptations?.map((s,i)=><p key={i}>{s}</p>)}
  {!r.documents&&!r.preliminary_plan&&r.items?.map(item=><section key={item.id}><h4>{item.title}</h4><MessageMarkdown text={item.detail}/></section>)}
  {!!r.missing?.length&&<><h4>待补资料</h4><ul>{r.missing.map((s,i)=><li key={i}>{s}</li>)}</ul></>}
  {r.limitations?.map((s,i)=><p className="muted" key={i}>{s}</p>)}
 </>;
 return <section className="round-analysis" aria-label="本轮登记分析">
  <p className="result-version">本轮事项 r{snapshot.revision}{snapshot.legacy?' · 历史登记内容，未重新生成':''}{['blocked','revise'].includes(snapshot.outcome)?' · 候选未通过核验':''}</p>
  {hasAnswer?<details><summary>展开已登记的完整分析</summary>{result}</details>:result}
  {(!!r.matters?.length||!!snapshot.sources.length)&&<details className="round-sources"><summary>依据与适用分析</summary>
   {r.matters?.map(m=><section key={m.matter_id}><h4>{m.subject}</h4>{m.reasoning_items?.map((x,i)=><p key={i}>{x.condition}：{x.application}<br/>{x.locator}：{x.quote}</p>)}
    {!!m.procedural_requirements?.length&&<p>程序：{m.procedural_requirements.join('；')}</p>}
    {!!m.reassessment_conditions?.length&&<p>复判条件：{m.reassessment_conditions.join('；')}</p>}</section>)}
   {snapshot.sources.map(s=><details key={s.id}><summary>{s.title} {s.article}</summary><p>{s.text}</p>{/^https?:\/\//i.test(s.url||'')&&<a href={s.url} target="_blank" rel="noreferrer">查看来源</a>}</details>)}
  </details>}
 </section>;
}
