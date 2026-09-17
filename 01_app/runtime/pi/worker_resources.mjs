import { channel } from 'node:diagnostics_channel';

function resourceCounts() {
  const counts={};
  for (const type of process.getActiveResourcesInfo()) counts[type]=(counts[type] || 0)+1;
  return counts;
}

export function flushStdout() {
  return new Promise((resolve,reject)=>process.stdout.write('',error=>error?reject(error):resolve()));
}

// CLI-only lifetime: one worker process owns one round. Subscribe before any
// provider call; track only client connections created/used by this worker.
export function trackWorkerTransports() {
  const sockets=new Set();
  const remember=socket=>{if(socket && typeof socket.destroy==='function')sockets.add(socket);};
  const undici=channel('undici:client:connected');
  const http=channel('http.client.request.start');
  const onUndici=message=>remember(message.socket);
  const onHttp=message=>{
    if (message.request?.socket) remember(message.request.socket);
    else message.request?.once('socket',remember);
  };
  undici.subscribe(onUndici);http.subscribe(onHttp);
  let released=false;
  return async () => {
    if(released)return;
    released=true;
    undici.unsubscribe(onUndici);http.unsubscribe(onHttp);
    // Preserve every text/tool receipt before touching the transport. In
    // particular, never substitute process.exit() for stdout completion.
    await flushStdout();
    const startedAt=performance.now(),before=resourceCounts();
    const pending=[...sockets].filter(socket=>!socket.destroyed);
    let closedSockets=0;
    const closed=pending.map(socket=>new Promise(resolve=>{
      socket.once('close',()=>{closedSockets++;resolve();});
      socket.destroy();
    }));
    let timeout;
    try {
      await Promise.race([Promise.all(closed),new Promise(resolve=>{timeout=setTimeout(resolve,250);})]);
    } finally {clearTimeout(timeout);}
    return {type:'transport_cleanup',before,after:resourceCounts(),tracked_sockets:sockets.size,
      destroyed_sockets:pending.length,closed_sockets:closedSockets,remaining_sockets:[...sockets].filter(socket=>!socket.destroyed).length,
      elapsed_ms:Math.round(performance.now()-startedAt)};
  };
}
