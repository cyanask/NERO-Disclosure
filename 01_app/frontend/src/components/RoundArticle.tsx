import type {RefObject} from 'react';
import {Alert} from 'antd';
import type {PiRun,Receipt} from '../chat';
import {live,runLabels,runStageLabel} from '../chat';
import {profileLabel} from '../modelSettings';
import {roundResult} from '../roundResult';
import MessageMarkdown from './MessageMarkdown';
import RoundAnalysis from './RoundAnalysis';
import RoundIncompleteAnswer,{incompleteAnswerRows} from './RoundIncompleteAnswer';
import KnowledgeChange from './KnowledgeChange';
import RunTimings from './RunTimings';
import RunAuditPanel from './RunAuditPanel';
import {visibleAnswers} from '../roundAnswers';

type Props={
 run:PiRun;
 companyCode?:string;
 rows:Receipt[];
 busy:boolean;
 hideQuestions:boolean;
 audit:{open:boolean;anchor:RefObject<HTMLElement>;toggle:()=>void;close:()=>void};
 onProgress?:()=>void;
 onRunChange:(run:PiRun)=>void;
};

/** Render one round from its own immutable receipts, without reading another round's state. */
export default function RoundArticle({run,companyCode='',rows,busy,hideQuestions,audit,onRunChange,onProgress}:Props){
 const assistants=rows.filter(r=>r.kind==='assistant');
 const snapshot=roundResult(rows);
 const answers=visibleAnswers(run,rows);
 const delta=rows.filter(r=>r.kind==='text_delta'&&(r.body.phase==='final'||['chat','knowledge','document','announcement','confirmation'].includes(run.stage))
  &&!assistants.some(a=>a.body.message===r.body.message)).map(r=>r.body.delta).join('');
 const incompleteRows=incompleteAnswerRows(run,rows);
 const progress=assistants.filter(r=>!answers.includes(r)&&!incompleteRows.includes(r)&&r.body.text);

 const queued=rows.filter(r=>r.kind==='user_queued'&&!rows.some(item=>item.kind==='user'&&item.body.request_id===r.body.id));
 const messages=[...rows.filter(r=>r.kind==='user'&&r.body.text),...queued,...answers.filter(r=>r.body.text)].sort((a,b)=>a.seq-b.seq);

 return <article className="chat-round" data-run-id={run.id}>
  <div className="round-meta">
   <span>{runStageLabel(run)} · {profileLabel(run.model)}</span>
   {onProgress&&<button onClick={onProgress}>查看本轮进展</button>}
   <button onClick={audit.toggle}>{runLabels[run.status]} · 执行记录 ↗</button>
  </div>
  {messages.map(row=><div className={`chat-message ${row.kind==='user_queued'?'user':row.kind}`} data-message-id={`${run.id}:${row.seq}`} key={row.seq}>
   <span className="speaker">{row.kind==='user'||row.kind==='user_queued'?'你':'NERO'}</span>
   <MessageMarkdown text={String(row.body.text)}/>
   {Array.isArray(row.body.attachments)&&row.body.attachments.length>0&&<div className="message-attachments" aria-label="本轮补充资料">{row.body.attachments.map((a:{filename:string;id:string})=><span key={a.id}>{a.filename}</span>)}</div>}
   {row.kind==='user_queued'&&<small role="status">{rows.some(item=>item.kind==='user_message_not_applied'&&item.body.id===row.body.id)||!live(run)?'此条尚未执行，请重新发送':'已排队，等待 Pi 接收'}</small>}

  </div>)}
  {delta&&<div className="chat-message assistant streaming"><span className="speaker">NERO</span><MessageMarkdown text={delta}/></div>}
  <RoundIncompleteAnswer run={run} rows={rows}/>
  {run.announcement_assessment&&<details className="chat-tool-receipts"><summary>本次拟稿判断与范围</summary><p>{({yes:"拟按需披露起草",no:"未认定需要披露",uncertain:"披露条件尚待核实"} as Record<string,string>)[run.announcement_assessment.disclosure_needed]}</p><p>{run.announcement_assessment.disclosure_scope}</p><p>{run.announcement_assessment.reason}</p></details>}
  {run.timings&&<RunTimings run={run}/>}
  {run.knowledge_change&&<KnowledgeChange run={run} busy={busy} onDone={onRunChange}/>}
  {snapshot&&<RoundAnalysis snapshot={snapshot} hasAnswer={!!answers.length||!!delta}/>}
  {['failed','interrupted'].includes(run.finalization_status||'')&&<p className="run-outcome">业务结果已保存，收尾答复未完成。可在本轮查看已登记分析。</p>}
  {!!progress.length&&<details className="chat-tool-receipts">
   <summary>工作过程</summary>{progress.map(row=><MessageMarkdown key={row.seq} text={String(row.body.text)}/>)}
  </details>}
  <RunAuditPanel run={run} companyCode={companyCode||run.company_code||''} open={audit.open} anchor={audit.anchor} onClose={audit.close}/>
  {!!run.questions?.length&&!hideQuestions&&<Alert type="info" message="本轮提出的问题"
   description={<ul>{run.questions.map((q,i)=><li key={i}>{q}</li>)}</ul>}/>}
  {!live(run)&&!['completed','waiting_approval'].includes(run.status)&&<p className="run-outcome">
   {typeof run.reason==='string'?run.reason:'请查看执行记录中的阻断原因'}
  </p>}
  {run.artifact_id&&<a className="artifact-link" href={`/api/events/${run.event_id}/artifacts/${run.artifact_id}/file`}>下载本轮 Word 工作稿 ↗</a>}
 </article>;
}
