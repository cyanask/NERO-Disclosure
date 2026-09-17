"""Scoped knowledge capabilities: Pi prepares, the existing browser owns material changes."""
import copy,hashlib,json,re,shutil
from pathlib import Path
from uuid import uuid4
from fastapi import HTTPException
from . import library,library_admin,library_write,public_sources
from .knowledge_references import references
from .domain import Seeds


def spec(name,description,properties,required=()):
    return {'name':'knowledge_'+name,'description':description,'parameters':{'type':'object','additionalProperties':False,'properties':properties,'required':list(required)}}
S={'type':'string'};I={'type':'integer','minimum':0}
COL={'type':'string','enum':['laws','cases','blacklist_cases','profiles']}


def tools(intent):
    result=[spec('search','查询当前板块知识库，返回候选和来源状态。',{'collection':COL,'query':S},['collection','query']),
            spec('read','读取具体条目、内容模板及原件定位。',{'item_id':S},['item_id'])]
    if intent in ('query','refresh','template'):
        result += [spec('web_search','在互联网检索新法规、公告格式及公开披露案例。仅用公开关键词，不发送未公开事项细节。',{'query':S},['query']),
          spec('download','下载官方PDF或HTML原件并登记哈希，提取页级正文；下载不等于已入库。',{'url':S},['url']),
          spec('download_read','读取本轮下载原件的指定页和分段；无文本时提示需OCR。',{'download_id':S,'page':{'type':'integer','minimum':1},'offset':I},['download_id','page'])]
    if intent in ('edit','delete','refresh','template'):
        result += [spec('propose','准备具体知识变更，在对话中展示对象、内容和引用影响；用户核对后写入。items按当前条目结构填写，制作模板需给出新profile章节、字段、法源、参考案例和layout_profile_id。',
             {'operation':{'type':'string','enum':['edit','delete','admit','template']},'collection':COL,'ids':{'type':'array','items':S},
              'items':{'type':'array','items':{'type':'object','additionalProperties':True}},'download_id':S,'summary':S},['operation','collection','summary'])]
    result += [spec('imports','列出本轮公司可继续处理的上传/下载文件。',{},[]),spec('history','读取本轮公司历史公告及公告时间表；无公司范围时不能查询。',{'query':S,'item_id':S,'page':{'type':'integer','minimum':1},'offset':I},[]),
               spec('import_read','读取用户上传或本轮下载文件的结构、字段及指定页正文。',{'import_id':S,'page':{'type':'integer','minimum':1}},['import_id'])]
    if intent in ('refresh','template'):
        result += [spec('import_url','下载官方文件并完成结构抽取，按本轮公司隔离历史公告。',{'url':S,'collection':{'type':'string','enum':['laws','cases','blacklist_cases','history','profiles']}},['url','collection']),
                   spec('import_propose','提交上传/下载文件的入库元数据，待用户核对；禁止重写原文或伪造发布确认。',{'import_id':S,'metadata':{'type':'object','additionalProperties':True},'summary':S},['import_id','metadata','summary'])]
        result += [spec('import_batch_propose','同一资料库的多份文件集中预览、一次确认。中途失败保留已完成清单，可继续剩余文件。',{'imports':{'type':'array','minItems':1,'maxItems':200,'items':{'type':'object','properties':{'import_id':S,'metadata':{'type':'object','additionalProperties':True}},'required':['import_id','metadata'],'additionalProperties':False}},'summary':S},['imports','summary'])]
    if intent=='template':result += [spec('template_replace','使用用户上传原文件替换指定模板，先展示版本影响。',{'import_id':S,'profile_id':S},['import_id','profile_id'])]
    if intent=='delete':result += [spec('delete_prepare','后台确定当前范围的删除清单及引用影响，用户确认后执行。',{'collection':{'type':'string','enum':['laws','cases','blacklist_cases','history','profiles']},'ids':{'type':'array','items':S}},['collection','ids'])]
    return result



