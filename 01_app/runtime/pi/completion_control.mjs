// Internal recovery is scoped to the currently exposed tools, never a new user request.
export function completionInstruction(stage, tools, routing = false) {
  const names = tools.map(tool => tool.name);
  const has = name => names.includes(name);
  let action;
  if (routing && has('route_request')) action = '分流尚未登记，请调用 route_request，按实际参数错误修正。';
  else if (stage === 'document_preflight' && has('assess_document_readiness')) action = '起草前核对尚未登记，请调用 assess_document_readiness。读取当前资料并登记具体缺口；用户已明确要求缺项留空或标注待补时，按核对合同登记该选择并继续。不要仅在聊天中列问题或编造登记编号。';
  else if (stage === 'announcement' && has('save_announcement')) action = '公告正文尚未保存，请调用 save_announcement 保存完整文稿。';
  else if (stage === 'document' && has('make_word')) action = 'Word 尚未生成，请调用 make_word；以当前文稿和已接受的缺口处理方式完成文件。';
  else if (stage === 'lifecycle' && has('lifecycle_submit')) action = '法规核验尚未登记，请调用 lifecycle_submit；来源不足时登记 unavailable 或 uncertain。';
  else if (has('submit_candidate')) action = '业务判断尚未登记，请调用 submit_candidate 提交本节点结果。' + (has('request_information') ? '确实缺少关键资料时调用 request_information。' : '');
  else if (has('assess_document_readiness')) action = '请调用 assess_document_readiness 重新核对当前资料与缺口。';
  else return null;
  return '【系统内部执行纠偏，不是用户追加要求】' + action + '当前可用工具：' + names.join('、') + '。仅使用本轮实际工具；未完成只说明真实故障，不重复要求用户选择，不把制稿等同于签发或审批。';
}

export function controlMessage(content, purpose) {
  return {role:'user',content,timestamp:Date.now(),runtime_control:purpose};
}
