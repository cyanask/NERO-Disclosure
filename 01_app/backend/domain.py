"""Candidate rule evaluation. Rules and citations are injected public seed material."""
import hashlib
import json
import re
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from uuid import uuid4
from fastapi import HTTPException
from .boards import require_board
from .event_kinds import KINDS
from .public_store import board_dir, template_dir
from .paths import knowledge_of

COMPANIES = [{'id':'demo-chinext','name':'上市公司（创业板模拟）','layer':'chinext'}]
NOTICE = '信息披露-AI辅助系统：当前工作区仅开放创业板；Pi 按网页本轮选择调用模型；所有候选经当前输入 Verify/Gate 检查，检查通过不表示人工验收或法律意见。'


def read_json(path, fallback):
    return json.loads(path.read_text('utf-8')) if path.exists() else fallback


class Seeds:
    def __init__(self, root, board=None, event=None, draft_provider=None):
        self.root = knowledge_of(root)
        self.board = require_board(board) if board is not None else None
        self.event_scope = event
        self.draft_provider = draft_provider

    def for_board(self, board):
        board = require_board(board)
        if self.board is not None and self.board != board:
            raise HTTPException(422, '知识库与事项板块不一致')
        return self if self.board == board else Seeds(self.root, board, draft_provider=self.draft_provider)

    def for_event(self, event):
        self.for_board(event['layer'])
        return Seeds(self.root,event['layer'],event,self.draft_provider)

    @property
    def public_dir(self):
        return board_dir(self.root, self.board)

    @property
    def template_dir(self):
        return template_dir(self.root, self.board)

    def catalog(self):
        from .library import safe_file
        catalog = read_json(self.public_dir / 'catalog.json', {'sources': [], 'cases': [], 'rules': []})
        if catalog.get('board') != self.board:
            raise HTTPException(409, '知识库板块清单不一致')
        catalog['layout_profiles'] = read_json(self.template_dir / 'layout_profiles.json', [])
        from .library import profiles as scoped_profiles
        catalog['profiles'] = scoped_profiles(self)
        catalog['instruments'] = read_json(self.public_dir / 'instruments.json', [])
        catalog['rules'] = read_json(self.public_dir / 'rules.json', catalog.get('rules', []))
        for key in ('sources','cases','blacklist_cases','profiles','instruments','rules','layout_profiles'):
            if any(row.get('library_board') != self.board or
                   (row.get('layers') and row['layers'] != [self.board]) for row in catalog.get(key, [])):
                raise HTTPException(409, '知识库含其他板块记录，请核对所属板块：'+key)
        # Bind both the registered description and the bytes served through read tools.
        assets={}
        for row in catalog.get('sources',[])+catalog.get('cases',[])+catalog.get('blacklist_cases',[]):
            documents=[row]+row.get('evidence_documents',[])
            for document in documents:
                for key in ('original_path','document_path'):
                    name=document.get(key)
                    if name and name not in assets:
                        try:assets[name]=hashlib.sha256(safe_file(self,name).read_bytes()).hexdigest()
                        except (HTTPException,OSError):assets[name]='missing_or_unreadable'
        templates=self.templates();template_assets={}
        for row in templates:
            path=(self.root/'templates'/row['file']).resolve()
            try:template_assets[row['id']]=hashlib.sha256(path.read_bytes()).hexdigest() if path.is_relative_to((self.root/'templates').resolve()) else 'invalid_path'
            except OSError:template_assets[row['id']]='missing_or_unreadable'
        catalog['templates']=templates;catalog['template_asset_state']=template_assets
        for row in catalog['layout_profiles']:
            name=row.get('source_observations_path')
            if name:
                try:assets[name]=hashlib.sha256(safe_file(self,name).read_bytes()).hexdigest()
                except (HTTPException,OSError):assets[name]='missing_or_unreadable'
        catalog['asset_state']=assets
        if self.event_scope:
            from .announcement_history import snapshot
            catalog['client_history']=snapshot(self.root,self.event_scope)
        return catalog

    def fingerprint(self, catalog=None):
        snapshot = self.catalog() if catalog is None else catalog
        return hashlib.sha256(json.dumps(snapshot, sort_keys=True, ensure_ascii=False).encode()).hexdigest()

    def templates(self, kind=None):
        from .library import profiles as board_profiles
        entries = read_json(self.template_dir / 'manifest.json', [])
        code=(self.event_scope or {}).get('stock_code','')
        if re.fullmatch(r'\d{6}',code or ''):
            overrides=read_json(self.root/'templates/companies'/self.board/code/'manifest.json',[])
            byid={x['id']:x for x in entries}
            byid.update({x['id']:x for x in overrides});entries=list(byid.values())
        entries=[x for x in entries if not x.get('company_scope') or x['company_scope']==code]
        if any(row.get('library_board') != self.board for row in entries):
            raise HTTPException(409, '模板清单与当前板块不一致')
        profiles={p['id']:p for p in board_profiles(self)}
        entries=[{**x, **({k:profiles[x['profile_id']][k] for k in ('sections','layout_profile_id') if k in profiles[x['profile_id']]} if x.get('profile_id') in profiles else {})} for x in entries]
        bound={x.get('profile_id') for x in entries}
        for profile in profiles.values():
            if profile['id'] in bound:continue
            shell=next((x for x in entries if x['kind']==profile['kind']),None)
            if shell:
                entries.append({**shell,'id':'profile-'+hashlib.sha256(profile['id'].encode()).hexdigest()[:20],
                    'profile_id':profile['id'],'name':profile['title'],'version':profile.get('version','profile-v1'),
                    'sections':profile['sections'],'layout_profile_id':profile['layout_profile_id']})
        return [x for x in entries if kind is None or x['kind'] == kind]

    def scenarios(self):
        if self.board is None:
            from .boards import BOARDS
            return [s for b in BOARDS if b['available'] for s in self.for_board(b['id']).scenarios()]
        return read_json(self.public_dir / 'scenarios.json', [])

    def knowledge(self):
        catalog = self.catalog()
        return (catalog.get('instruments', []) + catalog.get('sources', []) + catalog.get('cases', [])
                + catalog.get('blacklist_cases', []))


