"""Typed contracts for internal node tasks; no model-provider configuration."""
from typing import Literal
from datetime import date
from pydantic import Field
from .models import Strict, Generate, PlanItem

Stage = Literal['assessment', 'plan', 'template', 'draft']


class TaskCreate(Generate):
    stage: Stage
    instruction: str = Field(default='', max_length=5000)


class Claim(Generate):
    host_family: Literal['codex', 'workbuddy', 'other', 'pi']
    host_run_ref: str = Field(min_length=1, max_length=200)


class Lease(Generate):
    claim_id: str = Field(min_length=1, max_length=100)


class SemanticVerdict(Strict):
    item_id: str = Field(min_length=1, max_length=200)
    verdict: Literal['supported','conflict','insufficient']
    reason: str = Field(min_length=1, max_length=2000)
    locator: str = Field(default='', max_length=300)


class Submit(Lease):
    input_fingerprint: str = Field(pattern=r'^[a-f0-9]{64}$')
    result: dict
    semantic_review: list[SemanticVerdict] | None = Field(default=None, max_length=100,
        description='独立语义复核结论；每次提交可附当前候选的复核意见，服务端按候选摘要绑定。')


class Finish(Generate):
    status: Literal['failed', 'cancelled']
    claim_id: str | None = None
    reason: str = Field(min_length=1, max_length=3000)


class AssessmentCandidate(Strict):
    status: Literal['disclose','no_disclosure','needs_info','review_required']
    summary: str = Field(min_length=1, max_length=10000)
    reasons: list[str] = Field(min_length=1, max_length=30)
    missing: list[str] = Field(default_factory=list, max_length=50)
    source_ids: list[str] = Field(min_length=1, max_length=50)
    limitations: list[str] = Field(default_factory=list, max_length=30)
    assessment_as_of: date
    facts: list['FactBasis'] = Field(default_factory=list, max_length=100)
    matters: list['Matter'] = Field(min_length=1, max_length=30)
    preliminary_plan: 'PlanCandidate | None' = None


class PlanCandidate(Strict):
    items: list[PlanItem] = Field(default_factory=list, max_length=100)
    documents: list['PlannedDocument'] = Field(min_length=1, max_length=30)
    requirements: list['Requirement'] = Field(min_length=1, max_length=200)
    drafting_gaps: list['Gap'] = Field(default_factory=list, max_length=100)
    blocking_questions: list[str] = Field(default_factory=list, max_length=30)
    change_impact: Literal['none','assessment'] = 'none'
    limitations: list[str] = Field(default_factory=list, max_length=30)


class DraftCandidate(Strict):
    template_id: str = Field(min_length=1, max_length=100)
    text: str = Field(min_length=1, max_length=200000)
    requirement_map: dict[str, str | list[str]] = Field(default_factory=dict,max_length=200,description='要求ID对应正文精确原句；跨段内容可用多段原句列表，不要自行拼接不存在的连续句子。')


class DocumentDraft(Strict):
    document_id: str = Field(min_length=1, max_length=100)
    text: str = Field(min_length=1, max_length=200000)
    requirement_map: dict[str, str | list[str]] = Field(min_length=1,max_length=200,description='仅映射当前正文的适用要求；每项可为一段精确原句或多段原句列表。')


class TextDraftCandidate(Strict):
    documents: list[DocumentDraft] = Field(min_length=1, max_length=30)


class FactBasis(Strict):
    key: str = Field(min_length=1, max_length=100)
    value: str | int | float | bool | None
    status: Literal['user_statement','material_supported','model_inference','unknown','conflicting']
    source_ref: str = Field(min_length=1, max_length=200, description='仅填 facts.字段名、summary、scope.company_name/stock_code/board 或当前公司历史公告的准确 announcement-编号；不要添加 event.、client_history: 或 #页码。')
    quote: str = Field(default='', max_length=5000, description='历史公告事实必须填写能在原文定位且包含value的原句，数字也须原句；不能用概括语句冒充原文。')
    observed_at: str = Field(min_length=1, max_length=100)


class Reasoning(Strict):
    source_id: str
    locator: str = Field(min_length=1, max_length=300)
    quote: str = Field(min_length=1, max_length=10000)
    condition: str = Field(min_length=1, max_length=5000)
    fact_keys: list[str] = Field(min_length=1, max_length=100, description='填写本候选facts数组中已定义的key；source_ref不等于key。')
    application: str = Field(min_length=1, max_length=10000)
    outcome: Literal['established','not_met','unknown']


