import React from 'react';
import assert from 'node:assert/strict';
import {renderToStaticMarkup} from 'react-dom/server';
import RoundArticle from '../frontend/src/components/RoundArticle';
import {workProgress} from '../frontend/src/workProgress';
import type {DisclosureEvent} from '../frontend/src/types';
import {openRunStream} from '../frontend/src/runStream';
import {mergeReceipts} from '../frontend/src/useRunDetail';
import type {PiRun,Receipt} from '../frontend/src/chat';

const run={id:'r1',session_id:'s1',event_id:'e1',stage:'chat',status:'completed',model:{label:'离线测试模型'},questions:['补充日期']} as PiRun;
const row=(seq:number,kind:string,body:object)=>({seq,run_id:'r1',at:0,kind,body} as Receipt);
const rows=[row(1,'user',{text:'用户问题'}),row(2,'assistant',{text:'第一条答复',message:1,stopReason:'stop'}),row(3,'assistant',{text:'第二条答复',message:2,stopReason:'stop'})];
function view(round=run,receipts=rows,hideQuestions=false){return renderToStaticMarkup(<RoundArticle run={round} rows={receipts} busy={false} hideQuestions={hideQuestions} audit={{open:false,anchor:{current:null},toggle:()=>{},close:()=>{}}} onRunChange={()=>{}}/>);}
assert.doesNotMatch(view(),/导出本条为 Word 工作稿/);
assert.match(view(),/用户问题/);assert.match(view(),/补充日期/);assert.doesNotMatch(view(run,rows,true),/补充日期/);
assert.doesNotMatch(view({...run,status:'running'}),/导出本条为 Word 工作稿/);
assert.match(view({...run,status:'failed',reason:'网络失败'}),/网络失败/);
assert.match(view({...run,artifact_id:'a1'}),/\/api\/events\/e1\/artifacts\/a1\/file/);
assert.deepEqual(mergeReceipts([rows[1],rows[0]],[rows[1],rows[2]]).map(r=>r.seq),[1,2,3]);

class Stream {
 static instances:Stream[]=[];
 listeners:Record<string,(e:unknown)=>void>={};onerror:()=>void=()=>{};closed=false;
 constructor(public url:string){Stream.instances.push(this);}
 addEventListener(kind:string,listener:(e:unknown)=>void){this.listeners[kind]=listener;}
 close(){this.closed=true;}
 emit(kind:string,body:object){this.listeners[kind]?.({data:JSON.stringify(body)});}
}
const original={source:globalThis.EventSource,fetch:globalThis.fetch,setTimeout:globalThis.setTimeout,clearTimeout:globalThis.clearTimeout};
let pending:(()=>Promise<void>)|undefined;
Object.assign(globalThis,{EventSource:Stream,setTimeout:(fn:()=>Promise<void>)=>{pending=fn;return 1;},clearTimeout:()=>{pending=undefined;}});
try {
 const received:Receipt[]=[],states:PiRun[]=[],disconnect:boolean[]=[];let valid=true;
 const dispose=openRunStream('r1',{onReceipt:r=>received.push(r),onState:r=>states.push(r),onDisconnected:v=>disconnect.push(v),current:()=>valid});
 const first=Stream.instances.at(-1)!;first.emit('receipt',rows[0]);first.onerror();
 let complete!:(value:Response)=>void;globalThis.fetch=()=>new Promise(resolve=>{complete=resolve;});
 const replay=pending!();valid=false;complete(new Response(JSON.stringify({events:[rows[1]],run})));
 await replay;first.emit('state',run);
 assert.equal(received.length,1);assert.equal(states.length,0);assert.deepEqual(disconnect,[true]);dispose();

 valid=true;received.length=0;states.length=0;disconnect.length=0;
 const end=openRunStream('r1',{onReceipt:r=>received.push(r),onState:r=>states.push(r),onDisconnected:v=>disconnect.push(v),current:()=>valid});
 const second=Stream.instances.at(-1)!;second.onerror();let calls=0;
 globalThis.fetch=async()=>new Response(JSON.stringify({run,events:++calls===1?Array.from({length:1000},(_,i)=>row(i+1,'text_delta',{delta:'x'})):[row(1001,'assistant',{text:'最终答复'})]}));
 await pending!();assert.equal(received.length,1001);assert.equal(states.length,1);assert.ok(second.closed);
 assert.equal(disconnect.at(-1),false);assert.equal(pending,undefined);end();
} finally {Object.assign(globalThis,{EventSource:original.source,fetch:original.fetch,setTimeout:original.setTimeout,clearTimeout:original.clearTimeout});}
console.log('PASS: round rendering, retired per-answer export, receipt merge, obsolete-session guards, complete paged replay, stream disposal');

const retainedGate={id:'e1',stage:'awaiting_draft_confirmation',workflow_policy:'continuous-v1',revision:1} as DisclosureEvent;
const independentQuestion=workProgress({...run,stage:'announcement',status:'waiting_user',questions:['请说明本次审议状态']},[],{pendingReview:'正文确认'});
assert.equal(independentQuestion.action,'input');assert.match(independentQuestion.detail,/请说明本次审议状态/);
