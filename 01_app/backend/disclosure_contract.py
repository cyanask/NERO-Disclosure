"""Shared v2.1 checks. Legal applicability remains a visible professional review item."""
from decimal import Decimal, InvalidOperation
import re
from . import library

CONTRACT_VERSION = '2.5.0'


def scope(event):
    return {'case_id': event['id'], 'client_ref': event['company_id'], 'board': event['layer'],
            'company_name': event['company_name'], 'stock_code': event.get('stock_code'),
            'access': 'local_workspace' if event.get('intake_mode')=='open' else 'local_demo_workspace',
            'client_authorization': 'not_connected'}


def capabilities():
    return {
        'client_history': {'status': 'not_connected', 'coverage_as_of': None,
                           'message': '未接入客户历史公告服务；无结果不能解释为从未披露。'},
        'client_materials': {'status': 'not_connected', 'message': '仅能使用本事项输入；未接入授权附件或完整台账服务。'},
        'monitoring': {'status': 'not_connected', 'message': '需人工跟踪；本系统未启动后台监测或通知。'},
        'human_identity': {'status': 'local_self_reported', 'message': '产品内确认；不核验法定权限。'},
        'word': {'status': 'external_agent_demo', 'message': '复用现有模拟 Word 工具；渲染由宿主实际执行。'},
    }


def problem(code, detail, **metadata):
    return {'code': code, 'detail': detail, **metadata}


def unique(rows, key, errors):
    ids = [row[key] for row in rows]
    if len(set(ids)) != len(ids):
        errors.append(problem('duplicate_id', '编号重复：' + key))


def quoted_value_matches(value, quote):
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        # Compare complete numeric tokens; normalize grouping only, never units/scales.
        tokens = re.findall(r'(?<![\d.,])[-+]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?(?![\d.,])', quote)
        return any(Decimal(t.replace(',', '')) == Decimal(str(value)) for t in tokens)
    return str(value) in quote


def excerpt_in_source(quote, source_text):
    # PDF line wraps and spacing do not alter the cited legal wording.
    return re.sub(r'\s+', '', quote) in re.sub(r'\s+', '', source_text)


def evidence_context(text, quote, span=600):
    """Bounded original-text window around a locatable quote, for independent review."""
    index=text.find(quote)
    if index<0:
        return text[:span*2]
    return text[max(0,index-span):index+len(quote)+span]


def bind_summary_quote(summary, value):
    """Bind a user-statement fact to the sentence the user actually wrote.

    Only the user's own wording is reused; nothing is paraphrased or inferred.
    """
    if not isinstance(summary, str) or not summary.strip():
        return None
    # A bare number/boolean cannot identify what the sentence is about.
    if not isinstance(value, str) or len(value.strip()) < 2 or re.fullmatch(r'[\d.,%％+\-\s]+', value):
        return None
    matches = [s.strip() for s in re.split(r'(?<=[。；！？!?\n])', summary)
               if value.strip() in s]
    return matches[0] if len(matches) == 1 else None


def review_item(item_id, code, fact, source_ref, context, evidence_sha=None):
    return {'item_id':item_id,'code':code,'fact_key':fact['key'],'value':fact['value'],'quote':fact['quote'],
            'source_ref':source_ref,'context':context,'evidence_sha':evidence_sha,
            'detail':'事实值与原文引文需独立语义复核：'+fact['key']}


def resolve_review(item, review, review_items, errors):
    """A semantic doubt is not an error until the independent review rules on it."""
    verdict=(review or {}).get(item['item_id']) or {}
    kind=verdict.get('verdict')
    if not kind:
        if review is None:review_items.append(item)
        else:errors.append(problem('semantic_review_incomplete','独立语义复核未覆盖该项，不能据此通过：'+item['fact_key'],item_id=item['item_id']))
        return False
    if kind=='supported':return True
    if kind=='conflict':
        errors.append(problem('fact_value_conflict','独立语义复核认为事实值与原文矛盾：'+item['fact_key'],
                              item_id=item['item_id'],reason=str(verdict.get('reason',''))[:1000]))
    else:
        errors.append(problem('semantic_review_insufficient','独立语义复核证据不足，需补充材料：'+item['fact_key'],
                              item_id=item['item_id'],reason=str(verdict.get('reason',''))[:1000]))
    return False


