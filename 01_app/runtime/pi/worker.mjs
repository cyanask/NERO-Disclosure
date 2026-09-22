import { Agent,convertToLlm } from '@earendil-works/pi-agent-core';
import { cleanupSessionResources } from '@earendil-works/pi-ai';
import {providerById,hydrateModel,providerRequestOptions,PI_VERSION} from './provider_runtime.mjs';
import {modelStream} from './model_transport.mjs';
import {conversationCheckpoint,createConversationCompactor} from './conversation_context.mjs';
import contract from '../../config/model-contract.json' with {type:'json'};
import { Type } from 'typebox';
import { createInterface } from 'node:readline';
import { setImmediate } from 'node:timers/promises';
import { pathToFileURL } from 'node:url';
import { createHash,randomUUID } from 'node:crypto';
import { brokerOptions } from './broker_compat.mjs';
import { publicProviderError } from './workflow_context.mjs';
import { trackWorkerTransports, flushStdout } from './worker_resources.mjs';
import { controlMessage } from './completion_control.mjs';

export function executionErrorMessage(error) {
  return '模型运行失败，请核对端点、凭据、模型或取消状态。';
}

// This worker owns one model round. Business state and tool effects belong to Python.
export async function execute(packet, emit, bridge, streamOverride, signal, releaseTransports, onControl, resolveAuth) {
  if (signal?.aborted) throw new Error('Cancelled before start');
  // A built-in provider owns its own transport (endpoint placeholders, headers, dynamic models).
  const provider = streamOverride ? undefined : providerById(packet.model.provider);
  packet={...packet,model:hydrateModel(packet.model,provider,packet.providerEnv)};
  const streamFn = streamOverride || await modelStream(packet.model,provider);
  const requestStream=async(model,context,options)=>{
    await setImmediate(); // Let cancellation/steering reach even an immediately resolving provider.
    if(signal?.aborted)throw new Error("Cancelled");
    if(packet.refresh_auth&&resolveAuth){
      const auth=await resolveAuth();
      if(auth.provider!==packet.model.provider||auth.model!==packet.model.id)throw new Error('Authorization no longer belongs to the selected model');
      packet.apiKey=auth.apiKey;packet.headers=auth.headers||{};packet.providerEnv=auth.env||{};
      if(auth.baseUrl)model={...model,baseUrl:auth.baseUrl};
    }
    const request=providerRequestOptions(model,brokerOptions(model,{...options,apiKey:packet.apiKey,headers:packet.headers||{},env:packet.providerEnv||{}}));
    const onPayload=request.onPayload;
    request.onPayload=async(payload,requestModel)=>{
      const transformed=await onPayload?.(payload,requestModel);
      const wire=transformed===undefined?payload:transformed;
      emit({type:'model_tool_surface',tools:(wire.tools||[]).map(t=>t.function?.name||t.name).filter(Boolean)});
      return wire;
    };
    return streamFn(model,context,request);
  };
  const checkpoint=conversationCheckpoint(packet);
  const compactConversation=createConversationCompactor(packet,async(model,context,options)=>{
    return requestStream(model,context,options);
  },emit,checkpoint);
  let turns = 0, calls = 0, messageNumber = 0;
  let finalizationRequested = false, closing = false, closingTurns = 0, sealed = false;
  let pendingContext;
  let stage = packet.stage || '';
  let started = false, activeCall, pendingDone;
  const executedToolIds = new Set();
  const finishModelCall = (stopReason, usage) => {
    if (!activeCall) return;
    const {startedAt, ...publicCall} = activeCall;
    activeCall = undefined;
    emit({type:'model_call_finished', ...publicCall, elapsed_ms:Math.round(performance.now()-startedAt), stopReason, usage});
  };
  const makeTools = specs => specs.map(spec => ({
    name: spec.name, label: spec.name, description: spec.description,
    parameters: Type.Unsafe(spec.parameters),
    execute: async (id, args) => {
      executedToolIds.add(id);
      if (sealed) return {content:[{type:'text',text:'本轮业务执行已结束，请根据已登记结果答复。'}],details:{},terminate:true};
      calls++;
      if (signal?.aborted) throw new Error('Cancelled');
      const result = await bridge(id, spec.name, args);
      if (result.next_context) pendingContext=result.next_context;
      if (result.terminate && !result.next_context) {
        sealed = true;
        agent.clearAllQueues();
        for(const id of queuedMessages.keys())emit({type:'user_message_not_applied',id,message:'本轮已到人工确认或结束边界，请重新发送追加消息。'});
        queuedMessages.clear();
        finalizationRequested = !!result.finalize;
      }
      return { content: [{ type: 'text', text: JSON.stringify(result.data) }],
        details: {}, ...(result.terminate && !result.next_context ? { terminate: true } : {}) };
    },
  }));
  const tools=makeTools(packet.tools);
  const queuedMessages=new Map();
  const agent = new Agent({
    convertToLlm,
    transformContext:async(messages,turnSignal)=>{
      const compacted=await compactConversation({messages,systemPrompt:agent.state.systemPrompt,tools:agent.state.tools},turnSignal);
      if(compacted!==messages){
        // Update both the loop's context and public Agent state; the next tool
        // turn must start from the same compacted transcript that was sent.
        messages.splice(0,messages.length,...compacted);agent.state.messages=compacted;
      }
      return messages;
    },
    prepareNextTurnWithContext: ({context}) => {
      if(!pendingContext)return;
      let updated={...context};
      if (pendingContext) {
        const next=pendingContext;pendingContext=undefined;
        stage = next.stage ?? stage;
        updated={...updated,systemPrompt:next.system,tools:makeTools(next.tools)};
        agent.state.systemPrompt=updated.systemPrompt;agent.state.tools=updated.tools;
        emit({type:"phase_started",stage,system_sha256:next.system_sha256,model:packet.model.id,provider:packet.model.provider,reasoning_effort:packet.reasoning_effort||"off"});
      }
      return {context:updated};
    },
    initialState: { systemPrompt: packet.system, model: packet.model, messages: packet.history || [],
      thinkingLevel: packet.reasoning_effort || 'off', tools },
    streamFn: async (model, context, options) => {
      if (closing && ++closingTurns > 1) throw new Error('Closing reply requested another model turn');
      turns++;
      const effort = packet.reasoning_effort ?? 'off';
      const maxTokens = packet.maxTokens ?? model.maxTokens ?? contract.defaults.maxTokens;
      activeCall = {call:turns,phase:closing?'final':'working',stage,reasoning_effort:effort,maxTokens,startedAt:performance.now()};
      const {startedAt, ...publicCall} = activeCall;
      emit({type:'model_call_started', ...publicCall, tools:context.tools.map(t=>t.name)});
      try {
        return await requestStream(model,context,{...options,reasoning:effort,maxTokens});
      } catch (error) {
        finishModelCall(signal?.aborted?'aborted':'error');
        if (!signal?.aborted) emit({type:'provider_failure',stage,phase:closing?'final':'working',stopReason:'error',message:publicProviderError(error.message,packet)});
        throw error;
      }
    },
    sessionId: packet.session_id,
    getApiKey: () => packet.apiKey,
  });
  const abort = () => agent.abort();
  onControl?.({enqueue:input=>{
    if(sealed||closing||signal?.aborted){emit({type:'user_message_not_applied',id:input.id,message:'本轮已进入收尾或人工确认，请在结束后重新发送。'});return;}
    if(!['steer','follow_up'].includes(input.mode)||typeof input.text!=='string'||!input.text.trim())return;
    if(queuedMessages.has(input.id))return;
    const message={role:'user',content:input.text,timestamp:Date.now(),request_id:input.id};
    queuedMessages.set(input.id,message);
    input.mode==='steer'?agent.steer(message):agent.followUp(message);
  }});
  signal?.addEventListener('abort', abort, { once: true });
  agent.subscribe(event => {
    if(event.type==='message_end'&&event.message.role==='user'&&queuedMessages.has(event.message.request_id)){
      queuedMessages.delete(event.message.request_id);
      emit({type:'user_message_delivered',id:event.message.request_id,text:event.message.content});
    }
    if(event.type==='turn_end')checkpoint(agent.state.messages);
    if (event.type === 'agent_start' && !started) {started=true;emit({ type: 'started', engine: 'pi-agent-core', version: PI_VERSION,
      model: packet.model.id, provider: packet.model.provider, api: packet.model.api,
      reasoning_effort:packet.reasoning_effort||'off',
      system_sha256: createHash('sha256').update(packet.system).digest('hex') });}
    if (event.type === 'tool_execution_end') {
      const executed = executedToolIds.delete(event.toolCallId);
      if (event.isError && !executed) {
        // Pi appends full arguments to schema errors. Keep the diagnostic only;
        // never serialize arguments, private reasoning or provider credentials.
        const error = (event.result?.content || []).filter(item=>item.type==='text').map(item=>item.text).join('\n').split('\n\nReceived arguments:')[0].slice(0,2000);
        emit({type:'tool_validation_failed',phase:'working',stage,tool:event.toolName,error});
      }
    }
    if (event.type === 'message_update' && event.assistantMessageEvent.type === 'text_delta') {
      emit({ type: 'text_delta', message: messageNumber, phase:closing?'final':'working', delta: event.assistantMessageEvent.delta });
    }
    if (event.type === 'message_end' && event.message.role === 'assistant') {
      const m = event.message;
      const usage = m.usage ? Object.fromEntries(Object.entries(m.usage).filter(([key]) => ['input','output','cacheRead','cacheWrite','totalTokens'].includes(key))) : undefined;
      finishModelCall(m.stopReason, usage);
      if (m.stopReason === 'error' || m.stopReason === 'length') emit({type:'provider_failure',stage,phase:closing?'final':'working',stopReason:m.stopReason,message:publicProviderError(m.errorMessage || (m.stopReason==='length'?'Provider output limit reached':agent.state.errorMessage),packet)});
      // Never serialize private reasoning, provider payloads or headers.
      emit({ type: 'assistant', message: messageNumber++, text: m.content.filter(x => x.type === 'text').map(x => x.text).join(''),
        phase:closing?'final':m.content.some(x=>x.type==='toolCall')?'progress':'answer',
        stopReason: m.stopReason, usage, pricing: 'not_configured', provider: m.provider, model: m.model });
    }
  });
  const checkCompletion = () => {
    const last = [...agent.state.messages].reverse().find(x => x.role === 'assistant');
    if (signal?.aborted || last?.stopReason === 'aborted') throw new Error('Cancelled');
    if (agent.state.errorMessage || last?.stopReason === 'error') throw new Error('Provider failed; verify endpoint, credentials and model configuration');
    if (last?.stopReason === 'length') throw new Error('Provider output limit reached');
    return last;
  };
  try {
    await agent.prompt(packet.prompt);
    checkCompletion();
    // Native Pi owns tool selection and the next turn. Missing business receipts
    // are reported by the host; they do not create a second prompt/retry loop.
    if (finalizationRequested) {
      closing = true;
      agent.state.tools = [];
      emit({type:'finalization_started'});
      try {
        await agent.prompt(controlMessage('本轮业务执行已结束，工具已关闭。完整登记分析、文件正文和待办已由对话界面展示。请只用200字以内说明当前完成范围、最重要的未完成事项和用户下一步；不得重复已展示的正文、表格、问题清单、原文或检索过程，不输出JSON。不另作业务判断，不宣称人工已经批准，明确待确认或待补状态。','finalization'));
        const final = [...agent.state.messages].reverse().find(x=>x.role==='assistant');
        if (agent.state.errorMessage || final?.stopReason!=='stop' || !final?.content.some(x=>x.type==='text'&&x.text.trim())) throw new Error('Closing reply incomplete');
        emit({type:'finalization_completed'});
      } catch {
        emit({type:'finalization_failed',message:'业务结果已保存，收尾答复未完成；请查看本轮已登记分析。'});
      }
    }
    pendingDone = { type: 'done', turns, calls };
  } finally {
    for(const id of queuedMessages.keys())emit({type:'user_message_not_applied',id,message:'追加消息尚未执行，本轮已经结束；请重新发送。'});
    finishModelCall(signal?.aborted?'aborted':'error');
    signal?.removeEventListener('abort', abort);
    // Pi keeps Codex WebSockets alive for reuse. This process owns one round only;
    // release its session timer/socket so stdout can reach EOF after flushed output.
    const cleanupStartedAt = performance.now();
    try {
      try {cleanupSessionResources(packet.session_id);}
      finally {
        const resources=await releaseTransports?.();
        if(resources)emit(resources);
      }
    } catch (error) {
      emit({type:'session_cleanup',status:'failed',elapsed_ms:Math.round(performance.now()-cleanupStartedAt)});
      throw error;
    }
    emit({type:'session_cleanup',status:'completed',elapsed_ms:Math.round(performance.now()-cleanupStartedAt)});
    if (pendingDone) emit(pendingDone);
  }
}

