import type {PiRun,Receipt} from './chat';

// Keep the journal intact; retry attempts are available in the process details.
export function visibleAnswers(run:PiRun,rows:Receipt[]){
 const assistants=rows.filter(r=>r.run_id===run.id&&r.kind==='assistant'&&r.body.text);
 const finals=assistants.filter(r=>r.body.phase==='final'&&r.body.stopReason==='stop');
 const answers=finals.length?finals:['chat','knowledge','document','announcement','confirmation'].includes(run.stage)
  ?assistants.filter(r=>r.body.phase!=='progress'&&r.body.stopReason!=='toolUse'):[];
 if(rows.some(r=>r.run_id===run.id&&r.kind==='completion_repair_started'))return answers.slice(-1);
 return answers;
}
