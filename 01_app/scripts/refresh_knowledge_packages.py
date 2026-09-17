"""Create or verify portable knowledge snapshots; never modify source assets."""
import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from backend import paths
from backend import knowledge_packages as packages


def inventory(base, selections):
    rows=[]
    for selection in selections:
        folder=packages.contained(base,selection)
        if not folder.is_dir():raise ValueError('知识目录缺失：'+selection)
        for p in sorted(folder.rglob('*')):
            if p.name=='.DS_Store' or p.name.endswith(('-wal','-shm','.lock')):continue
            if p.is_symlink():raise ValueError('知识包不得包含链接')
            if p.is_file():
                rows.append({'path':p.relative_to(base).as_posix(),'bytes':p.stat().st_size,'sha256':packages.digest(p)})
    return rows


def build(base,identity,kind,selections,required,dependencies,company=''):
    files=inventory(base,selections)
    snapshot=hashlib.sha256(json.dumps(files,ensure_ascii=False,sort_keys=True).encode()).hexdigest()
    return {'schema':packages.SCHEMA,'id':identity,'version':'1.'+snapshot[:16],
            'software_contract':packages.SOFTWARE_CONTRACT,'kind':kind,'board':'chinext',
            'company_code':company,'paths':selections,'required_files':required,
            'depends_on':dependencies,'requires_software':list(packages.CAPABILITIES),
            'content_sha256':snapshot,'files':files,'files_count':len(files),
            'bytes':sum(r['bytes'] for r in files),'index_policy':'rebuildable_projection',
            'generated_at':datetime.now(timezone.utc).isoformat()}


def refresh(base,output):
    shared='chinext-disclosure-shared'
    docs=[build(base,shared,'board-shared',['data/public','templates'],
                ['data/public/boards/chinext/'+n+'.json' for n in ('catalog','profiles','instruments','rules','scenarios')]
                +['templates/boards/chinext/manifest.json','templates/boards/chinext/layout_profiles.json'],[])]
    for folder in sorted((base/'data/client_announcements/chinext').glob('*')):
        if not folder.is_dir() or not (folder/'catalog.json').is_file():continue
        code=folder.name
        if len(code)!=6 or not code.isdecimal():raise ValueError('证券代码目录无效')
        relative=folder.relative_to(base).as_posix()
        docs.append(build(base,'chinext-announcements-'+code,'company-announcements',
                          [relative],[relative+'/catalog.json'],[shared],code))
    output.mkdir(parents=True,exist_ok=True)
    entries=[]
    for doc in docs:
        target=output/(doc['id']+'.json')
        target.write_text(json.dumps(doc,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        entries.append({'id':doc['id'],'file':target.name,'sha256':packages.digest(target),
                        'files':doc['files_count'],'bytes':doc['bytes'],'depends_on':doc['depends_on']})
    result={'schema':packages.INDEX_SCHEMA,'knowledge_root':'.','packages':entries}
    (output/'index.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return result


def main():
    parser=argparse.ArgumentParser(description='知识包快照生成与完整性核对')
    parser.add_argument('--knowledge',type=Path,default=paths.knowledge_of(ROOT))
    parser.add_argument('--output',type=Path)
    parser.add_argument('--verify',action='store_true')
    args=parser.parse_args()
    base=args.knowledge.resolve()
    result=packages.load(base,ROOT,full=True) if args.verify else refresh(base,args.output or base/'packages')
    print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':main()
