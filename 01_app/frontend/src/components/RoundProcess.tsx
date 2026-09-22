import {useEffect,useState} from 'react';
import type {PiRun,Receipt} from '../chat';
import {live} from '../chat';
import {totalTiming} from '../runTimingValues';
import {currentProcessText,elapsedLabel} from '../conversationPresentation';
import MessageMarkdown from './MessageMarkdown';

export default function RoundProcess({run,rows}:{run:PiRun;rows:Receipt[]}){
 const [now,setNow]=useState(Date.now),running=live(run);
 useEffect(()=>{setNow(Date.now());if(!running)return;const timer=window.setInterval(()=>setNow(Date.now()),1000);return()=>window.clearInterval(timer);},[run.id,running]);
 const timing=totalTiming(run,now),text=currentProcessText(run,rows);
 const label=timing.milliseconds===null?'处理用时未记录':`${running?(run.status==='cancelling'?'正在停止 · 已用':'正在思考 · 已用'):'已处理'} ${elapsedLabel(timing.milliseconds)}`;
 return <div className="round-process">
  <p className="round-elapsed" aria-live="off" title="本轮处理总用时，包含模型、工具执行与等待时间。">{label}</p>
  {text&&<div className="round-process-text" aria-label="中文过程说明" aria-live="polite" aria-atomic="true"><MessageMarkdown text={text}/></div>}
 </div>;
}
