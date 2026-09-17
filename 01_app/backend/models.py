from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator


class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)


class Create(Strict):
    workflow_policy: Literal['legacy-v1','continuous-v1'] = 'legacy-v1'
    company_id: str | None = Field(default=None, min_length=1, max_length=100)
    company_name: str | None = Field(default=None, min_length=1, max_length=300)
    stock_code: str | None = Field(default=None, pattern=r'^\d{6}$')
    board: Literal['base','innovation','chinext'] | None = None
    kind: str = Field(default='unclassified', min_length=1, max_length=100)
    output_mode: Literal['text','word'] = 'word'
    title: str = Field(min_length=1, max_length=300)
    summary: str = Field(default='', max_length=20000)
    facts: dict[str, Any] = Field(default_factory=dict)
    request_id: str = Field(min_length=8, max_length=128)

    @field_validator('facts')
    @classmethod
    def facts_safe(cls, value):
        import json
        import math
        if len(json.dumps(value)) > 50000 or len(value) > 100:
            raise ValueError('事实过大')
        for key, item in value.items():
            if isinstance(item, float) and not math.isfinite(item):
                raise ValueError('数值必须有限')
            if not isinstance(item, (str,int,float,bool,type(None))) or len(key) > 100:
                raise ValueError('事实仅支持扁平标量字段')
        return value


class Revision(Strict):
    expected_revision: int = Field(ge=1)


class Generate(Revision):
    request_id: str = Field(min_length=8, max_length=128)


class Edit(Revision):
    output_mode: Literal['text','word'] | None = None
    title: str | None = Field(default=None, min_length=1, max_length=300)
    summary: str | None = Field(default=None, max_length=20000)
    facts: dict[str, Any] | None = None

    @field_validator('facts')
    @classmethod
    def facts_safe(cls, value):
        return Create.facts_safe(value) if value is not None else value



class PlanItem(Strict):
    id: str = Field(max_length=100)
    title: str = Field(min_length=1, max_length=500)
    requirement: str = Field(default='', max_length=5000)
    detail: str = Field(default='', max_length=10000)
    evidence_status: str = Field(default='待补', max_length=100)
    source_ids: list[str] = Field(default_factory=list, max_length=100)
    notes: str = Field(default='', max_length=5000)


class Import(Strict):
    request_id: str = Field(min_length=8, max_length=128)



class Verify(Generate):
    stage: Literal['assessment','plan','template','draft','word']


class SourceSearch(Generate):
    stage: Literal['assessment','plan','draft'] = 'assessment'
    input_fingerprint: str = Field(pattern=r'^[a-f0-9]{64}$')
    status: Literal['found','not_found']
    queries: list[str] = Field(min_length=1,max_length=20)
    urls: list[str] = Field(default_factory=list,max_length=50)
    message: str = Field(min_length=10,max_length=3000)


class LibraryUpdate(Strict):
    expected_fingerprint: str = Field(pattern=r'^[a-f0-9]{64}$')
    items: list[dict[str, Any]] = Field(min_length=1,max_length=200)


class LawLifecycleCheck(Strict):
    """Manual trigger of the same fixed entry used by the monthly host schedule."""
    board: str = Field(min_length=1,max_length=30)
    instrument_id: str | None = Field(default=None,min_length=1,max_length=150)
    force: bool = False
    failed_only: bool = False
    dry_run: bool = False


class LifecycleRunRequest(Strict):
    """Browser manual trigger: one Pi run checks one law through the fixed write path."""
    board: str = Field(min_length=1,max_length=30)
    instrument_id: str = Field(min_length=1,max_length=150)
    model_key: str = Field(min_length=1,max_length=80)


class LifecycleSubmit(Strict):
    """Structured result a lifecycle Pi run may register; the backend owns the write."""
    instrument_id: str = Field(min_length=1,max_length=150)
    outcome: Literal['unchanged','changed','unavailable']
    detail: str = Field(min_length=1,max_length=2000)
    official_url: str | None = Field(default=None,max_length=500)
    download_id: str | None = Field(default=None,max_length=64)
    evidence_note: str | None = Field(default=None,max_length=1000)
    validity: Literal['current','repealed','superseded','not_yet_effective','uncertain'] = 'uncertain'
    validity_download_id: str | None = Field(default=None,pattern=r'^[a-f0-9]{64}$')
    validity_quote: str = Field(default='',max_length=4000)


class ArtifactUpload(Generate):
    input_fingerprint: str = Field(pattern=r'^[a-f0-9]{64}$')
    sha256: str = Field(pattern=r'^[a-f0-9]{64}$')
    filename: str = Field(min_length=1,max_length=200)
    content_base64: str = Field(min_length=1,max_length=8000000)
    host_qa: str = Field(default='',max_length=4000)


class LawBindings(Generate):
    bindings: dict[str,str] = Field(min_length=1,max_length=100)


class HumanConfirmation(Generate):
    stage: Literal['assessment','plan','template','draft','word']
    input_fingerprint: str = Field(pattern=r'^[a-f0-9]{64}$')
    decision: Literal['prepare_mandatory','prepare_voluntary','no_disclosure','special_review','accept','reject']
    reviewer: str = Field(min_length=1, max_length=100)
    reason: str = Field(min_length=1, max_length=3000)
    artifact_id: str | None = None
    visual_review: Literal['not_reviewed','reviewed'] = 'not_reviewed'
    content_review: Literal['not_reviewed','reviewed'] = 'not_reviewed'

    @field_validator('reviewer','reason')
    @classmethod
    def nonblank(cls,value):
        if not value.strip():raise ValueError('确认人和理由不能为空')
        return value.strip()


class DraftingSupplement(Generate):
    values: dict[str, str] = Field(min_length=1, max_length=100)
    source_note: str = Field(min_length=1, max_length=3000)


class Reopen(Generate):
    stage: Literal['assessment','plan','template','draft']
    reason: str = Field(min_length=1, max_length=3000)