def prepare(runtime,rid,args):
    run=runtime.store.run(rid);op=args.get('operation');collection=args.get('collection');board=run['board']
    allowed={'edit':('edit',),'delete':('delete',),'refresh':('admit','edit'),'template':('admit','template')}
    if op not in allowed.get(run.get('intent'),()):raise HTTPException(403,'当前意图不授予这项知识写操作')
    state=library_admin.state(runtime.root,collection,board)
    items=copy.deepcopy(args.get('items') or [])
    if not isinstance(items,list) or len(items)>200 or any(not isinstance(x,dict) for x in items):raise HTTPException(422,'知识变更内容结构无效')
    if op!='delete' and not items:raise HTTPException(422,'请先形成具体变更内容，再提交确认')
    item_ids=[x.get('id') for x in items]
    ids=args.get('ids') if args.get('ids') is not None else item_ids
    if not isinstance(ids,list) or not 1<=len(ids)<=200 or any(not isinstance(x,str) or not re.fullmatch(r'[A-Za-z0-9][\w.-]{0,149}',x) for x in ids) or len(set(ids))!=len(ids):raise HTTPException(422,'请提供不重复的具体知识条目编号')
    if op!='delete' and (item_ids!=ids):raise HTTPException(422,'预览对象必须与实际变更内容逐项一致')
    if op=='delete':items=[]  # Deletion previews use canonical rows, never model-supplied content.
    existing={x['id']:x for x in state['items']}
    if any(existing.get(i,{}).get('company_scope') not in (None,'',run.get('company_code','')) for i in ids):raise HTTPException(403,'资料属于其他公司的专用模板范围')
    source=None
    if op=='delete':
        if not set(ids)<=set(existing):raise HTTPException(404,'部分删除条目不存在')
    elif op=='admit':
        if collection not in ('laws','cases','blacklist_cases'):raise HTTPException(422,'原件入库仅适用于法规或案例')
        source,document=public_sources.receipt(runtime.root,rid,args.get('download_id'))
        if source['board']!=board or source['requires_ocr']:raise HTTPException(409,'原件尚无可核对正文或板块不匹配')
        full=''.join(p['text'] for p in document['pages']);normalized=lambda v:re.sub(r'\s+','',v)
        for item in items:
            if item['id'] in existing:raise HTTPException(409,'新版本须用新编号；已有条目请使用编辑操作')
            if collection=='laws' and (not item.get('text') or normalized(item['text']) not in normalized(full)):raise HTTPException(422,'法条正文必须能定位至本次下载原件，不能凭模型重写')
            item.update({k:source[k] for k in ('original_path','document_path','sha256','document_sha256')})
            item.update(url=source['final_url'],library_board=board,review_status='pending_professional_review',scope_review_status='pending_professional_review',verification_status='original_bound_pending_review')
            if collection=='cases':item.update(source_kind='official_case',verification_status='official_original_indexed',eligible_as_case_evidence=False,case_admission_status='pending_publication_layer')
            elif collection=='blacklist_cases':
                item.update(source_kind='blacklist_case',admission_status='pending_review',verification_status='official_decision_pending_review',
                    evidence_documents=[{'id':'decision-'+source['sha256'][:20],'role':'regulatory_decision','title':item['title'],
                    'url':source['final_url'],'original_path':source['original_path'],'document_path':source['document_path'],
                    'sha256':source['sha256'],'document_sha256':source['document_sha256'],'page_count':source['page_count']}])
        duplicates=[];unique=[]
        for item in items:
            old=next((x for x in state['items'] if x.get('sha256')==source['sha256'] and (collection=='cases' or x.get('article')==item.get('article') and x.get('effective_from')==item.get('effective_from') and normalized(x.get('text',''))==normalized(item.get('text','')))),None)
            if old:duplicates.append(old['id'])
            else:unique.append(item)
        if not unique:return {'data':{'status':'already_present','existing_ids':duplicates,'instruction':'相同原件及条目已经入库，不重复增加记录。'}}
        items=unique;ids=[x['id'] for x in items]
    elif op=='edit':
        if not set(ids)<=set(existing):raise HTTPException(404,'编辑应指向已有条目')
    elif op=='template':
        if collection!='profiles' or len(items)!=1 or ids[0] in existing:raise HTTPException(422,'制作模板须提供一个新内容profile')
        items[0]['scope_review_status']='format_and_case_evidence_pending'
        items[0]['review_status']='pending_human_review'
        items[0]['verification_status']='candidate_unreviewed'
    seeds=Seeds(runtime.root).for_board(board);cat=seeds.catalog()
    if op!='delete':
        for item in items:library_write.validate_change(runtime.root,collection,{**existing.get(item['id'],{}),**item},existing.get(item['id']),board)
    value={'id':str(uuid4()),'operation':op,'collection':collection,'board':board,'ids':ids,'items':items,
           'expected_fingerprint':state['fingerprint'],'summary':str(args.get('summary',''))[:1000],
           'objects':[{'id':i,'title':next((x.get('title',i) for x in items if x['id']==i),existing.get(i,{}).get('title',i))} for i in ids],
           'before':[existing[i] for i in ids if i in existing],'references':references(runtime,board,ids),'status':'pending'}
    if source:value['source']=source
    basis_ids={sid for row in items for sid in row.get('normative_source_ids',[])}
    value['basis']=[{k:row.get(k,'') for k in ('id','title','article','url')} for row in cat['sources'] if row['id'] in basis_ids]
    if op=='template':
        from .template_authoring import prepare_template
        value['template']=prepare_template(runtime.root,rid,board,items[0])
    value['fingerprint']=hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True).encode()).hexdigest()
    if op=='edit' and not value['references'] and all(set(x)<={'id','title','notes','tags','category'} for x in items):
        result=library_admin.update(runtime.root,collection,items,state['fingerprint'],board)
        value.update(status='applied',result=result);runtime.store.update(rid,knowledge_change=value,outcome='completed')
        runtime.trace(rid,'knowledge_applied',{'id':value['id'],'result':result,'source':'explicit_metadata_edit'})
        return {'data':{'status':'applied','summary':value['summary'],'result':result},'terminate':True,'finalize':True}
    runtime.store.update(rid,knowledge_change=value,outcome='waiting_knowledge_confirmation')
    runtime.trace(rid,'knowledge_proposal',value)
    return {'data':{'status':'waiting_knowledge_confirmation','summary':value['summary'],'objects':value['objects'],'references':value['references'],'instruction':'具体变更已显示在对话中，等待用户确认，不能宣称已写入。'},'terminate':True,'finalize':True}


