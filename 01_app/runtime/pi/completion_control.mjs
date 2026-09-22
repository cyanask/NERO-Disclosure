// Internal closing messages stay distinct from actual user instructions.
export function controlMessage(content, purpose) {
  return {role:'user',content,timestamp:Date.now(),runtime_control:purpose};
}
