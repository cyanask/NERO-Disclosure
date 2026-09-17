"""Private operation contracts used by the in-process Pi runtime."""
from typing import Literal
from pydantic import Field,ValidationError
from fastapi import HTTPException
from . import models as m,agent_models as am

class Envelope(m.Strict):
    protocol_version: Literal['1']='1'
    operation: str=Field(min_length=1,max_length=100)
    args: dict=Field(default_factory=dict)

class Empty(m.Strict):pass
class OptionalBoard(m.Strict):board: str | None=None
class BoardScope(m.Strict):board: Literal['base','innovation','chinext']
class EventId(m.Strict):event_id: str=Field(min_length=1,max_length=100)
class EventGenerate(m.Generate,EventId):pass
class EventEdit(m.Edit,EventId):pass
class TaskId(EventId):task_id: str=Field(min_length=1,max_length=100)
class TaskRequest(am.TaskCreate,EventId):pass
class TaskOpen(am.Claim,TaskId):pass
class TaskSubmit(am.Submit,TaskId):pass
class TaskHeartbeat(am.Lease,TaskId):pass
class TaskFinish(am.Finish,TaskId):pass
class VerifyRead(EventId):stage: Literal['assessment','plan','template','draft','word']='assessment'
class VerifyWrite(m.Verify,EventId):pass
class SourceSearch(m.SourceSearch,EventId):pass
class LawBindings(m.LawBindings,EventId):pass
class Collection(BoardScope):collection: Literal['laws','cases','blacklist_cases','profiles']
class LibraryUpdate(m.LibraryUpdate,Collection):pass
class ArtifactUpload(m.ArtifactUpload,EventId):pass
class TaskAdopt(m.Generate,TaskId):pass
class DraftingSupplement(m.DraftingSupplement,EventId):pass
class Reopen(m.Reopen,EventId):pass
class Continuous(m.Generate,EventId):
    session_id:str=Field(min_length=1,max_length=100)
    model_key:str=Field(min_length=1,max_length=80)
    run_id:str=Field(min_length=1,max_length=100)
class TaskSearch(TaskId):
    collection: Literal['laws','cases','blacklist_cases','profiles','client_history','client_materials']='laws'
    query: str=Field(default='',max_length=500)
    offset: int=Field(default=0,ge=0)
    limit: int=Field(default=20,ge=1,le=100)
    view: Literal['items','groups']='items'
class TaskRead(TaskId):
    item_id: str=Field(min_length=1,max_length=150)
    page: int | None=Field(default=None,ge=1)
    view: Literal['auto','document']='auto'
class Search(BoardScope):
    company:str=Field(default='',pattern=r'^\d{6}$|^$')
    collection: Literal['laws','cases','blacklist_cases','profiles']='laws'
    query: str=Field(default='',max_length=500)
    kind: str | None=None
    view: Literal['items','groups','candidates']='items'
    offset: int=Field(default=0,ge=0)
    limit: int=Field(default=20,ge=1,le=100)
class Read(BoardScope):
    company:str=Field(default='',pattern=r'^\d{6}$|^$')
    item_id: str=Field(min_length=1,max_length=150)
    page: int | None=Field(default=None,ge=1)
    view: Literal['auto','document']='auto'
class Templates(BoardScope):kind: str | None=None
class Scenario(m.Import):scenario_id: str=Field(min_length=1,max_length=100)

MODELS={'event.list':OptionalBoard,'event.create':m.Create,'event.get':EventId,'event.update':EventEdit,
        'rules.check':EventGenerate,'task.list':OptionalBoard,'task.request':TaskRequest,'task.open':TaskOpen,'task.context':TaskId,
        'task.submit':TaskSubmit,'task.heartbeat':TaskHeartbeat,'task.finish':TaskFinish,'library.search':Search,'library.read':Read,'library.manage':Collection,'library.update':LibraryUpdate,
        'templates.list':Templates,'word.context':EventId,'artifact.register':ArtifactUpload,'verify.run':VerifyRead,'gate.advance':VerifyWrite,'law.bind':LawBindings,'source.search_report':SourceSearch,'task.adopt':TaskAdopt,'scenario.list':OptionalBoard,'scenario.import':Scenario,
        'task.library.search':TaskSearch,'task.library.read':TaskRead,'drafting.supplement':DraftingSupplement,'workflow.reopen':Reopen}
MODELS['task.evaluate']=TaskSubmit
MODELS['workflow.continuous']=Continuous


def dispatch(envelope,handlers):
    op=envelope.operation
    if op in ('approve','confirmation','human.confirm','word.review','word.prepare','session.login','publish'):raise HTTPException(403,'内部工作流不提供人工审批或账户管理')
    if op not in MODELS:raise HTTPException(422,'未登记的Harness操作')
    try:args=MODELS[op].model_validate(envelope.args)
    except ValidationError:raise HTTPException(422,'操作参数不符合内部操作schema')
    return {'protocol_version':'1','operation':op,'data':handlers[op](args)}


def payload(args,model):
    return model.model_validate({k:v for k,v in args.model_dump().items() if k in model.model_fields})
