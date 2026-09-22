import {useEffect, useState} from 'react';
import type {PiRun} from '../chat';
import {recordedMilliseconds, timingSeconds, totalTiming} from '../runTimingValues';

/** Read-only, live elapsed time; unknown measurements are not zero seconds. */
export default function RunTimings({run}: {run: PiRun}) {
 const [now, setNow] = useState(() => Date.now());
 const running = ['accepted', 'running', 'cancelling'].includes(run.status);
 useEffect(() => {
  setNow(Date.now());
  if (!running) return;
  const timer = window.setInterval(() => setNow(Date.now()), 1000);
  return () => window.clearInterval(timer);
 }, [run.id, running]);
 const total = totalTiming(run, now);
 const phase = (key: string) => timingSeconds(recordedMilliseconds(run.timings?.[key]));
 return <details className="chat-tool-receipts"><summary>本轮耗时与检索</summary>
  <p>{total.label} {timingSeconds(total.milliseconds)}{total.live ? '（执行中，含启动等待）' : ''} · 需求分流 {phase('routing_ms')} · 正式模型调用 {phase('business_model_ms')} · 收尾答复 {phase('closing_model_ms')} · 工具执行 {phase('tools_ms')} · 结束清理 {phase('cleanup_ms')}</p>
  {run.research_stats && <p>检索 {run.research_stats.searches || 0} 次 · 无新增匹配 {run.research_stats.empty_searches || 0} 次 · 复用 {run.research_stats.cache_hits || 0} 次 · 避免重复空查 {run.research_stats.suppressed_searches || 0} 次</p>}
 </details>;
}
