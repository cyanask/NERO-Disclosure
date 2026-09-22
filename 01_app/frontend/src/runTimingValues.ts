/** Pure display policy. Wall time is never reconstructed by summing phases. */
export type TimingRun = {
 status: string;
 created: number;
 timings?: Record<string, number>;
};

export function recordedMilliseconds(value: number | undefined): number | null {
 return typeof value === 'number' && Number.isFinite(value) && value >= 0 ? value : null;
}

export function totalTiming(run: TimingRun, nowMilliseconds: number) {
 const running = ['accepted', 'running', 'cancelling'].includes(run.status);
 if (running) {
  const elapsed = nowMilliseconds - run.created * 1000;
  // created is the acceptance time, not the worker start: label this as waiting.
  const valid = Number.isFinite(run.created) && run.created > 0 && Number.isFinite(elapsed) && elapsed >= 0;
  return {live: true, label: '已等待', milliseconds: valid ? elapsed : null};
 }
 return {live: false, label: '总耗时', milliseconds: recordedMilliseconds(run.timings?.total_ms)};
}

export function timingSeconds(value: number | null): string {
 return value === null ? '尚未记录' : `${(value / 1000).toFixed(1)} 秒`;
}