async function main() {
  const lines = createInterface({ input: process.stdin, crlfDelay: Infinity });
  const pending = new Map(); const abort = new AbortController(); let launched = false, finished = false,control;const earlyMessages=[];
  const emit = event => process.stdout.write(JSON.stringify(event) + '\n');
  const cancel = () => { abort.abort(); for (const p of pending.values()) p.reject(new Error('Cancelled')); pending.clear(); };
  process.on('SIGTERM', cancel);
  lines.on('line', line => {
    let input; try { input = JSON.parse(line); } catch { return; }
    if (!launched) {
      launched = true;
      const releaseTransports=trackWorkerTransports();
      execute(input, emit, (id, name, args) => new Promise((resolve, reject) => {
        pending.set(id, { resolve, reject }); emit({ type: 'tool_call', id, name, args });
      }), undefined, abort.signal, releaseTransports,value=>{control=value;for(const message of earlyMessages)control.enqueue(message);earlyMessages.length=0;},()=>new Promise((resolve,reject)=>{
        const id='auth-'+randomUUID();pending.set(id,{resolve,reject});emit({type:'auth_request',id});
      })).catch(error => emit({ type: 'error', message: executionErrorMessage(error) }))
        .finally(async () => { finished = true; lines.close(); process.stdin.destroy(); await releaseTransports(); await flushStdout(); });
    } else if(input.type==='user_message'){
      if(control)control.enqueue(input);else earlyMessages.push(input);
    } else if(input.type==='auth_result'&&pending.has(input.id)){
      const p=pending.get(input.id);pending.delete(input.id);input.error?p.reject(new Error('Provider authorization failed')):p.resolve(input.auth);
    } else if (input.type === 'tool_result' && pending.has(input.id)) {
      const p = pending.get(input.id); pending.delete(input.id);
      input.error ? p.reject(new Error(input.error)) : p.resolve(input);
    }
  });
  lines.on('close', () => { if (!finished) cancel(); });
}
if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) await main();
