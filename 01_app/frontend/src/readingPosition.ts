const blocks='p,h1,h2,h3,h4,li,tr';
export interface ReadingPosition {messageId?:string;runId?:string;blockIndex:number;delta:number;relative:number;scrollTop?:number}
function readingLine(panel:HTMLElement){return panel.getBoundingClientRect().top+(panel.querySelector<HTMLElement>('.chat-heading')?.offsetHeight||0)+16;}

export function captureReadingPosition(panel:HTMLElement,messages:HTMLElement):ReadingPosition|undefined{
 const line=readingLine(panel),rect=messages.getBoundingClientRect();
 if(line<rect.top||line>=rect.bottom)return;
 const block=Array.from(messages.querySelectorAll<HTMLElement>(blocks)).find(e=>{const r=e.getBoundingClientRect();return r.height>0&&r.width>0&&r.bottom>line;});
 const owner=block?.closest<HTMLElement>('[data-message-id],[data-run-id]');
 return {...(panel===messages?{scrollTop:panel.scrollTop}:{}),messageId:owner?.dataset.messageId,runId:owner?.dataset.runId,blockIndex:owner&&block?Array.from(owner.querySelectorAll(blocks)).indexOf(block):0,delta:block?block.getBoundingClientRect().top-line:0,relative:line-rect.top};
}

export function restoreReadingPosition(panel:HTMLElement,messages:HTMLElement,position?:ReadingPosition){
 const line=readingLine(panel);
 const owner=position&&Array.from(messages.querySelectorAll<HTMLElement>('[data-message-id],[data-run-id]')).find(e=>position.messageId?e.dataset.messageId===position.messageId:e.dataset.runId===position.runId);
 const block=owner?.querySelectorAll<HTMLElement>(blocks)[position?.blockIndex||0];
 if(panel===messages&&!(block&&block.getBoundingClientRect().height>0)){panel.scrollTo({top:position?.scrollTop||0,behavior:'instant' as ScrollBehavior});return;}
 const target=block&&block.getBoundingClientRect().height>0?block.getBoundingClientRect().top-(position?.delta||0):messages.getBoundingClientRect().top+(position?.relative||0);
 panel.scrollTo({top:panel.scrollTop+target-line,behavior:'instant' as ScrollBehavior});
}
