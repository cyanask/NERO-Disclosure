import type {DocumentVersion,PiRun,Receipt} from './chat';
import {live} from './chat';

export type ListedDocument=DocumentVersion&{available?:boolean;history?:DocumentVersion[]};
/** Only recorded Word versions, never model prose or an empty document placeholder. */
export function deliveredWords(run:PiRun,items:ListedDocument[]):ListedDocument[]{
 const versions=items.flatMap(item=>[item,...(item.history||[]).filter(v=>v.version!==item.version)]);
 const delivered=run.documents?.length?run.documents:versions.filter(v=>v.run_id===run.id);
 return [...new Map(delivered.filter(v=>(v.format||'docx')==='docx'&&v.document_id&&v.version&&v.download)
  .map(v=>{const listed=versions.find(x=>x.document_id===v.document_id&&x.version===v.version);return [`${v.document_id}:${v.version}`,{...v,...listed}];})).values()];
}
/** Public assistant commentary is separate from the final answer and private reasoning. */
export function currentProcessText(run:PiRun,rows:Receipt[]):string{
 if(!live(run))return '';
 const row=rows.filter(r=>r.run_id===run.id&&r.kind==='assistant'&&r.body.phase==='progress'
  &&typeof r.body.text==='string'&&/[\u3400-\u9fff]/.test(r.body.text)).at(-1);
 return row?String(row.body.text):'';
}
export function elapsedLabel(milliseconds:number|null):string{
 if(milliseconds===null)return '用时未记录';
 const seconds=Math.floor(milliseconds/1000);
 return seconds>=60?`${Math.floor(seconds/60)}分${seconds%60}秒`:`${seconds}秒`;
}

export function deliveredTexts(run:PiRun,items:ListedDocument[]):ListedDocument[]{
 const versions=items.flatMap(item=>[item,...(item.history||[]).filter(v=>v.version!==item.version)]);
 const delivered=run.documents?.length?run.documents:versions.filter(v=>v.run_id===run.id);
 return [...new Map(delivered.filter(v=>v.format==='text'&&v.document_id&&v.version)
  .map(v=>[`${v.document_id}:${v.version}`,{...v,...versions.find(x=>x.document_id===v.document_id&&x.version===v.version)}] as const)).values()];
}


export function evidenceWarnings(value:unknown):{reason:string;count:number;statements:string[]}[]{
 if(!Array.isArray(value))return [];
 const groups=new Map<string,{reason:string;count:number;statements:string[]}>();
 for(const warning of value){
  if(!warning||typeof warning!=='object')continue;
  const reason=typeof warning.reason==='string'&&warning.reason.trim()?warning.reason.trim():'此项依据尚待核实';
  const display=reason==='引文在所引来源中定位不到，请复制来源原句'?'引用未能与来源原文匹配，相关结论仍需核对'
   :reason==='该断言未逐字出现在提交正文中，statement 须复制正文原句'?'正文与所绑定的依据尚未核对一致':reason;
  const group:{reason:string;count:number;statements:string[]}=groups.get(reason)||{reason:display,count:0,statements:[]};group.count++;
  if(typeof warning.statement==='string'&&warning.statement.trim())group.statements.push(warning.statement.trim());
  groups.set(reason,group);
 }
 return [...groups.values()];
}

export function unsavedDrafts(run:PiRun,rows:Receipt[]):{title:string;text:string}[]{
 if(!['failed','blocked','incomplete','cancelled','interrupted'].includes(run.status)||run.documents?.length||run.artifact_id)return [];
 const attempted=rows.filter(row=>row.run_id===run.id&&row.kind==='model_tool_call'&&['make_word','save_announcement'].includes(String(row.body.name))).at(-1);
 const args=attempted?.body.args as {documents?:unknown[]}|undefined;
 if(!Array.isArray(args?.documents))return [];
 return args.documents.flatMap(value=>{
  if(!value||typeof value!=='object')return [];
  const item=value as {title?:unknown;text?:unknown};
  return typeof item.text==='string'&&item.text.trim()?[{title:typeof item.title==='string'?item.title:'未保存草稿',text:item.text}]:[];
 });
}
