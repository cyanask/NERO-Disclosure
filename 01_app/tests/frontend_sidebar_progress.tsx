import React from 'react';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {parse} from 'postcss';
import {renderToStaticMarkup} from 'react-dom/server';
import SessionPanel from '../frontend/src/components/SessionPanel';
import WorkProgress from '../frontend/src/components/WorkProgress';
import ConversationNavigation from '../frontend/src/components/ConversationNavigation';
import {workProgress} from '../frontend/src/workProgress';
import type {ChatSession,PiRun} from '../frontend/src/chat';

const sessions=[['one','上市公司分红程序性要求咨询'],['two','关联财务资助审议与披露要求咨询'],['three','利润分配与对外投资公告起草']].map(([id,title])=>({id,title,updated:1,archived:0,board:'chinext',event_id:'conversation:'+id})) as ChatSession[];
const chosen:string[]=[];
const base={sessions,sid:'two',search:'没有匹配',archived:false,busy:false,running:()=>false,onSearch:()=>{},onToggle:()=>{},onNew:()=>{},onChoose:(id:string)=>chosen.push(id),onArchive:()=>{},onDelete:()=>{},onArchived:()=>{}};
const collapsed=renderToStaticMarkup(<SessionPanel {...base} open={false}/>);
for(const s of sessions){assert.ok(collapsed.includes(s.title));assert.ok(collapsed.includes(`title="${s.title} ·`));}
assert.match(collapsed,/sessions-collapsed/);assert.match(collapsed,/aria-current="true"/);assert.match(collapsed,/aria-expanded="false"/);
const expanded=renderToStaticMarkup(<SessionPanel {...base} open/>);
assert.match(expanded,/未找到匹配会话/);assert.doesNotMatch(expanded,/class="session-select"/);
// Exercise the actual compact task buttons' existing selection callbacks.
function elements(node:any):any[]{if(Array.isArray(node))return node.flatMap(elements);if(!node||typeof node!=='object'||!node.props)return [];return [node,...elements(node.props.children)];}
const tree=SessionPanel({...base,open:false});
const taskButtons=elements(tree).filter(n=>n.type==='button'&&n.props.className==='session-select');
assert.equal(taskButtons.length,3);for(const button of taskButtons)button.props.onClick();assert.deepEqual(chosen,['one','two','three']);

const run={id:'run',session_id:'s',event_id:'conversation:s',stage:'chat',status:'running',created:1} as PiRun;
for(const stage of ['chat','knowledge','announcement','document','assessment']){
 for(const status of ['accepted','running','cancelling']){
  const p=workProgress({...run,stage,status});assert.equal(p.tone,'active');assert.equal(p.animate,status==='running');
 }
 const completed=workProgress({...run,stage,status:'completed'});assert.equal(completed.tone,'done');assert.equal(completed.animate,false);
 for(const status of ['failed','interrupted','incomplete','blocked','cancelled','waiting_user','waiting_approval','waiting_knowledge_confirmation'])assert.notEqual(workProgress({...run,stage,status}).tone,'done');
}
assert.notEqual(workProgress({...run,status:'completed'},[],{disconnected:true}).tone,'done');
assert.equal(workProgress({...run,status:'completed'},[],{historical:true}).tone,'done');
assert.notEqual(workProgress({...run,documents:[{format:'docx'} as never]}).tone,'done');
for(const status of ['running','completed']){
 const r={...run,status},progress=workProgress(r);
 const panel=renderToStaticMarkup(<WorkProgress progress={progress} run={r} runs={[r]} open onOpen={()=>{}} onSelect={()=>{}} onAction={()=>{}} onEvidence={()=>{}} onCurrent={()=>{}}/>);
 const header=renderToStaticMarkup(<ConversationNavigation progress={progress} canRead onProgress={()=>{}} onRead={()=>{}} onCompose={()=>{}}/>);
 assert.doesNotMatch(panel,/暂停动效|开启动效|系统已减弱动效/);
 assert.match(panel,new RegExp(`work-progress ${status==='running'?'active':'done'}`));
 assert.match(header,new RegExp(`header-progress-trigger ${status==='running'?'active':'done'}`));
 assert.match(panel,new RegExp(`data-motion="${status==='running'?'on':'off'}"`));
}
// Static cascade guard for the actual defect: no rule may hide the collapsed task list.
for(const file of ['styles.css','conversationReading.css']){
 parse(fs.readFileSync(path.join(process.cwd(),'frontend/src',file),'utf8')).walkRules(rule=>{
  if(rule.selectors.some(s=>s.includes('.sessions-collapsed')&&s.includes('.session-list'))){
   assert.ok(!rule.nodes.some(n=>n.type==='decl'&&n.prop==='display'&&n.value==='none'),`${file}: compact task list hidden`);
  }
 });
}
for(const [file,selector] of [['ConversationNavigation.css','.header-progress-trigger'],['WorkProgress.css','.work-progress']]){
 const root=parse(fs.readFileSync(path.join(process.cwd(),'frontend/src/components',file),'utf8'));
 for(const [state,color] of [['active','#b33d35'],['done','#2c7a50']]){
  let found=false;root.walkRules(rule=>{if(rule.selector.startsWith(selector+'.'+state+' '))rule.walkDecls('background',d=>{if(d.value===color)found=true;});});
  assert.ok(found,`${file}: ${state} color`);
 }
 assert.ok(root.nodes.some(n=>n.type==='atrule'&&n.params.includes('prefers-reduced-motion')));
}
console.log('PASS: collapsed task selection, hidden filter recovery, red active / green completed states, removed motion controls, reduced-motion accessibility and no collapsed-list hiding rule');
