"""Read-only completion/capability projections, never approval or production authority.

A missing tool in the preflight tool surface is not an unavailable renderer.
These projections describe the existing server gate and current-round receipts;
Authored documents still pass document_preflight.enforce; bound-reply rendering
retains its existing source ownership and hash checks before the file writer.
"""


def document_capability(run):
    """Describe the current run, not the prior round's consent or a model claim."""
    stage = run.get('stage')
    tool = {'document': 'make_word', 'announcement': 'save_announcement'}.get(stage)
    if tool is None:
        return {'state': 'not_document_task', 'production_allowed': False,
                'next_tool': None, 'expected_result': None}
    plan = run.get('document_preflight') or {}
    expected = 'registered_docx' if stage == 'document' else 'registered_text'
    fingerprint = run.get('document_context_sha256')
    current = bool(fingerprint) and plan.get('input_fingerprint') == fingerprint
    allowed = plan.get('status') in ('ready', 'authorized') and current
    outcome = run.get('outcome')
    if outcome:
        state = 'waiting_user' if outcome == 'waiting_user' else 'round_closed'
        detail = '本轮已经暂停或结束，以实际登记结果为准；不重新开放写入。'
        next_tool = None
        allowed = False
    elif stage == 'document' and run.get('document_action') == 'render':
        allowed = bool(run.get('reply_source'))
        state = 'ready' if allowed else 'reply_source_required'
        next_tool = tool if allowed else None
        detail = ('源回复已绑定；只排版并取得文件登记回执，不重新起草。' if allowed
                  else '尚未绑定本轮要转为 Word 的已展示回复，不能以聊天文字代替文件登记。')
    elif allowed:
        state, next_tool = 'ready', tool
        detail = '当前核对记录有效；须调用生产工具并取得登记回执，聊天正文不代表文件已生成。'
    elif plan.get('status') == 'repair_evidence':
        state, next_tool = 'evidence_repair', 'assess_document_readiness'
        detail = '依据定位需要修正；修正后重新登记核对。不是 Word 引擎不可用。'
    elif plan.get('status') == 'waiting_choice':
        state, next_tool = 'preflight_required', 'assess_document_readiness'
        detail = '须核对本轮消息与已有缺口提醒；旧提醒不自动成为本轮授权。'
    elif plan and not current:
        state, next_tool = 'input_changed', 'assess_document_readiness'
        detail = '当前输入与核对记录不一致，须重新核对；不沿用过期权限。'
    else:
        state, next_tool = 'preflight_required', 'assess_document_readiness'
        detail = '制文工具已按信披范围开放；保存文件前仍须核对具体文稿、资料缺口和用户要求。'
    return {'state': state, 'production_allowed': allowed, 'production_tool': tool,
            'next_tool': next_tool, 'expected_result': expected,
            'renderer_health': 'not_probed', 'detail': detail}


def journal_rows(store, rid):
    """Consume the existing paginated journal, including a late final answer."""
    cursor = 0
    while True:
        rows = store.journal(rid, after=cursor)
        yield from rows
        if not rows:
            return
        cursor = rows[-1]['seq']


def current_answer(run, rows):
    """Require this round's LAST assistant message to be a finished visible answer.

    An earlier answer, tool-use prose, a delta, or an empty final response cannot
    stand in for this turn. Missing metadata is not silently interpreted as stop.
    """
    messages = [row for row in rows if row.get('run_id') == run.get('id')
                and row.get('kind') == 'assistant']
    if not messages:
        return False
    body = messages[-1].get('body') or {}
    text = body.get('text')
    return (body.get('stopReason') == 'stop' and body.get('phase') != 'progress'
            and isinstance(text, str) and bool(text.strip()))


def settle_without_outcome(run, rows):
    """Only for the no-outcome, non-cancelled branch of PiRuntime.work.

    Saved files/confirmed choices retain their existing authoritative outcome
    handling, even when the later closing reply fails. This helper never changes
    business state or replays tools.
    """
    own = [row for row in rows if row.get('run_id') == run.get('id')]
    incomplete = run.get('completion_complete') is False or any(
        row.get('kind') == 'completion_incomplete'
        or row.get('kind') == 'done' and (row.get('body') or {}).get('completion_complete') is False
        for row in own)
    if run.get('provider_error'):
        return 'failed', '模型服务返回异常，本轮未完成；请查看执行记录，已有记录保留。'
    if run.get('controller_mode')=='native' and run.get('completed_actions') and not incomplete and current_answer(run,own):
        return 'completed','本轮答复及工具操作已返回；实际交付范围以已登记回执为准。'
    if run.get('stage') == 'chat':
        # Evidence findings are reminders: a delivered answer is never withheld or left unregistered.
        warnings = (run.get('consultation_result') or {}).get('warnings') or []
        if current_answer(run, own):
            if warnings:
                return 'completed', '本轮答复已展示；依据核验有 %d 项未通过，已作为提醒保留，不阻断答复。' % len(warnings)
            return 'completed', '本轮答复已返回；结论仍需结合所列依据和限制核对。'
        return 'incomplete', '本轮尚未返回可展示的答复；已有检索和执行记录保留。'
    if run.get('stage') == 'knowledge':
        if not incomplete and current_answer(run, own):
            return 'completed', '本轮答复已返回；结论仍需结合所列依据和限制核对。'
        return 'incomplete', '本轮尚未返回完整答复；已有检索和执行记录保留，未将仅检索或空答复标记为完成。'
    if run.get('stage') in ('document', 'announcement'):
        target = 'Word 文件' if run['stage'] == 'document' else '公告正文版本'
        capability = document_capability(run)
        # Report a real validation/tool failure before the generic missing step.
        failure = next((row for row in reversed(own) if row.get('kind') in
                        ('document_check_failed', 'tool_validation_failed', 'model_tool_failed', 'script_failed')), None)
        if failure:
            return 'incomplete', target + '尚未登记；本轮存在工具参数或执行检查错误，请查看最后一次错误并从该步骤修复。'
        if capability['state'] == 'ready':
            return 'incomplete', target + '尚未登记；核对已通过，但未取得生产工具的成功登记回执，聊天正文不等于文件。'
        return 'incomplete', target + '尚未登记；' + capability['detail']
    return 'incomplete', '本轮已结束，但尚未登记完整的工作结果。'
