export type Board={id:string;name:string;fullName:string;layer:'base'|'innovation'|'chinext'};
export type Company={board:Board['layer'];board_name:string;company_name:string;stock_code:string;verification?:CompanyResult|null};
export type CompanyResult={status:'verified'|'needs_review';board?:string;board_name?:string;available?:boolean;reason:string;checked_at?:string;run_id?:string;sources:{url:string;quote:string;page:number;download_id:string}[]};
export type CompanyWorkspace={company:Company|null;companies:Company[]};
export const companyBoard=(company:Company):Board=>({id:company.board,layer:company.board,name:company.board_name,fullName:company.board_name});
export function legacyCompany(workspace:CompanyWorkspace,raw:string|null):Company|undefined{
 if(workspace.company||!raw)return;
 try{const saved=JSON.parse(raw);return workspace.companies.find(c=>c.board===saved.boardId&&c.stock_code===saved.companyCode);}catch{return;}
}
export function eventsForCompany<T extends {layer:string;stock_code?:string}>(events:T[],company:Company):T[]{
 return events.filter(event=>event.layer===company.board&&event.stock_code===company.stock_code);
}