def authorize(runtime,rid,name):
    run=runtime.store.run(rid)
    research=run.get('intent_domain')=='disclosure' and run['stage'] in ('chat','assessment','plan','document','announcement') and name in ('knowledge_web_search','knowledge_download','knowledge_download_read')
    if (run.get('intent_domain')!='knowledge' and not research) or run.get('outcome'):raise HTTPException(403,'当前没有知识库工具权限')
    definitions={x['name'] for x in tools('refresh' if research else run['intent'])}
    if name not in definitions:raise HTTPException(403,'知识库操作超出当前意图')
    return run

def execute(runtime,rid,name,args):
    run=authorize(runtime,rid,name)
    seeds=Seeds(runtime.root,run['board'],{'layer':run['board'],'stock_code':run.get('company_code','')})
    runtime.trace(rid,'knowledge_requested',{'name':name,'args':args})
    if name in ('knowledge_import_batch_propose','knowledge_imports','knowledge_history','knowledge_import_url','knowledge_import_read','knowledge_import_propose','knowledge_template_replace','knowledge_delete_prepare'):
        return file_operation(runtime,rid,name,args)
    if name=='knowledge_search':
        data=library.search(seeds,args['collection'],args['query'])
        if args['collection'] in ('cases','blacklist_cases'):data['pending']=library.search(seeds,args['collection'],args['query'],view='candidates')
    elif name=='knowledge_read':data=library.item(seeds,args['item_id'])
    elif name=='knowledge_web_search':data=public_sources.search(args['query'],run['board'])
    elif name=='knowledge_download':data=public_sources.acquire(runtime.root,rid,run['board'],args['url'])
    elif name=='knowledge_download_read':
        source,doc=public_sources.receipt(runtime.root,rid,args['download_id']);page=args['page'];offset=args.get('offset',0)
        if type(page)!=int or not 1<=page<=len(doc['pages']) or type(offset)!=int or offset<0:raise HTTPException(422,'页码或分段位置无效')
        body=doc['pages'][page-1]['text'];data={'source':source,'page':page,'text':body[offset:offset+30000],'next_offset':offset+30000 if len(body)>offset+30000 else None,'links':[public_sources.urljoin(source['final_url'],s) for s in doc.get('links',[])][:80]}
    elif name=='knowledge_propose':return prepare(runtime,rid,args)
    else:raise HTTPException(403,'未登记知识工具')
    runtime.trace(rid,'knowledge_returned',{'name':name,'result':data});return {'data':data}


