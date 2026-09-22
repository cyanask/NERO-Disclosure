import test from 'node:test';
import assert from 'node:assert/strict';
import {hasVisibleAnswer,needsCompletion,completionInstruction} from './completion_control.mjs';

for (const stage of ['chat','knowledge']) {
 test(`${stage}: empty answer enters recovery without a production tool`, () => {
  assert.equal(needsCompletion({stage,answered:false,requiresResult:false,awaitingRoute:false,sealed:false}),true);
  const instruction=completionInstruction(stage,[]);
  assert.match(instruction,/完整答复/);
  assert.doesNotMatch(instruction,/请调用 make_word/);
 });
 test(`${stage}: a finished answer completes read-only work`, () => {
  assert.equal(needsCompletion({stage,answered:true,requiresResult:false,awaitingRoute:false,sealed:false}),false);
 });
}
test('routing needs its routing receipt, not prose', () => {
 assert.equal(needsCompletion({stage:'auto',answered:true,requiresResult:false,awaitingRoute:true,sealed:false}),true);
});
test('document result cannot be replaced by a finished text answer', () => {
 assert.equal(needsCompletion({stage:'document',answered:true,requiresResult:true,awaitingRoute:false,sealed:false}),true);
});
test('sealed waiting-user / saved-result boundary never reopens tools', () => {
 assert.equal(needsCompletion({stage:'document',answered:false,requiresResult:true,awaitingRoute:false,sealed:true}),false);
});
for (const message of [undefined,{stopReason:'stop',content:[]},{stopReason:'stop',content:[{type:'text',text:'  '}]},
 {stopReason:'toolUse',content:[{type:'text',text:'查询中'}]},
 {stopReason:'stop',content:[{type:'text',text:'完成'},{type:'toolCall',name:'query'}]},
 {stopReason:'length',content:[{type:'text',text:'不完整'}]},
 {content:[{type:'text',text:'没有结束标记'}]}]) {
 test(`not an answer: ${JSON.stringify(message)}`, () => assert.equal(hasVisibleAnswer(message),false));
}
test('finished visible text is an answer', () => {
 assert.equal(hasVisibleAnswer({stopReason:'stop',content:[{type:'text',text:'基于现有资料，以下为测试答复。'}]}),true);
});
test('preflight recovery names only the actual preflight tool', () => {
 const instruction=completionInstruction('document_preflight',[{name:'assess_document_readiness'}]);
 assert.match(instruction,/assess_document_readiness/);
 assert.doesNotMatch(instruction,/请调用 make_word|submit_candidate/);
});
test('ready document recovery names make_word', () => {
 assert.match(completionInstruction('document',[{name:'make_word'}]),/请调用 make_word/);
});
