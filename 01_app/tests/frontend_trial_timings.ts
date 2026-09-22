import assert from 'node:assert/strict';
import {totalTiming,recordedMilliseconds,timingSeconds} from '../frontend/src/runTimingValues';
const now=100000;
for (const status of ['accepted','running','cancelling']) {
 const view=totalTiming({status,created:20,timings:{routing_ms:61200,business_model_ms:4000}},now);
 assert.equal(view.milliseconds,80000);
 assert.equal(view.live,true);
 assert.equal(view.label,'已等待');
}
assert.equal(totalTiming({status:'running',created:20,timings:{total_ms:1000}},now).milliseconds,80000);
assert.equal(totalTiming({status:'completed',created:20,timings:{total_ms:83000}},now).milliseconds,83000);
assert.equal(totalTiming({status:'incomplete',created:20,timings:{routing_ms:61200}},now).milliseconds,null);
assert.equal(totalTiming({status:'failed',created:20,timings:{total_ms:0}},now).milliseconds,0);
assert.equal(totalTiming({status:'running',created:101},now).milliseconds,null);
assert.equal(totalTiming({status:'running',created:NaN},now).milliseconds,null);
assert.equal(totalTiming({status:'running',created:0},now).milliseconds,null);
for (const value of [undefined,NaN,Infinity,-1]) assert.equal(recordedMilliseconds(value),null);
assert.equal(recordedMilliseconds(0),0);
assert.equal(timingSeconds(null),'尚未记录');
assert.equal(timingSeconds(0),'0.0 秒');
assert.equal(timingSeconds(61200),'61.2 秒');
console.log('frontend_trial_timings: 24 assertions passed');