def confirm(runtime,rid,fingerprint,accept,declarations=None):
    with runtime.lock:
        run=runtime.store.run(rid);change=run.get('knowledge_change')
        if not change or change.get('fingerprint')!=fingerprint:raise HTTPException(409,'知识变更预览已经变化')
        if change['status']=='partial' and not change.get('file_operation'):
            if not accept:raise HTTPException(409,'内容模板已经写入；当前仅待完成Word模板登记')
            from .template_authoring import register_template
            change['result']['template']=register_template(runtime.root,run['board'],change['template'])
            change['status']='applied';runtime.store.update(rid,knowledge_change=change,status='completed',outcome='completed');return change
        if change['status'] not in ('pending','partial'):return change
        if run['status'] in ('accepted','running','cancelling'):raise HTTPException(409,'请等待本轮结束')
        if not accept:
            change['status']='rejected';runtime.store.update(rid,knowledge_change=change,status='completed');return change
        if change.get('file_operation'):
            from . import file_ingestion,template_authoring,library_workspace
            if change['operation']=='file_import_batch':
                flags=declarations or {};done=change.setdefault('completed_imports',[])
                try:
                    for item in change['imports']:
                        if item['import_id'] in done:continue
                        metadata={**item['metadata'],**{k:flags.get(k) is True for k in ('publication_confirmed','extraction_confirmed','company_confirmed')}}
                        applied=file_ingestion.commit(runtime.root,item['import_id'],change['board'],change['collection'],change['company'],metadata,'用户在对话中确认本批',change['expected_fingerprint'])
                        if change['collection']=='history' and applied.get('index',{}).get('status')!='current':raise HTTPException(409,'原件已保存，但历史公告索引未完成；重试只重建索引')
                        done.append(item['import_id'])
                        change['expected_fingerprint']=applied['fingerprint']
                        runtime.store.update(rid,knowledge_change=change)
                except HTTPException as exc:
                    change.update(status='partial',result={'completed':len(done),'remaining':len(change['imports'])-len(done),'message':exc.detail})
                    runtime.store.update(rid,knowledge_change=change,status='waiting_knowledge_confirmation');raise
                result={'status':'applied','completed':len(done),'remaining':0}
            elif change['operation']=='file_import':
                flags=declarations or {}
                metadata={**change['metadata'],**{k:flags.get(k) is True for k in ('publication_confirmed','extraction_confirmed','company_confirmed')}}
                result=file_ingestion.commit(runtime.root,change['import_id'],change['board'],change['collection'],change['company'],metadata,'用户在对话中确认',change['expected_fingerprint'])
                if change['collection']=='history' and result.get('index',{}).get('status')!='current':
                    change.update(status='partial',result=result);runtime.store.update(rid,knowledge_change=change,status='waiting_knowledge_confirmation')
                    raise HTTPException(409,'原件已保存，但历史公告索引未完成；重试只重建索引')
            elif change['operation']=='template_replace':result=template_authoring.replacement(runtime.root,change['board'],change['import_id'],change['profile_id'],change['company'],change['expected_fingerprint'],True)
            else:result=library_workspace.delete(runtime.root,runtime,change['preview'],change['preview']['fingerprint'])
            change.update(status='applied',result=result);runtime.store.update(rid,knowledge_change=change,status='completed',outcome='completed')
            if change['operation'] in ('file_import','file_import_batch') and change['collection']=='history':
                from .announcement_review import enqueue
                if change['operation']=='file_import':ids=[result['id']]
                else:ids=[file_ingestion.get(runtime.root,i,change['board'],company=change['company'])['result']['id'] for i in done]
                result['classification_run']=enqueue(runtime,change['board'],change['company'],ids,run['model']['key']) if run['model'].get('key') else {'status':'waiting_model','reason':'原会话未记录模型，请选择模型后重试分类'}
                runtime.store.update(rid,knowledge_change=change)
            runtime.trace(rid,'knowledge_applied',{'operation':change['operation'],'result':result,'source':'browser_confirmation'})
            return change
        board=run['board'];collection=change['collection']
        # Recheck actual references and input fingerprints at the commit boundary.
        if references(runtime,board,change['ids'])!=change['references']:raise HTTPException(409,'引用范围已变化，请重新预览')
        if change['operation']=='delete':result=library_admin.remove(runtime.root,collection,change['ids'],change['expected_fingerprint'],board)
        else:
            result=library_admin.update(runtime.root,collection,change['items'],change['expected_fingerprint'],board)
            if change.get('template'):
                from .template_authoring import register_template
                try:result['template']=register_template(runtime.root,board,change['template'])
                except Exception:
                    change.update(status='partial',result=result);runtime.store.update(rid,knowledge_change=change,status='waiting_knowledge_confirmation');return change
        change.update(status='applied',result=result);runtime.store.update(rid,knowledge_change=change,status='completed',outcome='completed')
        runtime.trace(rid,'knowledge_applied',{'id':change['id'],'result':result,'source':'browser_confirmation'})
        return change