def locator_matches(locator, article, source_text):
    if locator == article:
        return True
    if re.fullmatch(r'\d+(?:\.\d+)+', article):
        return re.findall(r'(?<![\d.])\d+(?:\.\d+)+(?![\d.])', locator) == [article]
    if re.fullmatch(r'第[一二三四五六七八九十百千万零〇两]+条', article):
        return re.findall(r'第[一二三四五六七八九十百千万零〇两]+条', locator) == [article]
    return locator.startswith(article) and excerpt_in_source(locator[len(article):].strip(), source_text)


def ratio_value(numerator, denominator, unit):
    value = numerator / denominator
    return value * 100 if unit.strip() in ('%', '％', '百分比') else value


def assessment_checks(event, catalog, result, history_reader=None, review=None):
    """Deterministic checks first; ambiguous value/quote differences go to independent review.

    `review=None` means no review has been attempted yet: unresolved items are returned as
    pending. `review={}` or a populated mapping means a review round already ran, so any
    uncovered item becomes a hard error and can never pass silently.
    """
    errors, warnings, review_items = [], [], []
    sources = {row['id']: row for row in catalog['sources']}
    facts = {f['key']: f for f in result.get('facts', [])}
    unique(result.get('facts', []), 'key', errors)
    unique(result.get('matters', []), 'matter_id', errors)
    # Both positive and negative conclusions, and every calculation, depend on
    # locatable inputs. A negative conclusion is not a lesser evidence claim.
    decisive = {key for matter in result.get('matters', []) for path in matter.get('reasoning_items', [])
                if path.get('outcome') in ('established', 'not_met') for key in path.get('fact_keys', [])}
    decisive.update(key for matter in result.get('matters', []) for calculation in matter.get('calculations', [])
                    for key in calculation.get('fact_keys', []))

    def record(code, detail, key, *, invalid_claim=False):
        if key in decisive or invalid_claim:
            errors.append(problem(code, detail))
        else:
            facts[key]['status'] = 'unknown'
            missing = result.setdefault('missing', [])
            if detail not in missing:
                missing.append(detail)
            warnings.append(problem('fact_pending_supplement', detail + '；已标为待核，保留缺口并继续不受影响的部分'))
    for fact in facts.values():
        if fact['status'] in ('unknown', 'conflicting', 'model_inference'):
            continue
        ref = fact['source_ref']
        history_supported=False
        if ref.startswith('facts.'):
            if fact['value'] != event['facts'].get(ref[6:]) or ref[6:] not in event['facts']:
                errors.append(problem('fact_source_mismatch', '事实与事项输入不符：' + fact['key']))
        elif ref == 'summary':
            if not fact['quote']:
                bound = bind_summary_quote(event.get('summary', ''), fact['value'])
                if bound:
                    fact['quote'] = bound
                    warnings.append(problem('fact_quote_bound', '已从事项说明自动绑定事实原句：' + fact['key']))
                else:
                    record('fact_source_mismatch', '自然语言事实缺少可定位原句：' + fact['key'], fact['key'])
            elif fact['quote'] not in event.get('summary', ''):
                record('fact_source_mismatch', '提交的事实引文不在事项说明中：' + fact['key'], fact['key'], invalid_claim=True)
            elif not quoted_value_matches(fact['value'], fact['quote']):
                item=review_item('fact:'+fact['key'],'summary_value_review',fact,ref,fact['quote'])
                resolve_review(item,review,review_items,errors)
        elif ref in ('scope.company_name','scope.stock_code','scope.board'):
            if fact['value'] != scope(event).get(ref[6:]):
                errors.append(problem('fact_source_mismatch', '事实与本次绑定主体不符：' + fact['key']))
        elif ref.startswith('announcement-') and history_reader:
            allowed={r['id']:r for r in catalog.get('client_history',{}).get('items',[])}
            try:
                if ref not in allowed:raise ValueError()
                original=history_reader(ref)
                text='\n'.join(p['text'] for p in original['pages'])
                if original['sha256']!=allowed[ref]['sha256'] or not fact['quote'] or not excerpt_in_source(fact['quote'],text):raise ValueError()
                history_supported=True
                if not quoted_value_matches(fact['value'],fact['quote']):
                    item=review_item('fact:'+fact['key'],'fact_value_review',fact,ref,
                                     evidence_context(text,fact['quote']),original['sha256'])
                    resolve_review(item,review,review_items,errors)
            except (ValueError,KeyError):
                record('history_fact_unlocatable','历史事实不能定位至本公司当前原件：'+fact['key'],fact['key'],
                       invalid_claim=bool(fact.get('quote')))
        else:
            errors.append(problem('fact_source_unavailable', '当前没有该资料读取接口：' + ref))
        if fact['status'] == 'material_supported' and not history_supported:
            record('material_not_connected', '未接入附件核验，不得把输入或模型整理冒充材料已核实', fact['key'])
    established = False
    undecided = False
    for matter_index,matter in enumerate(result.get('matters', [])):
        paths = matter['reasoning_items']
        known_path = False
        for path_index,path in enumerate(paths):
            source = sources.get(path['source_id'], {})
            if source.get('source_kind') not in ('official_rule', 'regulation', 'statute'):
                errors.append(problem('not_a_law', '义务判断路径须引用适用法规'))
            if path['source_id'] not in result['source_ids'] or not excerpt_in_source(path['quote'], source.get('text', '')):
                errors.append(problem('citation_unlocatable', '判断引文与绑定条款原文不一致', repair={'path':f'/matters/{matter_index}/reasoning_items/{path_index}/quote','source_id':path['source_id'],'instruction':'可删除quote由服务器绑定当前条款原文，或提交准确原句' if 0<len(source.get('text',''))<=10000 else '须提交准确的原文片段'}))
            if source.get('article') and not locator_matches(path['locator'], source['article'], source.get('text', '')):
                errors.append(problem('citation_locator_mismatch', '条款定位与真实来源不符'))
            elif source.get('article') and path['locator'] != source['article']:
                warnings.append(problem('citation_sublocator_review', '已核对所属条款及引文；款项或章节细分仍须结合原件复核'))
            keys = path['fact_keys']
            if set(keys) - facts.keys():
                errors.append(problem('fact_reference_missing', '判断引用了不存在的事实'))
            if path['outcome'] == 'not_met' and any(facts.get(k, {}).get('status') not in ('user_statement', 'material_supported') for k in keys):
                errors.append(problem('unknown_fact_as_negative', '条件不满足的结论不能依赖未知、冲突或推测事实'))
            if path['outcome'] == 'established':
                if any(facts.get(k, {}).get('status') not in ('user_statement', 'material_supported') for k in keys):
                    errors.append(problem('unknown_fact_as_true', '已成立路径不能依赖未知、冲突或推测事实'))
                else:
                    known_path = True
        if known_path and matter['duty_status'] != 'mandatory':
            errors.append(problem('independent_duty_lost', '已成立的独立义务不能被其他未知指标降为待判断'))
        if matter['duty_status'] == 'mandatory' and not known_path:
            errors.append(problem('duty_without_path', '强制披露结论缺少已成立的独立依据链'))
        established |= known_path
        unknown_path = any(path['outcome']=='unknown' for path in paths)
        if not known_path and (unknown_path or matter['decisive_questions']):
            undecided = True
            if matter['duty_status'] != 'undetermined':
                errors.append(problem('unknown_duty_as_no_disclosure', '决定性路径尚未知，不能归为无需披露或条件未触发'))
        undecided |= matter['duty_status'] == 'undetermined'
        if matter['duty_status'] != 'mandatory' and not matter['reassessment_conditions']:
            errors.append(problem('reassessment_conditions_missing', '非强制或未触发结论须保留复判条件'))
        if matter['timing_status'] == 'triggered' and (not matter['trigger_events'] or not matter['deadline_basis']):
            errors.append(problem('timing_basis_missing', '已触发时点须列触发事件和时限依据'))
        if set(matter['deadline_basis']) - set(result['source_ids']):
            errors.append(problem('timing_basis_missing', '时限依据必须来自本判断引用的规则'))
        history=catalog.get('client_history',{})
        history_ids={r['id'] for r in history.get('items',[])}
        if set(matter['historical_links'])-history_ids:
            errors.append(problem('history_not_connected','历史引用不在当前公司公告时间表中'))
        if matter['history_status']=='covered' and not history.get('coverage',{}).get('complete'):
            errors.append(problem('history_coverage_unknown','未确认完整覆盖，不能声称历史已全部核实'))
        if not history.get('coverage',{}).get('complete'):warnings.append(problem('history_coverage_unknown','历史仅覆盖已登记公告；不得据此断言不存在历史披露'))
        case_ids = {c['id'] for c in catalog.get('cases', []) if library.admitted_case(c, event['layer'])}
        if set(matter['comparable_cases']) - case_ids:
            errors.append(problem('case_not_admitted', '案例未接纳或不在绑定板块'))
        if matter['urgency'] != 'normal' or matter['specialist_required'] or matter['special_review'] == 'required':
            warnings.append(problem('manual_escalation', '紧急、专项或特殊处理须交人工；已识别义务仍保留'))
        for calculation in matter['calculations']:
            try:
                factual_sum = calculation.get('scope') == 'snapshot' and calculation['operation'] == 'sum' and calculation['basis_source_id'] == 'facts'
                if not factual_sum and calculation['basis_source_id'] not in result['source_ids']:
                    raise ValueError()
                if any(facts.get(k, {}).get('status') not in ('user_statement', 'material_supported') for k in calculation['fact_keys']):
                    raise ValueError()
                values = [Decimal(str(facts[k]['value'])) for k in calculation['fact_keys']]
                claimed = Decimal(calculation['result'])
                if not all(v.is_finite() for v in [*values, claimed]):
                    raise ValueError()
                if calculation['operation'] == 'ratio':
                    if len(values) != 2 or values[1] == 0:
                        raise ValueError()
                    actual = ratio_value(values[0], values[1], calculation['unit'])
                else:
                    actual = sum(values)
                if actual != claimed:
                    errors.append(problem('calculation_mismatch', '独立复算与提交结果不符'))
                if calculation.get('scope') != 'snapshot' and calculation['aggregation_basis'] in ('public_announcements', 'unknown'):
                    errors.append(problem('ledger_incomplete', '公开公告或未知范围不能替代完整累计台账'))
            except (InvalidOperation, ValueError, KeyError, ZeroDivisionError):
                errors.append(problem('calculation_invalid', '计算输入、口径依据或数值无效'))
    expected = 'disclose' if established else 'needs_info' if undecided else 'no_disclosure'
    if result.get('status') not in (expected, 'review_required'):
        errors.append(problem('conclusion_conflict', '总判断未保留逐事项义务状态'))
    if result.get('status') == 'review_required':
        warnings.append(problem('manual_escalation', '规则适用存在分歧，须人工处理'))
    if result.get('status') == 'needs_info' and not established:
        errors.append(problem('decisive_facts_missing', '决定性事实仍不足；保留候选问题并补充后复判'))
    if not result.get('matters'):
        errors.append(problem('assessment_contract_missing', '缺少 v2.1 逐事项判断合同'))
    preview = result.get('preliminary_plan')
    if preview:
        used = {sid for group in ('documents','requirements','drafting_gaps') for row in preview[group] for sid in row.get('source_ids', [])}
        if used - set(result['source_ids']):
            errors.append(problem('preliminary_source_unbound', '条件性文件依据未列入本次判断的版本核验范围'))
        extra, notes = plan_checks({**event, 'assessment': result}, catalog, preview, preliminary=True)
        errors += extra
        warnings += notes
    elif event.get('intake_mode') == 'open' and result.get('status') != 'no_disclosure' and event.get('workflow_policy')!='continuous-v1':
        warnings.append(problem('analysis_outline_missing', '尚未给出条件性文件与内容要求；义务判断可保留，但完整分析仍待补充'))
    return errors, warnings, review_items


