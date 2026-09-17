"""Company-scoped facets over the existing, rebuildable history index."""
import json
from fastapi import HTTPException
from . import announcement_history as history, announcement_index as index, announcement_tags as tags


def validate_filter(tag,form):
    if tag and tag not in dict(tags.TAGS):raise HTTPException(422,'未知公告标签')
    if form and form not in dict(tags.FORMS):raise HTTPException(422,'未知文件细分')


def correction(row,value):
    if value is None:return None
    if not isinstance(value,dict) or set(value)-{'tags','forms'}:raise HTTPException(422,'分类校正字段无效')
    for key,options in (('tags',dict(tags.TAGS)),('forms',dict(tags.FORMS))):
        selected=value.get(key)
        if not isinstance(selected,list) or not selected or any(not isinstance(v,str) or v not in options for v in selected) or len(selected)!=len(set(selected)):
            raise HTTPException(422,'请选择有效且不重复的标签和文件细分')
    if 'unclassified' in value['tags'] and len(value['tags'])>1:raise HTTPException(422,'待分类不能与其他标签同时使用')
    return {**value,'source_key':tags.source_key(row),'evidence':{'field':'user_correction'}}


def listing(root,board,company,q='',deleted=False,tag='',form=''):
    validate_filter(tag,form)
    value=history.state(root,board,company)
    rows=value['items'] if deleted else history.visible(value)
    current=index.status(root,board,company)['status']=='current';classified={};matches=set()
    if current:
        db=index.connect(index.paths(root,board,company)[2],True)
        try:
            classified={r[0]:json.loads(r[1]) for r in db.execute('SELECT announcement_id,result_json FROM classifications')}
            if q.strip():
                term=q.strip();like='%'+term.replace('\\','\\\\').replace('%','\\%').replace('_','\\_')+'%'
                matches={r[0] for r in db.execute("SELECT id FROM announcements WHERE title LIKE ? ESCAPE '\\' OR announcement_number LIKE ? ESCAPE '\\'",(like,like))}
                if len(term)>=3:
                    phrase='"'+term.replace('"','""')+'"'
                    matches.update(r[0] for r in db.execute('SELECT DISTINCT u.announcement_id FROM unit_fts JOIN units u ON u.id=unit_fts.unit_id WHERE unit_fts MATCH ?',(phrase,)))
                else:
                    matches.update(r[0] for r in db.execute("SELECT DISTINCT announcement_id FROM units WHERE text LIKE ? ESCAPE '\\'",(like,)))
        finally:db.close()
    enriched=[]
    for row in rows:
        classification=classified.get(row['id']);document=None
        if classification is None:
            # Missing/stale projections fall back to version-checked canonical pages.
            try:document=history.read(root,board,company,row['id'])
            except HTTPException:
                if not row.get('deleted_at'):raise
            classification=tags.classify(row,document)
        if q.strip():
            metadata=json.dumps({k:row.get(k) for k in ('title','announcement_number','meeting')},ensure_ascii=False)
            matched=row['id'] in matches or q.strip().casefold() in metadata.casefold()
            if not current and not matched:
                matched=q.strip().casefold() in '\n'.join(p.get('text','') for p in (document or {}).get('pages',[])).casefold()
            if not matched:continue
        enriched.append({**{k:v for k,v in row.items() if k!='text'},'classification':classification})
    facets=[{'id':identity,'label':label,'count':sum(identity in r['classification']['tags'] for r in enriched),'common':identity in tags.COMMON} for identity,label in tags.TAGS]
    tagged=[r for r in enriched if not tag or tag in r['classification']['tags']]
    forms=[{'id':identity,'label':label,'count':sum(identity in r['classification']['forms'] for r in tagged)} for identity,label in tags.FORMS]
    result=[r for r in tagged if not form or form in r['classification']['forms']]
    return {**value,'items':sorted(result,key=lambda r:(r['published_at'],r.get('announcement_number') or ''),reverse=True),
        'tag_options':facets,'form_options':forms,'matched_total':len(enriched),'total':len(result),'classification_version':tags.VERSION,
        'retrieval_backend':'company_sqlite_fts5' if current else 'canonical_json',
        'related_options':[{'id':r['id'],'title':r['title']} for r in history.visible(value)]}
