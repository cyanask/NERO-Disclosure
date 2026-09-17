"""Project-owned stage methods. Never discovers or modifies host-global Skills."""
import hashlib
import json
from pathlib import Path
from fastapi import HTTPException
from .paths import app_of

STAGES={'assessment','plan','template','draft'}


def get(root,stage):
    if stage not in STAGES:raise HTTPException(422,'业务节点无效')
    return read_method(root,stage,'stages')


def get_method(root,name):
    if name not in ('consultation','announcement'):raise HTTPException(422,'业务方法无效')
    return read_method(root,name,'methods')


def read_method(root,stage,section):
    root=app_of(root);base=(root/'skills').resolve()
    try:
        if not base.is_relative_to(root.resolve()):raise ValueError()
        registry=json.loads((base/'registry.json').read_text('utf-8'))
        spec=registry[section][stage]
        relative=Path(spec['path'])
        if relative.is_absolute() or '..' in relative.parts:raise ValueError()
        path=(root/relative).resolve()
        if not path.is_relative_to(base) or path.name!='SKILL.md' or not path.is_file():raise ValueError()
        raw=path.read_bytes()
        if not 1<=len(raw)<=50000 or hashlib.sha256(raw).hexdigest()!=spec['sha256']:raise ValueError()
        references=[]
        for ref in spec.get('references',[]):
            relative_ref=Path(ref['path'])
            ref_path=(root/relative_ref).resolve()
            if relative_ref.is_absolute() or '..' in relative_ref.parts or not ref_path.is_relative_to(base) or ref_path.suffix!='.md':raise ValueError()
            content=ref_path.read_bytes()
            if not 1<=len(content)<=50000 or hashlib.sha256(content).hexdigest()!=ref['sha256']:raise ValueError()
            references.append({**ref,'content':content.decode('utf-8')})
        bundle=hashlib.sha256(json.dumps([spec['sha256'],[(r['path'],r['sha256']) for r in references]],sort_keys=True).encode()).hexdigest()
        return {'id':spec['id'],'version':spec['version'],'stage':stage,'path':spec['path'],
                'sha256':spec['sha256'],'bundle_sha256':bundle,'references':references,'instructions':raw.decode('utf-8'),'scope':'project_only'}
    except (OSError,ValueError,KeyError,TypeError):
        raise HTTPException(409,'节点Skill缺失或校验失败，请维护项目Skill注册后再领取任务')


def catalog(root):
    return [{k:v for k,v in get(root,stage).items() if k not in ('instructions','references')} for stage in ('assessment','plan','template','draft')]