class Calculation(Strict):
    operation: Literal['sum','ratio']
    fact_keys: list[str] = Field(min_length=1, max_length=100)
    result: str = Field(min_length=1, max_length=100, description='可省略，由服务端Decimal复算；ratio的%单位结果为分子/分母乘100，普通比值不乘100。显式填写须保留完整精度，不用显示用的四舍五入数。')
    unit: str = Field(min_length=1, max_length=100)
    period: str = Field(min_length=1, max_length=200)
    basis_source_id: str = Field(description='必填：法律阈值或累计判断填写已引用的准确法源ID；仅snapshot加总可填facts。普通ratio也须明确计算口径依据，不能省略或凭空选择法源。')
    aggregation_basis: Literal['not_applicable','user_declared_complete_ledger','public_announcements','unknown'] = 'not_applicable'
    scope: Literal['snapshot','cumulative'] = 'cumulative'


class Gap(Strict):
    key: str = Field(min_length=1, max_length=100)
    description: str = Field(min_length=1, max_length=3000)
    impact: Literal['assessment','plan','draft','content_review','publication'] = Field(description='assessment/plan/draft表示对应节点必需事实或内容缺失；content_review为终稿人工复核，publication为定稿后盖章、签发、报备和发布待办，后两者不阻断工作稿准备。')
    owner: str = Field(min_length=1, max_length=300)
    treatment: Literal['supply','disclose_uncertainty','later_trigger','special_review']
    source_ids: list[str] = Field(default_factory=list, max_length=30)


class Matter(Strict):
    matter_id: str
    event_types: list[str] = Field(min_length=1, max_length=20)
    subject: str = Field(min_length=1, max_length=1000)
    stage: str = Field(min_length=1, max_length=1000)
    duty_status: Literal['mandatory','not_triggered','no_mandatory_identified','undetermined']
    timing_status: Literal['triggered','not_triggered','unknown']
    trigger_events: list[str] = Field(default_factory=list, max_length=30)
    deadline_basis: list[str] = Field(default_factory=list, max_length=30, description='只填写本判断source_ids中准确的法源ID，不填时限说明文字；说明放在application或procedural_requirements。')
    reasoning_items: list[Reasoning] = Field(min_length=1, max_length=100)
    calculations: list[Calculation] = Field(default_factory=list, max_length=50)
    procedural_requirements: list[str] = Field(default_factory=list, max_length=30)
    historical_links: list[str] = Field(default_factory=list, max_length=30, description='只填写当前公司公告时间表中的准确announcement-编号，不填公告标题、公告文号或描述。')
    comparable_cases: list[str] = Field(default_factory=list, max_length=30)
    history_status: Literal['not_connected','not_searched','incomplete','covered'] = 'not_connected'
    special_review: Literal['none','required'] = 'none'
    decisive_questions: list[str] = Field(default_factory=list, max_length=30)
    downstream_gaps: list[Gap] = Field(default_factory=list, max_length=100)
    limitations: list[str] = Field(default_factory=list, max_length=30)
    reassessment_conditions: list[str] = Field(default_factory=list, max_length=30)
    urgency: Literal['normal','urgent','suspected_late'] = 'normal'
    specialist_required: bool = False


class PlannedDocument(Strict):
    document_id: str
    title: str = Field(min_length=1, max_length=500)
    profile_id: str | None = None
    purpose: Literal['public','filing','internal']
    necessity: Literal['required','conditional','recommended']
    applicability: str = Field(min_length=1, max_length=3000)
    stage: Literal['current','later_trigger','preliminary']
    producer: str = Field(min_length=1, max_length=300)
    production: Literal['company_draft','external_dependency']
    timing: str = Field(min_length=1, max_length=1000)
    dependencies: list[str] = Field(default_factory=list, max_length=50)
    source_ids: list[str] = Field(min_length=1, max_length=50)


class Requirement(Strict):
    applicability_status: Literal['applicable','not_applicable','unknown'] = Field(default='applicable',description='条件项经已给事实判断不适用时，明确标not_applicable并在applicability解释依据；保留在覆盖核对中，不强写进公告正文。必需项或未知事实不能据此省略。')
    requirement_id: str
    document_id: str
    section_id: str
    format_field_refs: list[str] = Field(default_factory=list, max_length=100)
    topic: str = Field(min_length=1, max_length=1000)
    granularity: str = Field(min_length=1, max_length=5000)
    necessity: Literal['required','conditional','recommended']
    applicability: str = Field(min_length=1, max_length=3000)
    source_ids: list[str] = Field(min_length=1, max_length=50)
    fact_keys: list[str] = Field(default_factory=list, max_length=100)
    historical_relation: Literal['new','changed','referenced','corrected','unknown']
    historical_links: list[str] = Field(default_factory=list, max_length=30)
    gap_key: str | None = None
    verify_method: str = Field(min_length=1, max_length=3000)


class TemplateCandidate(Strict):
    template_id: str
    requirement_map: dict[str, str] = Field(min_length=1, max_length=200)
    adaptations: list[str] = Field(default_factory=list, max_length=50)


AssessmentCandidate.model_rebuild()
PlanCandidate.model_rebuild()
