import type {RefObject} from 'react';
import {Alert} from 'antd';
import type {PiRun,Receipt} from '../chat';
import {live} from '../chat';
import {roundResult} from '../roundResult';
import MessageMarkdown from './MessageMarkdown';
import RoundAnalysis from './RoundAnalysis';
import RoundIncompleteAnswer from './RoundIncompleteAnswer';
import KnowledgeChange from './KnowledgeChange';
import RoundProcess from './RoundProcess';
import UserQuestion from './UserQuestion';
import DocumentPanel from './DocumentPanel';
import RoundTextDelivery from './RoundTextDelivery';
import {evidenceWarnings,unsavedDrafts,type ListedDocument} from '../conversationPresentation';
import RunAuditPanel from './RunAuditPanel';
import {visibleAnswers} from '../roundAnswers';

type Props={
 run:PiRun;
 documents?:ListedDocument[];
 companyCode?:string;
 rows:Receipt[];
 busy:boolean;
 hideQuestions:boolean;
 audit:{open:boolean;anchor:RefObject<HTMLElement>;toggle:()=>void;close:()=>void};
 onProgress?:()=>void;
 onRunChange:(run:PiRun)=>void;
};

/** Render one round from its own immutable receipts, without reading another round's state. */
export default function RoundArticle({run,documents=[],companyCode='',rows,busy,hideQuestions,audit,onRunChange}:Props){
 const assistants=rows.filter(r=>r.kind==='assistant');
 const snapshot=roundResult(rows);
 const answers=visibleAnswers(run,rows);
 const delta=rows.filter(r=>r.kind==='text_delta'&&(r.body.phase==='final'||['chat','knowledge','document','announcement','confirmation'].includes(run.stage))
  &&!assistants.some(a=>a.body.message===r.body.message)).map(r=>r.body.delta).join('');

 const drafts=unsavedDrafts(run,rows);
 const queued=rows.filter(r=>r.kind==='user_queued'&&!rows.some(item=>item.kind==='user'&&item.body.request_id===r.body.id));
 const questions=[...rows.filter(r=>r.run_id===run.id&&r.kind==='user'&&r.body.text),...queued].sort((a,b)=>a.seq-b.seq);
 return <article className="chat-round" data-run-id={run.id}>
  {questions.map(row=><UserQuestion key={row.seq} row={row} runId={run.id} queuedNotice={row.kind==='user_queued'?(rows.some(item=>item.kind==='user_message_not_applied'&&item.body.id===row.body.id)||!live(run)?'此条尚未执行，请重新发送':'已排队，等待 Pi 接收'):undefined}/>)}
  <RoundProcess run={run} rows={rows}/>
  {!live(run)&&!['completed','waiting_approval'].includes(run.status)&&<p className="run-outcome" role="status">{drafts.length?'本轮未完成，草稿未保存为交付物。 ':''}{typeof run.reason==='string'?run.reason:'请查看执行记录中的原因'}</p>}
  {answers.filter(row=>row.body.text).map(row=><div className="chat-message assistant" data-message-id={`${run.id}:${row.seq}`} key={row.seq}>
   <MessageMarkdown text={String(row.body.text)}/>
   {evidenceWarnings(row.body.warnings).length>0&&<aside className="answer-caveats" aria-label="依据核验提醒"><strong>依据核验提醒</strong><ul>{evidenceWarnings(row.body.warnings).map(group=><li key={group.reason}><span>{group.reason}{group.count>1?`（${group.count}项）`:''}</span>{group.statements.length>0&&<details><summary>查看对应表述</summary><ul>{[...new Set(group.statements)].map(statement=><li key={statement}>{statement}</li>)}</ul></details>}</li>)}</ul></aside>}
  </div>)}
  {delta&&<div className="chat-message assistant streaming"><MessageMarkdown text={delta}/></div>}
  <RoundIncompleteAnswer run={run} rows={rows}/>
  {run.announcement_assessment&&<details className="chat-tool-receipts"><summary>本次拟稿判断与范围</summary><p>{({yes:"拟按需披露起草",no:"未认定需要披露",uncertain:"披露条件尚待核实"} as Record<string,string>)[run.announcement_assessment.disclosure_needed]}</p><p>{run.announcement_assessment.disclosure_scope}</p><p>{run.announcement_assessment.reason}</p></details>}
  {run.knowledge_change&&<KnowledgeChange run={run} busy={busy} onDone={onRunChange}/>}
  {snapshot&&<RoundAnalysis snapshot={snapshot} hasAnswer={!!answers.length||!!delta}/>}
  {['failed','interrupted'].includes(run.finalization_status||'')&&<p className="run-outcome">业务结果已保存，收尾答复未完成。可在本轮查看已登记分析。</p>}
  <RunAuditPanel run={run} companyCode={companyCode||run.company_code||''} open={audit.open} anchor={audit.anchor} onClose={audit.close}/>
  {!!run.questions?.length&&!hideQuestions&&<Alert type="info" message="本轮提出的问题"
   description={<ul>{run.questions.map((q,i)=><li key={i}>{q}</li>)}</ul>}/>}
  {!!drafts.length&&<details className="unsaved-draft"><summary>查看本轮未保存草稿（历史尝试）</summary><p className="delivery-warning">以下为当时提交但未成功保存的内容，不能作为已核验或已交付版本；本次仅恢复查看，不重新提交或生成文件。</p>{drafts.map((draft,index)=><div key={index}><h3>{draft.title}</h3><MessageMarkdown text={draft.text}/></div>)}</details>}
  <RoundTextDelivery run={run} items={documents} answer={answers.map(r=>String(r.body.text||'')).join('\n')}/>
  <DocumentPanel run={run} items={documents}/>
 </article>;
}
