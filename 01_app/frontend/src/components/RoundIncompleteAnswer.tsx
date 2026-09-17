import type {PiRun,Receipt} from '../chat';
import {legacyWorkflowStages} from '../workProgress';
import MessageMarkdown from './MessageMarkdown';

// Use only this run's receipts: a partial answer must not become a registered result.
export function incompleteAnswerRows(run:PiRun,rows:Receipt[]){
 return ['incomplete','failed','cancelled','interrupted'].includes(run.status)&&legacyWorkflowStages.includes(run.stage)
  ?rows.filter(row=>row.run_id===run.id&&row.kind==='assistant'&&row.body.phase==='answer'&&typeof row.body.text==='string'&&row.body.text.trim()).slice(-1):[];
}
export default function RoundIncompleteAnswer({run,rows}:{run:PiRun;rows:Receipt[]}){
 const answers=incompleteAnswerRows(run,rows);
 if(!answers.length)return null;
 return <section className="round-incomplete-answer" aria-label="本轮未完成说明">
  <p role="status"><strong>本轮未完成 · 以下为模型说明，尚未形成完整流程结果</strong></p>
  {run.reason&&<p>{run.reason}</p>}
  {answers.map(row=><div key={row.seq} data-message-id={`${run.id}:${row.seq}`}><MessageMarkdown text={String(row.body.text)}/></div>)}
 </section>;
}
