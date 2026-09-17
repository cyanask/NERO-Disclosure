import {Button} from 'antd';
import type {RefObject} from 'react';
import type {PiRun} from '../chat';
import {EvidencePanel} from './ExecutionEvidence';

/** Inline execution record for one round; the console keeps the open/close state. */
export default function RunAuditPanel({run,companyCode,open,anchor,onClose}:{run:PiRun;companyCode:string;open:boolean;anchor:RefObject<HTMLElement>;onClose:()=>void}){
 if(!open)return null;
 return <section ref={anchor} className="inline-panel" aria-label="本轮执行记录"><Button onClick={onClose}>收起执行记录</Button><EvidencePanel key={run.id} sessionId={run.session_id} board={run.board} company={companyCode} initialRunId={run.id}/></section>;
}
