import type {Receipt} from './chat';
import type {DisclosureEvent,Knowledge,PlanningView} from './types';

export type ResultContent = Partial<NonNullable<DisclosureEvent['assessment']>> & Partial<PlanningView> & {
 text?:string;items?:{id:string;title:string;detail:string}[];
 template_id?:string;adaptations?:string[];
};
export interface ResultSnapshot {event_id:string;revision:number;stage:string;outcome:string;result:ResultContent|null;sources:Knowledge[];legacy?:boolean}

// This projection uses only this run's receipts, never the current event.
export function roundResult(rows:Receipt[]):ResultSnapshot|undefined{
 const saved=[...rows].reverse().find(r=>r.kind==='result_snapshot');
 if(saved)return saved.body as unknown as ResultSnapshot;
 const evaluated=[...rows].reverse().find(r=>r.kind==='tool_returned'&&r.body.name==='task.evaluate');
 if(!evaluated)return;
 const submitted=[...rows].reverse().find(r=>r.seq<evaluated.seq&&r.kind==='model_tool_call'&&r.body.name==='submit_candidate');
 if(!submitted)return;
 const reply=evaluated.body.result as {event_id:string;expected_revision:number;outcome:string};
 const result=(submitted.body.args as {result:ResultContent}).result;
 const context=rows.find(r=>r.kind==='context_loaded')?.body.context as {sources?:Knowledge[];stage?:string}|undefined;
 const stage=String(rows.find(r=>r.kind==='accepted')?.body.stage||context?.stage||'assessment');
 return {event_id:reply.event_id,revision:reply.expected_revision,stage,outcome:reply.outcome,result,
  sources:context?.sources||[],legacy:true};
}