def plan_checks(event, catalog, result, *, preliminary=False):
    errors, warnings = [], []
    documents, requirements = result['documents'], result['requirements']
    unique(documents, 'document_id', errors)
    unique(requirements, 'requirement_id', errors)
    unique(result['drafting_gaps'], 'key', errors)
    sources = {s['id']: s for s in catalog['sources']}
    cases = {s['id'] for s in catalog.get('cases', []) if library.admitted_case(s, event['layer'])}
    profiles = {p['id']: p for p in catalog.get('profiles', [])}
    docs = {d['document_id']: d for d in documents}
    gaps = {g['key']: g for g in result['drafting_gaps']}
    fact_keys = {f['key'] for f in (event.get('assessment') or {}).get('facts', [])}
    fact_status={f['key']:f['status'] for f in (event.get('assessment') or {}).get('facts', [])}
    if not preliminary and result['change_impact'] == 'assessment':
        errors.append(problem('return_to_assessment', '新增信息改变义务或时点，须回判断节点'))
    if not preliminary and result['blocking_questions']:
        errors.append(problem('planning_questions', '规划问题尚未解决'))
    selected_profile = library.selected_from_catalog(event, catalog)
    current_profiles = {d['profile_id'] for d in documents if d['stage'] == 'current' and d['purpose'] == 'public'}
    if not preliminary and (event.get('intake_mode')!='open' or event.get('facts',{}).get('disclosure_profile_id')) and (not selected_profile or selected_profile['id'] not in current_profiles):
        errors.append(problem('plan_profile_missing', '本事项绑定的公告格式未列入当前公开文件'))
    for doc in documents:
        if preliminary and doc['stage'] == 'current':
            errors.append(problem('preliminary_stage_invalid', '条件性分析中的文件须标为 preliminary 或 later_trigger，不能冒充已确认的本次制作任务'))
        if preliminary:
            refs={ref for row in requirements if row['document_id']==doc['document_id'] for ref in row['format_field_refs']}
            profile=profiles.get(doc.get('profile_id'))
            allowed={section['id']+':'+str(field['block']) for section in (profile or {}).get('sections',[]) for field in section.get('fields',[])}
            if refs and (not profile or refs-allowed):
                errors.append(problem('format_field_invalid', '条件性分析不能声明未绑定或不存在的格式字段；按法源说明内容即可'))
        if set(doc['source_ids']) - sources.keys():
            errors.append(problem('document_source_invalid', '文件依据不存在于规范库'))
        if doc['production'] == 'external_dependency' and not doc['dependencies']:
            if preliminary:
                warnings.append(problem('external_dependency_to_confirm', '外部文件的具体出具依赖留待正式规划核对：'+doc['title']))
            else:
                errors.append(problem('external_dependency_missing', '第三方文件须列出出具或程序依赖'))
        if (preliminary or doc['stage']=='current') and doc['production']=='company_draft' and not any(r['document_id']==doc['document_id'] for r in requirements):
            errors.append(problem('document_requirements_missing', '本次公司文件缺少逐项内容要求：'+doc['title']))
        if doc['purpose'] == 'public' and doc['stage'] == 'current':
            if doc['profile_id'] is None and event.get('intake_mode')=='open':
                warnings.append(problem('format_not_bound', '文件按所列法源规划；尚未绑定独立规范格式，不能宣称格式覆盖已核验：'+doc['title']))
                if any(r['format_field_refs'] for r in requirements if r['document_id']==doc['document_id']):
                    errors.append(problem('format_field_invalid', '未绑定格式的文件不能声明已映射格式字段'))
                continue
            profile = profiles.get(doc['profile_id'])
            if not profile:
                errors.append(problem('profile_missing', '公开文件缺少适用格式基准'))
                continue
            expected = {s['id'] for s in profile['sections']}
            mapped = {r['section_id'] for r in requirements if r['document_id'] == doc['document_id'] and r['necessity'] != 'recommended'}
            if not expected <= mapped:
                warnings.append(problem('format_coverage_review', '格式基准仍有章节需在正文及最终确认中核对：' + '、'.join(sorted(expected - mapped))))
            field_refs = {section['id'] + ':' + str(f['block'])
                          for section in profile['sections'] for f in section.get('fields', [])}
            covered = {ref for r in requirements if r['document_id'] == doc['document_id']
                       and r['necessity'] != 'recommended' for ref in r['format_field_refs']}
            if field_refs - covered:
                warnings.append(problem('format_field_coverage_review', '具体格式字段须在正文及最终确认中逐项核对'))
            if covered - field_refs:
                errors.append(problem('format_field_invalid', '内容矩阵引用了不存在的格式字段'))
            for sid in profile.get('normative_source_ids', []):
                sid = (event.get('law_bindings') or {}).get(sid, sid)
                if not sources.get(sid, {}).get('text'):
                    errors.append(problem('format_source_missing', '格式的规范原始依据缺失'))
    for row in requirements:
        if row.get('applicability_status')=='not_applicable':
            if row['necessity']=='required' or not row['fact_keys'] or row.get('gap_key') or any(fact_status.get(k) not in ('user_statement','material_supported') for k in row['fact_keys']) or row['applicability'].strip() in ('不适用','无','N/A'):
                errors.append(problem('requirement_exclusion_invalid','不适用项须为有明确事实依据的条件或建议项，不能省略必需项、未知项或仅写不适用'))
            warnings.append(problem('requirement_exclusion_review','终稿时核对不适用项：'+row['topic']+'；'+row['applicability']))
        if row['document_id'] not in docs:
            errors.append(problem('document_reference_missing', '要求未映射至文件'))
        if set(row['source_ids']) - (sources.keys() | cases):
            errors.append(problem('requirement_source_invalid', '要求依据不在绑定资料中'))
        if row['necessity'] != 'recommended' and not set(row['source_ids']) & sources.keys():
            errors.append(problem('case_as_requirement', '案例不能作为必需内容的唯一依据'))
        if row['granularity'].strip() == row['topic'].strip():
            errors.append(problem('granularity_missing', '章节标题不能代替具体内容颗粒度'))
        if set(row['fact_keys']) - fact_keys:
            errors.append(problem('fact_reference_missing', '要求引用了未登记来源的事实'))
        if row['gap_key'] and row['gap_key'] not in gaps:
            errors.append(problem('gap_reference_missing', '要求缺口未列处理安排'))
        if not row['fact_keys'] and not row['gap_key']:
            warnings.append(problem('requirement_basis_review', '内容要求未关联具体事实或缺口，须在正文确认时核对：'+row['topic']))
        if set(row['historical_links'])-{r['id'] for r in catalog.get('client_history',{}).get('items',[])}:
            errors.append(problem('history_not_connected','历史引用不在当前公司公告时间表中'))
    # The legacy Word section projection cannot diverge from the richer matrix.
    selected_sections={s['id']:s for s in (selected_profile or {}).get('sections',[])}
    items={i['id']:i for i in result.get('items',[])}
    if not preliminary and event.get('output_mode')!='text' and (not selected_sections.keys() <= items.keys() or any(items[k]['title']!=s['title'] for k,s in selected_sections.items() if k in items)):
        errors.append(problem('plan_projection_mismatch', '正文工具章节投影与独立格式基准不一致'))
    for gap in gaps.values():
        if not preliminary and gap['impact'] in ('assessment', 'plan'):
            errors.append(problem('planning_gap', '存在影响判断或规划的缺口：' + gap['key']))
        if not preliminary and gap['treatment'] == 'special_review':
            errors.append(problem('special_decision_missing', '特殊处理决定接口未接入，不能据此省略必披内容'))
        if gap['treatment'] == 'disclose_uncertainty' and not gap['source_ids']:
            errors.append(problem('uncertainty_basis_missing', '披露未确定状态须有规则依据'))
        if set(gap['source_ids']) - sources.keys():
            errors.append(problem('gap_source_invalid', '缺口处理依据不在法规库'))
    if gaps:
        warnings.append(problem('drafting_gaps_visible', '规划可审阅；制稿前仍须检查待补资料与外部依赖'))
    warnings.append(problem('format_scope_review', '覆盖检查只针对已绑定格式；其他适用要求及颗粒度仍须专业复核'))
    return errors, warnings


