import type {PiRun} from '../chat';

/** One round's timings and retrieval counters; a collapse that only reads the run. */
export default function RunTimings({run}:{run:PiRun}){
 const seconds=(value?:number)=>(value||0)/1000;
 return <details className="chat-tool-receipts"><summary>本轮耗时与检索</summary><p>总耗时 {seconds(run.timings?.total_ms).toFixed(1)} 秒 · 需求分流 {seconds(run.timings?.routing_ms).toFixed(1)} 秒 · 正式模型调用 {seconds(run.timings?.business_model_ms).toFixed(1)} 秒 · 收尾答复 {seconds(run.timings?.closing_model_ms).toFixed(1)} 秒 · 工具执行 {seconds(run.timings?.tools_ms).toFixed(1)} 秒 · 结束清理 {seconds(run.timings?.cleanup_ms).toFixed(1)} 秒</p>{run.research_stats&&<p>检索 {run.research_stats.searches||0} 次 · 无新增匹配 {run.research_stats.empty_searches||0} 次 · 复用 {run.research_stats.cache_hits||0} 次 · 避免重复空查 {run.research_stats.suppressed_searches||0} 次</p>}</details>;
}
