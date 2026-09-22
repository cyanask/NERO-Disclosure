"""Shared evidence validation for consultation answers and authored documents.

The existing runtime owns execution and publication. This module only verifies
source bindings and full-text coverage; it never asks users to approve evidence.
"""
import json
import re
from fastapi import HTTPException
from . import document_store as store
from .semantic_review import validate_verdicts

def coverage_items(text, evidence, prior_text=''):
    """Review every new/changed body span, including assertions omitted from basis.

    Exact unchanged lines inherit the existing version; this does not certify
    their truth. All changed lines are checked with their surrounding context.
    """
    prior_lines={line for line in prior_text.splitlines() if line.strip()}
    occurrences=[]
    for binding in evidence:
        statement=binding['statement'];start=0
        while (index:=text.find(statement,start))>=0:
            occurrences.append((index,index+len(statement),statement))
            start=index+len(statement)
    items=[]
    for line in re.finditer(r'[^\n]+',text):
        if not line[0].strip() or line[0] in prior_lines:continue
        for start in range(line.start(),line.end(),2000):
            end=min(start+2000,line.end())
            supported=list(dict.fromkeys(statement for a,b,statement in occurrences if a<end and b>start))
            context_value=json.dumps({'reviewed_statements':supported,
                'body_context':text[max(0,start-600):min(len(text),end+600)]},ensure_ascii=False)
            items.append({'item_id':'coverage:'+str(start),'code':'document_coverage_review',
                'fact_key':'正文事实覆盖','value':text[start:end],'quote':'',
                'source_ref':'document:body','context':context_value,'evidence_sha':store.sha(context_value.encode())})
    return items



def review(runtime, rid, run, items, bindings, stop):
    if not items:return [], {'source':'empty','verdicts':[]}
    verdicts, origin = runtime.semantic_review(rid,run,items,stop)
    checked = validate_verdicts(verdicts,items)
    if checked is None:
        raise HTTPException(409,'依据复核未完整返回，未交付未经核验的正文；请检查复核模型配置或重试')
    issues=[{**bindings[v['item_id']], 'reason':'依据复核未通过：'+v['reason']}
            for v in checked if v['verdict']!='supported']
    runtime.trace(rid,'text_evidence_review',{'source':origin,'items':len(items),'unsupported':len(issues)})
    return issues, {'source':origin,'verdicts':checked}


def validate(runtime, rid, run, text, basis, context, stop, prior_text=''):
    from .document_runtime import source_text
    from .disclosure_contract import excerpt_in_source, evidence_context
    if not isinstance(text,str) or not 1<=len(text)<=100000:
        raise HTTPException(422,'正文须为非空文字，长度不超过100000字')
    if not isinstance(basis,list) or len(basis)>100:
        raise HTTPException(422,'依据绑定须为不超过100项的清单')
    evidence=[];issues=[];items=[];bindings={}
    for index,binding in enumerate(basis):
        if not isinstance(binding,dict) or set(binding)!={'statement','source_id','quote'} or not all(isinstance(v,str) and v.strip() for v in binding.values()):
            raise HTTPException(422,'事实依据绑定无效')
        try:source=source_text(runtime,run,context,binding['source_id'])
        except HTTPException as exc:
            if exc.status_code not in (404,422):raise
            issues.append({**binding,'reason':str(exc.detail)});continue
        if not excerpt_in_source(binding['quote'],source):
            issues.append({**binding,'reason':'引文在所引来源中定位不到，请复制来源原句'});continue
        if binding['statement'] not in text:
            issues.append({**binding,'reason':'该断言未逐字出现在提交正文中，statement 须复制正文原句'});continue
        evidence.append({**binding,'source_sha256':store.sha(source.encode())})
        identity='claim:'+str(index)
        source_id=binding['source_id']
        source_kind=('user_statement' if source_id.startswith(('user:','event:')) else
                     'document_candidate' if source_id.startswith('document:') else 'source_document')
        items.append({'item_id':identity,'code':'document_claim_review','fact_key':binding['statement'][:200],
            'value':binding['statement'],'quote':binding['quote'],'source_ref':binding['source_id'],
            'context':json.dumps({'source_kind':source_kind,'source_header':source[:1200],
                                 'source_context':evidence_context(source,binding['quote'])},ensure_ascii=False),
            'evidence_sha':store.sha(source.encode())})
        bindings[identity]=binding
    if issues:return evidence,{},issues
    issues,claims=review(runtime,rid,run,items,bindings,stop)
    if issues:return evidence,{},issues
    items=coverage_items(text,evidence,prior_text)
    bindings={row['item_id']:{'statement':row['value'],'source_id':row['source_ref'],'quote':''} for row in items}
    issues,coverage=review(runtime,rid,run,items,bindings,stop)
    return evidence,{'bindings':claims,'body_coverage':coverage},issues