def drafting_readiness(event):
    plan = event.get('plan') or {}
    # A reused gap key is not proof that old material satisfies the current plan.
    supplied = {key: row for key, row in (event.get('drafting_supplements') or {}).items()
                if isinstance(row, dict) and plan.get('id') and row.get('plan_id') == plan['id']
                and row.get('state') == 'current'}
    gaps = [g for g in plan.get('drafting_gaps', [])
            if g['treatment'] in ('supply', 'special_review') and g.get('impact') not in ('content_review','publication') and g['key'] not in supplied]
    outputs = [d for d in plan.get('documents', []) if d['stage'] == 'current' and d['production'] == 'company_draft']
    external = [d for d in plan.get('documents', []) if d['stage'] == 'current' and d['production'] == 'external_dependency']
    if event.get('output_mode')=='text':
        external=[d for d in external if any(d['document_id'] in o['dependencies'] or d['title'] in o['dependencies'] for o in outputs)]
        current={d['document_id'] for d in outputs+external}
        linked={g['key']:{r['document_id'] for r in plan.get('requirements',[]) if r.get('gap_key')==g['key']} for g in gaps}
        # Only a gap explicitly scoped to other documents can be set aside.
        # Unscoped and current-document gaps remain visible blockers.
        gaps=[g for g in gaps if g.get('impact')!='draft' or not linked[g['key']] or bool(linked[g['key']]&current)]
    blockers = [g['description'] for g in gaps] + ['外部文件尚未核实：' + d['title'] for d in external]
    if event.get('output_mode')=='text' and not outputs:
        blockers.append('本次没有待起草的公司文件')
    elif event.get('output_mode')!='text' and len(outputs) != 1:
        blockers.append('现有 Word 接口一次只承载一份当前文件；多文件套件需接入后再制稿')
    return {'status': 'ready' if not blockers else 'blocked', 'blockers': blockers}


