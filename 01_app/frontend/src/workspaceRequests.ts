import {api} from './api';
import type {DisclosureEvent} from './types';
import type {DocumentListing} from './components/DeliveryTable';

/** One view generation. Navigation invalidates every read from the prior view. */
export class ViewRequests{
 generation=0;
 private controller=new AbortController();
 invalidate(){this.controller.abort();this.controller=new AbortController();this.generation+=1;}
 capture(){const generation=this.generation;return {signal:this.controller.signal,current:()=>generation===this.generation};}
}
export function readEvents(board:string,company:string,signal?:AbortSignal){
 return api<DisclosureEvent[]>(`/events?board=${board}&company=${company}`,'GET',undefined,{signal});
}
export async function readDeliverySources(board:string,company:string,signal?:AbortSignal){
 const [events,documents]=await Promise.allSettled([
  readEvents(board,company,signal),api<DocumentListing>(`/documents?board=${board}&company=${company}`,'GET',undefined,{signal})
 ]);
 signal?.throwIfAborted();
 return {events,documents};
}
