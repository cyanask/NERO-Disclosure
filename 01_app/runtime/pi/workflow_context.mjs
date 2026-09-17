// Start each business node from its authoritative server context.  Only a
// same-node revision retains the last rejected candidate and its validation.
export function createWorkflowCompactor(originalUserMessages) {
  return (messages, latestUnadoptedCandidate, reason) => {
    const textOnly = content => typeof content === 'string' || (Array.isArray(content) && content.every(item=>item.type==='text'));
    if (!originalUserMessages.every(message=>textOnly(message.content)) ||
        messages.some(message=>message.role==='toolResult' && !textOnly(message.content))) return;
    if (reason === 'stage_transition') return [...originalUserMessages,{role:'user',timestamp:Date.now(),content:
      '【系统节点交接】上一节点已登记。事实、依据和最新业务状态已在当前系统上下文中；不从历史对话重建。'}];
    if (!latestUnadoptedCandidate) return originalUserMessages.slice();
    return [...originalUserMessages,{role:'user',timestamp:Date.now(),content:
      '【系统修订交接】以下是本节点最新未通过候选和校验问题。它不代表人工批准；只修正列明问题，事实和依据以当前系统上下文为准。\n'+JSON.stringify(latestUnadoptedCandidate)}];
  };
}

export function publicProviderError(value, packet) {
  let text = String(value || 'Provider returned an error').split('\n\nReceived arguments:')[0];
  for (const secret of [packet.apiKey,...Object.values(packet.headers || {})]) {
    if (typeof secret === 'string' && secret) text = text.split(secret).join('[REDACTED]');
  }
  text = text
    .replace(/\bBearer\s+\S+/gi,'Bearer [REDACTED]')
    .replace(/\bsk-[\w-]+/gi,'[REDACTED]')
    .replace(/\beyJ[\w-]+\.[\w-]+(?:\.[\w-]+)?/g,'[REDACTED]')
    .replace(/(?:["']?)(?:api[_-]?key|authorization|access[_-]?token|refresh[_-]?token|token|headers?|thinking|reasoning)(?:["']?)\s*[:=]\s*[^\r\n]*/gi,'[REDACTED FIELD]')
    .replace(/\s+/g,' ').trim();
  return text.slice(0,800);
}
