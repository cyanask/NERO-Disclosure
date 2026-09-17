// Match NERO Banker provider_adapters.mjs: OpenCodex owns Google authorization.
export const BROKER_PROVIDER = 'nero-opencodex-loopback';
export const BROKER_BASE_URL = 'http://127.0.0.1:10100/v1';

export function brokerOptions(model, options) {
  if (model.provider !== BROKER_PROVIDER) return options;
  if (model.api !== 'openai-responses' || model.baseUrl !== BROKER_BASE_URL) {
    throw new Error('Unregistered Gemini broker route');
  }
  return {...options, onPayload: async (payload, requestModel) => {
    const transformed = await options.onPayload?.(payload, requestModel);
    const next = {...(transformed === undefined ? payload : transformed)};
    delete next.max_output_tokens;
    delete next.service_tier;
    return next;
  }};
}
