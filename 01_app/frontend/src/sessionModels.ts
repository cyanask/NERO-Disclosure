import type {PiCapabilities,PiRun} from './chat';
import {live} from './chat';

type ModelStorage=Pick<Storage,'getItem'|'setItem'|'removeItem'>;
const storageKey=(board:string,sid:string)=>`nero-disclosure:session-model:${board}:${sid}`;
function browserStorage():ModelStorage|undefined{try{return window.localStorage;}catch{return;}}

export function savedSessionModel(board:string,sid:string,storage=browserStorage()):string|undefined{
 if(!sid)return;
 try{const value=storage?.getItem(storageKey(board,sid));return value&&value.length<=80?value:undefined;}catch{return;}
}
export function saveSessionModel(board:string,sid:string,key:string,storage=browserStorage()):boolean{
 if(!sid)return true;
 try{if(!storage)return false;storage.setItem(storageKey(board,sid),key);return true;}catch{return false;}
}
export function forgetSessionModel(board:string,sid:string,storage=browserStorage()){
 try{storage?.removeItem(storageKey(board,sid));}catch{/* The in-memory preference is still removed by the caller. */}
}
export function modelAvailable(caps:PiCapabilities|undefined,key:string){return !!caps?.models.some(m=>m.key===key&&m.configured&&m.visible!==false);}

export function resolveSessionModel(caps:PiCapabilities|undefined,sid:string,loadedSid:string,runs:PiRun[],remembered?:string):string{
 // Never use the previous session's in-flight detail response or run snapshot.
 if(sid&&loadedSid!==sid)return remembered||'';
 const own=sid?runs.filter(r=>r.session_id===sid):[];
 const active=own.find(live);
 if(active)return active.model.key;
 if(remembered!==undefined)return remembered;
 if(own[0]?.model.key)return own[0].model.key;
 if(!caps)return '';
 const fallback=caps.routes?.chat||caps.routes?.default;
 return fallback?(modelAvailable(caps,fallback)?fallback:''):caps.models.find(m=>m.configured&&m.visible!==false)?.key||'';
}