def event_types(profiles=None):
    options = {
        'meeting_type': [{'label':'年度股东会','value':'annual'}, {'label':'临时股东会','value':'extraordinary'}],
        'counterparty_type': [{'label':'关联自然人','value':'natural_person'}, {'label':'关联法人','value':'legal_person'}],
    }
    output=[]
    for key,(label,fields) in KINDS.items():
        entries=[{'key':'event_date','label':'事项发生日期','type':'date','required':True},
                 {'key':'facts_confirmed','label':'已核对模拟事实完整性','type':'boolean','required':True}]
        entries += [{'key':k,'label':l.split('（annual')[0].split('（natural_person')[0], 'type':t,'required':True} for k,l,t in fields]
        if key in ('related_transaction','litigation_arbitration'):
            entries += [{'key':'financial_period','label':'最近一期审计年度','type':'text','required':True},
                        {'key':'financial_confirmed','label':'已核对经审计财务口径','type':'boolean','required':True},
                        {'key':'aggregation_complete','label':'已核对历史事项范围并去重','type':'boolean','required':True}]
        for entry in entries:
            if entry['key'] in options:
                entry['options']=options[entry['key']]
            if entry['key']=='cumulative_amount':
                entry['label']='此前应累计交易金额（元）' if key=='related_transaction' else '此前其他案件金额（元）'
                entry['help']='不含本次；仅计入连续12个月内应累计且尚未履行相应义务的交易，需人工核对归组和去重。' if key=='related_transaction' else '如存在此前其他案件，系统转专业复核，不直接按关联交易方式累计。'
        if profiles:
            entries.append({'key':'disclosure_profile_id','label':'披露文种（可在分析后调整，调整后须重评）','type':'text','required':False,'options':[{'label':p['title'],'value':p['id']} for p in profiles if p['kind']==key]})
        output.append({'id':key,'label':label,'fields':entries})
    return output