def file_operation(runtime,rid,name,args):
    from . import file_ingestion,announcement_history as history,template_authoring,library_workspace
    run=runtime.store.run(rid);board=run['board'];company=run.get('company_code','')
    if name=='knowledge_import_batch_propose':
        incoming=args.get('imports');items=[];sources=[]
        if not isinstance(incoming,list) or not 1<=len(incoming)<=200:raise HTTPException(422,'请提供本批具体文件')
        for item in incoming:
            source=file_ingestion.get(runtime.root,item['import_id'],board,owner=rid)
            if source['company'] and source['company']!=company:raise HTTPException(403,'文件不属于本轮公司')
            if source['collection']=='profiles':raise HTTPException(422,'手工模板逐份核对版本后替换')
            metadata={k:v for k,v in item['metadata'].items() if k in ('title','url','kind','published_at','effective_from','effective_to','instrument_id','article','stock_code','company_name','related_ids','authority','decision_number','disposition_type','announcement_kinds','violation_types','wrongdoing_summary','regulator_finding','drafting_checks')}
            if not metadata.get('title'):raise HTTPException(422,'每份文件均须有标题')
            sources.append(source);items.append({'import_id':source['id'],'metadata':metadata})
        if len({s['id'] for s in sources})!=len(sources) or len({(s['collection'],s['company']) for s in sources})!=1:raise HTTPException(422,'同一批须为同一资料库及公司，文件不可重复')
        collection=sources[0]['collection'];scope_company=sources[0]['company']
        state=history.state(runtime.root,board,scope_company) if collection=='history' else library_admin.state(runtime.root,collection,board)
        change={'id':str(uuid4()),'operation':'file_import_batch','file_operation':True,'status':'pending','board':board,'company':scope_company,'collection':collection,
            'imports':items,'expected_fingerprint':state['fingerprint'],'summary':args['summary'],'objects':[{'id':i['import_id'],'title':i['metadata']['title']} for i in items],
            'items':[i['metadata'] for i in items],'before':[],'references':[],'requires_publication_confirmation':collection=='history',
            'requires_extraction_confirmation':any(s['document']['needs_review'] for s in sources)}
        change['fingerprint']=library_admin.sha(history.encoded(change));runtime.store.update(rid,knowledge_change=change,outcome='waiting_knowledge_confirmation');runtime.trace(rid,'knowledge_proposal',change)
        return {'data':{'status':'waiting_knowledge_confirmation','count':len(items),'instruction':'本批文件已集中呈现，等待用户一次确认。'},'terminate':True,'finalize':True}
    if name=='knowledge_imports':
        rows=[]
        for path in (runtime.local_root/'work/library-imports').glob('*/receipt.json'):
            value=json.loads(path.read_text())
            if value['board']==board and (not value['company'] or value['company']==company) and value.get('status')=='prepared':
                rows.append({k:value.get(k) for k in ('id','filename','collection','company','status','created_at')})
        return {'data':{'items':rows,'scope':{'board':board,'company':company}}}
    if name=='knowledge_history':
        history.company_key(company)
        if args.get('item_id'):return {'data':history.read(runtime.root,board,company,args['item_id'],args.get('page',1))}
        value=history.search(runtime.root,{'layer':board,'stock_code':company},args.get('query',''),args.get('offset',0))
        return {'data':value}
    if name=='knowledge_import_url':
        raw,_,url=public_sources.fetch(args['url'])
        scope=company if args['collection'] in ('history','profiles') else ''
        value=file_ingestion.prepare(runtime.root,board,args['collection'],raw,url.rsplit('/',1)[-1],scope,url,rid)
        return {'data':{'import_id':value['id'],'fields':value['fields'],'warnings':value['document']['warnings'],'instruction':'用 import_read 核对原文，再提交入库元数据。'}}
    if name=='knowledge_delete_prepare':
        preview=library_workspace.deletion_preview(runtime.root,runtime,board,args['collection'],args['ids'],company if args['collection']=='history' else '')
        change={**preview,'operation':'file_delete','preview':preview,'summary':'删除所选资料','file_operation':True}
    else:
        source=file_ingestion.get(runtime.root,args['import_id'],board,owner=rid)
        if source['company'] and source['company']!=company:raise HTTPException(403,'文件不属于本轮公司')
        if name=='knowledge_import_read':
            pages=source['document']['pages'];page=args.get('page',1)
            if type(page)!=int or not 1<=page<=len(pages):raise HTTPException(422,'页码无效')
            return {'data':{'import_id':source['id'],'collection':source['collection'],'company':source['company'],'page_count':len(pages),'page':pages[page-1],'fields':source['fields'],'warnings':source['document']['warnings'],'metadata_needed':['title','url','published_at' if source['collection']!='laws' else 'effective_from']}}
        if name=='knowledge_template_replace':
            preview=template_authoring.replacement(runtime.root,board,source['id'],args['profile_id'],source['company'])
            change={'operation':'template_replace','profile_id':args['profile_id'],'expected_fingerprint':preview['fingerprint'],'summary':preview['message'],'before':[preview]}
        else:
            metadata={k:v for k,v in args['metadata'].items() if k in ('title','url','kind','published_at','effective_from','effective_to','instrument_id','article','stock_code','company_name','related_ids','authority','decision_number','disposition_type','announcement_kinds','violation_types','wrongdoing_summary','regulator_finding','drafting_checks')}
            if not metadata.get('title'):raise HTTPException(422,'请提供资料标题')
            state=history.state(runtime.root,board,company) if source['collection']=='history' else library_admin.state(runtime.root,source['collection'],board)
            change={'operation':'file_import','metadata':metadata,'summary':args['summary'],'expected_fingerprint':state['fingerprint'],'items':[metadata],
                'requires_publication_confirmation':source['collection']=='history','requires_extraction_confirmation':source['document']['needs_review'],
                'source_preview':source['document']['pages'][0]['text'][:6000]}
        change.update(file_operation=True,board=board,collection=source['collection'],company=source['company'],import_id=source['id'],ids=[source['id']],objects=[{'id':source['id'],'title':change.get('metadata',{}).get('title',source['suggested_title'])}],references=[])
    change.setdefault('items',[]);change.setdefault('before',[])
    change.update(id=str(uuid4()),status='pending');change['fingerprint']=library_admin.sha(history.encoded(change))
    runtime.store.update(rid,knowledge_change=change,outcome='waiting_knowledge_confirmation')
    runtime.trace(rid,'knowledge_proposal',change)
    return {'data':{'status':'waiting_knowledge_confirmation','objects':change['objects'],'instruction':'用户确认后由同一文件服务执行，尚未入库或删除。'},'terminate':True,'finalize':True}
