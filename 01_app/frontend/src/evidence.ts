export type SourceItem={key:string;id:string;category:string;title:string;article?:string;instrument_id?:string;version?:string;sha256?:string;effective_from?:string;url?:string;published_at?:string;decision_number?:string;stock_code?:string;states:string[];pages:number[];run_ids:string[]};
export type EvidenceGroup={key:string;label:string;items:SourceItem[];searched:boolean;empty_search:boolean;failed:boolean;unavailable:boolean;incomplete:boolean;initiated_actions?:string[];checks:{performed:boolean;method:string;scope:string;count:number;run_id:string;fingerprint?:string;fields:string[];coverage?:{from?:string;through?:string};items:{id:string;title:string;published_at?:string}[]}[]};
export type EvidenceSummary={session_id:string;title:string;board:string;company:string;scope:string;run_id:string;status:string;live:boolean;legacy:boolean;unresolved_citations:number;unclassified_failures?:number;notice:string;groups:EvidenceGroup[];runs:{id:string;stage:string;status:string;created:number}[]};
export const evidenceState=(item:SourceItem)=>['used','cited','read','matched','provided','searched'].find(s=>item.states.includes(s))||'searched';
export const evidenceLabels:Record<string,string>={used:'已采用',cited:'已引用',read:'已查阅',matched:'已匹配，未采用',provided:'已提供正文',searched:'仅检索到'};
export const sourceUrl=(url?:string)=>{try{const u=new URL(url||'');return ['https:','http:'].includes(u.protocol)&&!u.username?u.href:undefined;}catch{return undefined;}};
export function sourceLines(items:SourceItem[]){
 const lines=new Map<string,{item:SourceItem;articles:string[]}>();
 for(const item of items){
  const key=item.category==='laws'&&item.article?JSON.stringify([item.instrument_id||item.title,item.title,item.sha256,item.version||item.effective_from,evidenceState(item),item.url]):item.key;
  const line=lines.get(key)||{item,articles:[]};
  if(item.article&&!line.articles.includes(item.article))line.articles.push(item.article);
  lines.set(key,line);
 }
 return [...lines.values()];
}
