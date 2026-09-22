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
