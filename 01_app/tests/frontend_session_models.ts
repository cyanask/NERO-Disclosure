import assert from 'node:assert/strict';
import {saveSessionModel,savedSessionModel,forgetSessionModel,resolveSessionModel,modelAvailable} from '../frontend/src/sessionModels';
import type {PiCapabilities,PiRun} from '../frontend/src/chat';

const values=new Map<string,string>();
const storage={getItem:(key:string)=>values.get(key)??null,setItem:(key:string,value:string)=>{values.set(key,value);},removeItem:(key:string)=>{values.delete(key);}};
const caps={models:[{key:'a',configured:true,visible:true},{key:'b',configured:true,visible:true}],routes:{chat:'a'}} as PiCapabilities;
const run=(sid:string,key:string,status='completed')=>({id:`${sid}-${key}`,session_id:sid,model:{key},status} as PiRun);

saveSessionModel('chinext','one','a',storage);saveSessionModel('chinext','two','b',storage);
assert.equal(savedSessionModel('chinext','one',storage),'a');
assert.equal(savedSessionModel('chinext','two',storage),'b');
assert.equal(savedSessionModel('base','one',storage),undefined);
assert.equal(resolveSessionModel(caps,'one','one',[run('one','b')],savedSessionModel('chinext','one',storage)),'a');
assert.equal(resolveSessionModel(caps,'two','two',[run('two','a')],savedSessionModel('chinext','two',storage)),'b');
assert.equal(resolveSessionModel(caps,'one','one',[run('one','b')]),'b'); // Historical actual model beats the global default.
assert.equal(resolveSessionModel(caps,'two','one',[run('one','a','running')]),''); // Late previous-session data is ignored.
assert.equal(resolveSessionModel(caps,'two','two',[run('one','a','running'),run('two','b')]),'b');
assert.equal(resolveSessionModel(caps,'one','one',[run('one','a','running')],'b'),'a'); // An accepted run is locked.
assert.equal(resolveSessionModel(caps,'one','one',[run('one','a')],'b'),'b'); // Next-round choice applies after completion.
assert.equal(resolveSessionModel(caps,'','one',[run('one','b')]),'a'); // New drafts do not inherit another conversation.
assert.equal(resolveSessionModel(caps,'','one',[],'b'),'b');
assert.equal(resolveSessionModel(caps,'one','one',[],'removed'),'removed');
assert.equal(modelAvailable(caps,'removed'),false); // Do not silently replace an unavailable selection.
saveSessionModel('chinext','','b',storage);assert.equal(values.size,2);
forgetSessionModel('chinext','one',storage);assert.equal(savedSessionModel('chinext','one',storage),undefined);assert.equal(savedSessionModel('chinext','two',storage),'b');
const blocked={...storage,setItem:()=>{throw Error('storage blocked');}};
assert.equal(saveSessionModel('chinext','three','a',blocked),false);
console.log('PASS: per-session/board isolation, persisted selections, actual-model fallback, async scope, active-run lock, unavailable models, scoped cleanup');