def body_requirements(event,document_id=None):
    plan=event.get('plan') or {};docs=plan.get('documents',[])
    current={d['document_id'] for d in docs if d['stage']=='current' and d['production']=='company_draft'}
    return [r for r in plan.get('requirements',[]) if r.get('applicability_status')!='not_applicable' and (not docs or r['document_id'] in current) and (document_id is None or r['document_id']==document_id)]


def mapped_in_text(value,text):
    pieces=value if isinstance(value,list) else [value]
    return bool(pieces) and len(pieces)<=30 and all(isinstance(piece,str) and piece.strip() and excerpt_in_source(piece,text) for piece in pieces)


def unresolved(text):
    return any(marker in text for marker in ('待补', '待填写', '待完善')) or bool(re.search(r'\b(?:TBD|TODO|XXX)\b|\{\{[^}]+\}\}|[【\[]待[^】\]\n]{0,30}(?:补充|填写|提供|确定|确认|核实)[^】\]\n]{0,10}[】\]]',text,re.I))


def draft_checks(text, plan):
    requirements=plan.get('requirements',[])
    handled={r['section_id'] for r in requirements};active={r['section_id'] for r in requirements if r.get('applicability_status')!='not_applicable'}
    items=[item for item in plan['items'] if item.get('id') not in handled or item.get('id') in active]
    missing = [item['title'] for item in items if not item['title'].strip() or item['title'] not in text]
    return [{'label':'披露内容完整性','status':'fail' if unresolved(text) else 'pass',
             'detail':'存在待补内容，补齐后方可人工验收' if unresolved(text) else '未检出待补标记，仍须人工核对正文'},
            {'label':'清单章节覆盖','status':'fail' if missing else 'pass',
             'detail':('缺少已确认清单章节：' + '、'.join(missing)) if missing else '已确认清单标题均存在；不代表正文语义或数字一致性已核验'},
            {'label':'模式','status':'warning','detail':'此处为确定性文稿检查；不代表内容、数字或专业结论已验收'}]