def evaluate(event, seeds, catalog=None):
    seeds = seeds.for_event(event)
    if catalog is not None and catalog.get('board') != seeds.board:
        raise HTTPException(422, '规则快照与事项板块不一致')
    catalog, facts = (seeds.catalog() if catalog is None else catalog), event['facts']
    result = {'id':str(uuid4()), 'status':'review_required','summary':'规则覆盖不足，待专业复核','reasons':[],'missing':[],'citations':[],'calculations':[],'limitations':[NOTICE],'approved':False,'mode':'rules_only'}
    rules = [r for r in catalog.get('rules', []) if r['event_kind'] == event['kind'] and event['layer'] in r.get('layers', [])]
    if not rules:
        result['limitations'].append('该事项或层级尚无经核对的可执行规则。')
        return result
    rule = rules[0]
    source_ids = [(event.get('law_bindings') or {}).get(sid,sid) for sid in rule.get('source_ids', [])]
    citations = [s for s in catalog.get('sources', []) if s['id'] in source_ids]
    result['citations'] = citations
    result['limitations'].extend(rule.get('limitations', []))
    required = ['event_date', 'facts_confirmed'] + rule.get('required_facts', [])
    if event['kind'] in ('related_transaction','litigation_arbitration'):
        required += ['amount','audited_net_assets','financial_period','financial_confirmed']
    if event['kind'] == 'related_transaction':
        required += ['aggregation_complete','cumulative_amount']
    result['missing'] = [key for key in required if facts.get(key) is None or facts.get(key) == '']
    for flag in ('facts_confirmed','financial_confirmed','aggregation_complete'):
        if flag in required and facts.get(flag) is not True:
            result['missing'].append(flag)
    for key, _, kind in KINDS.get(event['kind'],('',[]))[1]:
        if kind == 'boolean' and key in required and type(facts.get(key)) is not bool:
            result['missing'].append(key)
    if 'financial_period' in required and (not isinstance(facts.get('financial_period'), str) or len(facts['financial_period']) != 4 or not facts['financial_period'].isdigit()):
        result['missing'].append('financial_period')
    result['missing'] = list(dict.fromkeys(result['missing']))
    if result['missing']:
        result.update(status='needs_info', summary='关键事实待补，尚不能作披露判断')
        return result
    if len(citations) != len(source_ids) or not citations:
        result['limitations'].append('规则缺少完整条款来源。')
        return result
    try:
        event_date = date.fromisoformat(facts['event_date'])
        for source in citations:
            if (source.get('effective_from') and event_date < date.fromisoformat(source['effective_from'])) or (source.get('effective_to') and event_date > date.fromisoformat(source['effective_to'])):
                result['limitations'].append('事项日期不在所载条款适用期间。')
                return result
    except (ValueError, TypeError):
        result.update(status='needs_info', summary='事项日期无效', missing=['event_date'])
        return result
    logic = rule.get('logic', {})
    if event['kind'] == 'litigation_arbitration' and facts.get('cumulative_amount') not in (None, 0, '0', ''):
        result['limitations'].append('存在此前案件金额，不能套用关联交易累计规则，须独立核对诉讼披露。')
        return result
    if logic.get('type') == 'board':
        flags = [facts.get('requires_shareholder_approval'), facts.get('contains_disclosable_information')]
        if any(v is True for v in flags):
            result.update(status='disclose', summary='涉及股东会审议或应披露重大信息，待当前输入 Verify/Gate 核对')
        elif all(v is False for v in flags):
            result.update(status='review_required', summary='已列明的决议披露条件未命中，其他披露义务待专业复核')
        else:
            result.update(status='needs_info', summary='董事会决议披露条件待补', missing=['requires_shareholder_approval','contains_disclosable_information'])
    elif logic.get('type') == 'notice':
        kind = facts.get('meeting_type')
        days = logic.get('advance_days', {}).get(kind)
        try:
            if type(days) is not int:
                raise ValueError()
            meeting = date.fromisoformat(facts['meeting_date'])
            deadline = meeting - timedelta(days=days)
            result.update(status='disclose', summary='须披露股东会通知，法定提前期限待人工核对')
            result['calculations'] = [{'label':'通知最迟日期（自然日）','expression':f'{meeting} - {days}天','result':deadline.isoformat()}]
            if event_date > deadline:
                result['limitations'].append('事项日期已晚于所算通知期限，须立即专业核对。')
        except (ValueError,TypeError,KeyError):
            result.update(status='needs_info',missing=['meeting_type','meeting_date'],summary='会议类型或日期待补')
    elif logic.get('type') == 'always':
        result.update(status='disclose', summary='所载规则要求披露，待当前输入 Verify/Gate 核对')
    elif logic.get('type') in ('threshold', 'litigation', 'related'):
        try:
            amount = Decimal(str(facts[logic.get('amount_field', 'amount')]))
            denominator = Decimal(str(facts[logic.get('denominator_field', 'audited_net_assets')]))
            if event['kind'] == 'related_transaction':
                previous = Decimal(str(facts['cumulative_amount']))
                if not previous.is_finite() or previous < 0:
                    raise ValueError()
                amount += previous
                result['limitations'].append('累计金额为本次加此前应累计金额；去重与累计范围由提供者确认。')
            if logic.get('denominator_absolute') or logic.get('type') == 'litigation':
                denominator = abs(denominator)
            if logic.get('type') == 'related':
                if facts.get('is_related_party') is not True or any(facts.get(k) is not False for k in ('is_guarantee','daily_expected','exemption_claimed')):
                    result['limitations'].append('关联关系、担保、日常预计或豁免须专业核对。')
                    return result
                counterparty = facts.get('counterparty_type')
                if counterparty not in ('natural_person','legal_person'):
                    result.update(status='needs_info', missing=['counterparty_type'])
                    return result
                logic = {**logic, **logic.get(counterparty, {})}
                if counterparty == 'natural_person':
                    denominator = Decimal(1)
            absolute = Decimal(str(logic['absolute_threshold']))
            ratio = Decimal(str(logic['ratio_threshold']))
            if not all(v.is_finite() for v in (amount, denominator, absolute, ratio)) or amount < 0 or denominator <= 0:
                raise ValueError()
            actual_ratio = amount / denominator
            result['calculations'] = [{'label':'金额比较','expression':f'{amount} >= {absolute}', 'result': amount >= absolute}, {'label':'比例比较','expression':f'{amount} / {denominator} = {actual_ratio}', 'result':float(actual_ratio)}]
            amount_hit = amount > absolute if logic.get('absolute_comparator') == 'gt' or logic.get('type') == 'litigation' else amount >= absolute
            result['calculations'][0] = {'label':'金额比较','expression':f'{amount} ' + ('>' if logic.get('absolute_comparator') == 'gt' or logic.get('type') == 'litigation' else '>=') + f' {absolute}', 'result':amount_hit}
            conditions = [amount_hit, actual_ratio >= ratio]
            operator = logic.get('operator', 'and' if logic.get('type') in ('litigation','related') else None)
            if operator not in ('and', 'or'):
                return result
            hit = all(conditions) if operator == 'and' else any(conditions)
            if logic.get('type') == 'litigation':
                hit = hit or facts.get('material_impact') is True or facts.get('resolution_validity_case') is True
            result['status'] = 'disclose' if hit else logic.get('below_status', 'review_required')
            if result['status'] not in ('disclose', 'no_disclosure', 'review_required'):
                result['status'] = 'review_required'
            if logic.get('type') in ('litigation','related') and not hit:
                result['status'] = 'review_required'
            result['summary'] = '达到所载规则阈值，待当前输入 Verify/Gate 核对' if hit else '未达到本项阈值，须核对累计及其他触发条件'
        except (KeyError, ValueError, InvalidOperation, TypeError, ZeroDivisionError):
            result.update(status='needs_info', summary='计算事实或规则参数不足，待补充')
    result['reasons'].append(rule.get('id', '公开规则候选'))
    return result
