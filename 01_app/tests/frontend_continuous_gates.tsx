import assert from 'node:assert/strict';
import {test} from 'node:test';
import React from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
import {DraftReviewBody} from '../frontend/src/components/DisclosureConfirmation';
import RoundIncompleteAnswer,{incompleteAnswerRows} from '../frontend/src/components/RoundIncompleteAnswer';
import {canSubmitConfirmation,humanGatesForEvent,pendingHumanGate,needsUserInput,wordReviewCopy} from '../frontend/src/humanGates';
import type {DisclosureEvent} from '../frontend/src/types';
import type {PiRun,Receipt} from '../frontend/src/chat';
const event={id:'e',workflow_policy:'continuous-v1',output_mode:'text',revision:1,stage:'awaiting_draft_confirmation',approval_records:[],plan:{documents:[{document_id:'d1',title:'第一份文件',purpose:'public',stage:'current',producer:'公司',applicability:'适用说明',timing:'本次'}, {document_id:'d2',title:'第二份文件',purpose:'filing',stage:'current',producer:'董事会',applicability:'适用说明',timing:'本次'}]},draft:{documents:[{document_id:'d1',text:'第一份正文开头\n\n第一份正文结尾'}, {document_id:'d2',text:'第二份完整正文'}],text:'Word 路线完整正文'}} as unknown as DisclosureEvent;
const submit={stage:'draft',decision:'accept',reviewer:'审阅人',reason:'已核对',gate:{status:'PASS'},content:false,visual:false};
test('continuous text has only final draft confirmation; Word also has file acceptance',()=>{
 assert.deepEqual(humanGatesForEvent(event).map(g=>g.stage),['draft']);
 assert.deepEqual(humanGatesForEvent({...event,output_mode:'word'}).map(g=>g.stage),['draft','word']);
 assert.equal(pendingHumanGate(event)?.stage,'draft');
 for(const stage of ['awaiting_plan_confirmation','awaiting_template_confirmation'])assert.equal(pendingHumanGate({...event,stage}),undefined);
 assert.deepEqual(humanGatesForEvent({...event,workflow_policy:undefined}).map(g=>g.stage),['assessment','plan','template','word']);
});
test('exception handling remains a real human action',()=>{
 const exception={...event,stage:'awaiting_assessment_confirmation'};
 assert.equal(pendingHumanGate(exception)?.stage,'assessment');
});
test('full document list and full draft are available for human review',()=>{
 const text=renderToStaticMarkup(<DraftReviewBody event={event}/>);
 for(const phrase of ['第一份文件','第二份文件','第一份正文开头','第一份正文结尾','第二份完整正文','董事会','报送备查'])assert.ok(text.includes(phrase));
 assert.doesNotMatch(text,/Word 路线完整正文/);
 const word=renderToStaticMarkup(<DraftReviewBody event={{...event,output_mode:'word'}}/>);
 for(const phrase of ['第一份文件','第二份文件','Word 路线完整正文'])assert.ok(word.includes(phrase));
});
test('draft acceptance requires content review; Word requires content and visual review',()=>{
 assert.equal(canSubmitConfirmation(submit),false);
 assert.equal(canSubmitConfirmation({...submit,content:true}),true);
 assert.equal(canSubmitConfirmation({...submit,content:true,hasDraft:false}),false);
 assert.equal(canSubmitConfirmation({...submit,content:true,gate:{status:'BLOCKED'}}),false);
 assert.equal(canSubmitConfirmation({...submit,stage:'word',content:true}),false);
 assert.equal(canSubmitConfirmation({...submit,stage:'word',content:true,visual:true}),true);
 assert.equal(canSubmitConfirmation({...submit,stage:'word',content:true,visual:true,hasArtifact:false}),false);
 assert.equal(canSubmitConfirmation({...submit,decision:'reject'}),true);
});
test('confirmed text does not request more input',()=>{assert.equal(needsUserInput({...event,stage:'text_confirmed'},{event_id:'e',status:'waiting_user'} as PiRun),false);});
test('incomplete answer is visible as explanation only and stays isolated to its run',()=>{
 const run={id:'r',stage:'draft',status:'incomplete',reason:'正文资料未齐备'} as PiRun;
 const rows=[{seq:1,run_id:'r',kind:'assistant',body:{phase:'answer',text:'本轮已检查资料，但还需补充日期。'}},{seq:2,run_id:'another',kind:'assistant',body:{phase:'answer',text:'其他轮说明'}}] as Receipt[];
 assert.equal(incompleteAnswerRows(run,rows).length,1);
 const html=renderToStaticMarkup(<RoundIncompleteAnswer run={run} rows={rows}/>);
 assert.match(html,/本轮未完成/);assert.match(html,/尚未形成完整流程结果/);assert.match(html,/还需补充日期/);assert.doesNotMatch(html,/其他轮说明/);
 assert.equal(incompleteAnswerRows({...run,status:'completed'},rows).length,0);
 assert.equal(incompleteAnswerRows({...run,stage:'chat'},rows).length,0);
});

test('continuous Word acceptance checks transfer fidelity and actual layout after content confirmation',()=>{
 const copy=wordReviewCopy({...event,output_mode:'word'});
 assert.match(copy.content,/与已确认正文一致/);assert.match(copy.visual,/逐页检查实际排版/);
 assert.doesNotMatch(copy.content,/程序及适用限制/);
 const gate=humanGatesForEvent({...event,output_mode:'word'}).find(g=>g.stage==='word')!;
 assert.match(gate.question,/已确认正文的一致性/);
 assert.match(wordReviewCopy({...event,workflow_policy:undefined}).content,/数据、程序及适用限制/);
});