def text_draft_checks(event, result):
    errors=[]
    planned={d['document_id']:d for d in event['plan']['documents'] if d['stage']=='current' and d['production']=='company_draft'}
    documents=result.get('documents',[])
    unique(documents,'document_id',errors)
    if {d['document_id'] for d in documents}!=planned.keys():
        errors.append(problem('draft_documents_mismatch','正文文件集合须与本次公司起草清单一致，不能代拟第三方已出具报告'))
    for doc in documents:
        target=planned.get(doc['document_id'])
        if not target:continue
        required={r['requirement_id'] for r in body_requirements(event,doc['document_id'])}
        mapping=doc['requirement_map']
        missing=sorted(required-set(mapping));extra=sorted(set(mapping)-required);unlocated=[key for key,value in mapping.items() if not mapped_in_text(value,doc['text'])]
        if missing or extra or unlocated:
            errors.append(problem('draft_mapping_missing','正文与内容要求的对应关系尚未齐备：'+target['title'],repair={'missing_ids':missing,'extra_ids':extra,'unlocatable_ids':unlocated,'instruction':'只映射本次当前文件适用要求；摘录准确原句或用多段原句列表，不拼接正文中不存在的句子。'}))
        normalized=re.sub(r'(?m)^#{1,6}\s*','',doc['text'])
        if not excerpt_in_source(target['title'],normalized) or unresolved(doc['text']):
            errors.append(problem('draft_incomplete','正文缺少当前文件标题或仍有待填内容：'+target['title']))
    return errors
