"""Build an offline Release .app and DMG. Never packages the developer's local state."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP))
from backend.knowledge_packages import digest, load
from scripts.refresh_knowledge_packages import refresh
from scripts.macos_bundle import BUNDLE_ID

VERSION = '1.0.0'
APP_NAME = 'NERO 信披系统.app'
SKIP = {'.git', '__pycache__', '.pytest_cache', '.DS_Store', 'node_modules', '.venv'}
MACH = {b'\xcf\xfa\xed\xfe', b'\xce\xfa\xed\xfe', b'\xca\xfe\xba\xbe', b'\xca\xfe\xba\xbf'}


def run(argv, **kwargs):
    print('RUN', ' '.join(map(str, argv)), flush=True)
    return subprocess.run(list(map(str, argv)), check=True, **kwargs)


def ignored(folder, names):
    return [n for n in names if n in SKIP or n.endswith(('.pyc', '.log', '.tsbuildinfo'))]


def copy_source(destination):
    rows=[]
    for relative in ('backend','scripts','skills','docs','tests','native','frontend/src','frontend/dist','frontend/public'):
        source=APP/relative
        if source.exists():shutil.copytree(source,destination/relative,ignore=ignored)
    for relative in ('requirements.txt','requirements.lock.txt','pytest.ini','frontend/index.html','frontend/package.json',
                     'frontend/package-lock.json','frontend/tsconfig.json','frontend/vite.config.ts',
                     'config/pi-models.example.json','config/model-contract.json','config/workspace-layout.json'):
        source=APP/relative
        if source.is_file():
            target=destination/relative;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,target)
    for target in sorted(destination.rglob('*')):
        if target.is_file():
            relative=target.relative_to(destination).as_posix()
            original=APP/relative
            if digest(original)!=digest(target):raise RuntimeError('源代码在构建期间变化：'+relative)
            rows.append({'path':relative,'sha256':digest(target),'bytes':target.stat().st_size})
    return rows


def copy_python(source, site, target):
    # A relocatable standalone distribution, never the host .venv or its links.
    shutil.copytree(source,target,symlinks=True,ignore=ignored)
    site_target=target/'lib/python3.13/site-packages'
    site_target.mkdir(exist_ok=True)
    def skip_site(folder,names):
        return ignored(folder,names)+[n for n in names if n in ('_virtualenv.py','_virtualenv.pth')]
    shutil.copytree(site,site_target,dirs_exist_ok=True,symlinks=True,ignore=skip_site)
    # Executable scripts are not used. Their build-machine shebangs are not portable.
    for path in (target/'bin').iterdir():
        if not path.is_symlink() and path.is_file() and path.name!='python3.13':
            raw=path.read_bytes()
            if raw.startswith(b'#!'):
                first,separator,body=raw.partition(b'\n')
                if b'python' in first:path.write_bytes(b'#!/usr/bin/env python3\n'+body)
    library=target/'lib/libpython3.13.dylib'
    run(['install_name_tool','-id','@rpath/libpython3.13.dylib',library])
    for path in target.rglob('*'):
        if path.is_symlink():
            if not path.resolve().is_relative_to(target.resolve()):raise RuntimeError('Python 存在外部链接：'+str(path))


def copy_pi(target):
    source=APP/'runtime/pi';target.mkdir(parents=True)
    for file in source.iterdir():
        if file.suffix=='.mjs' or file.name in ('package.json','package-lock.json'):
            shutil.copy2(file,target/file.name)
    shutil.copytree(source/'node_modules',target/'node_modules',symlinks=True,
                    ignore=lambda folder,names:[n for n in names if n in ('.DS_Store','__pycache__')])
    for path in (target/'node_modules').rglob('*'):
        if path.is_symlink() and not path.resolve().is_relative_to(target.resolve()):raise RuntimeError('Pi 依赖含外部链接')
        if path.suffix in ('.node','.dylib','.so'):raise RuntimeError('Pi 新增原生依赖，需要按目标架构准备：'+str(path))


def copy_knowledge(source,target):
    # Reuse the declared public package only. Company history and local work stay private.
    selected=source/'packages/chinext-disclosure-shared.json'
    snapshot=json.loads(selected.read_text())
    if snapshot.get('id')!='chinext-disclosure-shared' or snapshot.get('depends_on'):
        raise RuntimeError('公共知识包身份或依赖发生变化，请重新核对')
    target.mkdir()
    source_hashes=[]
    for folder in ('data/public','templates'):
        for original in sorted((source/folder).rglob('*')):
            if original.is_symlink():raise RuntimeError('知识包包含链接')
            if not original.is_file() or original.name=='.DS_Store' or original.name.endswith(('.lock','-wal','-shm')):continue
            rel=original.relative_to(source).as_posix()
            destination=target/rel;destination.parent.mkdir(parents=True,exist_ok=True)
            before=digest(original)
            if original.suffix=='.sqlite3':
                # Consistent copy of a potentially live projection; preserve source untouched.
                import sqlite3
                with sqlite3.connect(original.resolve().as_uri()+'?mode=ro',uri=True) as src:
                    with sqlite3.connect(destination) as dst:src.backup(dst)
            else:shutil.copy2(original,destination)
            if digest(original)!=before:raise RuntimeError('知识文件在构建中发生变化：'+rel)
            if original.suffix!='.sqlite3' and digest(destination)!=before:raise RuntimeError('知识副本不符：'+rel)
            source_hashes.append({'path':rel,'source_sha256':before,'copied_sha256':digest(destination)})
    refresh(target,target/'packages')
    return source_hashes


def native_binaries(bundle,arch,cache):
    sdk=subprocess.check_output(['xcrun','--show-sdk-path'],text=True).strip()
    code=bundle/'Contents/Resources/01_app'
    binary=bundle/'Contents/MacOS/NERO Disclosure'
    helper=code/'runtime/macos/bin/disclosure-ocr'
    binary.parent.mkdir(parents=True);helper.parent.mkdir(parents=True)
    for source,output in ((code/'native/macos/Launcher.swift',binary),(code/'native/macos/DocumentOCR.swift',helper)):
        run(['xcrun','swiftc','-O','-whole-module-optimization','-swift-version','5',
             '-target',arch+'-apple-macos13.5','-sdk',sdk,'-module-cache-path',cache,source,'-o',output])


def icon(bundle,work):
    source=APP/'frontend/public/disclosure-window-a.png'
    folder=work/'AppIcon.iconset';folder.mkdir()
    for size in (16,32,128,256,512):
        for factor,suffix in ((1,''),(2,'@2x')):
            run(['sips','-z',str(size*factor),str(size*factor),source,'--out',folder/f'icon_{size}x{size}{suffix}.png'],stdout=subprocess.DEVNULL)
    run(['iconutil','-c','icns',folder,'-o',bundle/'Contents/Resources/AppIcon.icns'])


def sign(bundle,identity):
    binaries=[]
    for file in bundle.rglob('*'):
        if file.is_file() and not file.is_symlink():
            with file.open('rb') as stream:magic=stream.read(4)
            if magic in MACH:binaries.append(file)
    for file in sorted(binaries,key=lambda p:len(p.parts),reverse=True):
        cmd=['codesign','--force','--sign',identity,'--options','runtime' if identity!='-' else '0']
        if identity=='-':cmd.append('--timestamp=none')
        else:cmd.append('--timestamp')
        if file.name=='node':cmd += ['--entitlements',APP/'native/macos/runtime.entitlements.plist']
        run(cmd+[file],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    return binaries


def payload_manifest(bundle,metadata):
    rows=[]
    for path in sorted(bundle.rglob('*')):
        rel=path.relative_to(bundle).as_posix()
        if rel.startswith('Contents/_CodeSignature/') or rel=='Contents/MacOS/NERO Disclosure' or path.name=='PAYLOAD_MANIFEST.json':continue
        if path.is_symlink():rows.append({'path':rel,'link':os.readlink(path)})
        elif path.is_file():rows.append({'path':rel,'bytes':path.stat().st_size,'sha256':digest(path)})
    (bundle/'Contents/Resources/PAYLOAD_MANIFEST.json').write_text(json.dumps({**metadata,'files':rows},ensure_ascii=False,indent=2)+'\n')
    return len(rows)


def build(args):
    output=args.output.resolve()
    if output.exists():raise RuntimeError('构建目标已存在，拒绝覆盖：'+str(output))
    output.mkdir(parents=True)
    media=output/'media';media.mkdir()
    bundle=media/APP_NAME
    code=bundle/'Contents/Resources/01_app';code.mkdir(parents=True)
    source_rows=copy_source(code)
    runtime=code/'runtime/macos'
    copy_python(args.python_root.resolve(),args.site_packages.resolve(),runtime/'python')
    node=runtime/'node/bin';node.mkdir(parents=True)
    shutil.copy2(args.node_root/'bin/node',node/'node')
    shutil.copy2(args.node_root/'LICENSE',runtime/'node/LICENSE')
    copy_pi(code/'runtime/pi')
    shutil.copy2(APP/'runtime/portable-runtime.lock.tsv',code/'runtime/portable-runtime.lock.tsv')
    work=output/'build-work';work.mkdir()
    native_binaries(bundle,args.arch,APP.parent/'03_local/cache/macos-release'/('swift-'+args.arch))
    icon(bundle,work)
    info={'CFBundleIdentifier':BUNDLE_ID,'CFBundleName':'NERO 信披系统','CFBundleDisplayName':'NERO 信披系统',
          'CFBundleExecutable':'NERO Disclosure','CFBundlePackageType':'APPL','CFBundleShortVersionString':VERSION,
          'CFBundleVersion':'2026091703','LSMinimumSystemVersion':'13.5','NSHighResolutionCapable':True,
          'CFBundleIconFile':'AppIcon.icns','NSPrincipalClass':'NSApplication'}
    (bundle/'Contents/Info.plist').write_bytes(plistlib.dumps(info))
    knowledge_rows=copy_knowledge(APP.parent/'02_knowledge',media/'02_knowledge')
    load(media/'02_knowledge',code,full=True)
    metadata={'schema':'nero.disclosure.macos-release.v1','version':VERSION,'architecture':args.arch,
              'build_configuration':'Release','minimum_macos':'13.5',
              'developer_id_signed':args.identity!='-','notarized':False,
              'hardened_runtime':args.identity!='-',
              'built_at':datetime.now(timezone.utc).isoformat(),
              'knowledge_package':'chinext-disclosure-shared','personal_data_included':False,
              'source_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=APP,text=True).strip()}
    (code/'MACOS_RELEASE.json').write_text(json.dumps(metadata,ensure_ascii=False,indent=2)+'\n')
    # Record immutable software separately from the editable knowledge snapshot.
    manifest={'schema_version':'nero.disclosure.manifest.v1','product':'NERO_Disclosure','version':VERSION,
              'scope':'source','path_base':'app','producer':{'name':'NERO','label':'NERO 出品'},
              'files_count':len(source_rows),'files':source_rows}
    (code/'BUILD_MANIFEST.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
    sign(bundle,args.identity)
    count=payload_manifest(bundle,metadata)
    cmd=['codesign','--force','--sign',args.identity,'--options','runtime' if args.identity!='-' else '0',
         '--timestamp=none' if args.identity=='-' else '--timestamp',bundle]
    run(cmd)
    run(['codesign','--verify','--deep','--strict',bundle])
    readme=(APP/'native/macos/INSTALL.txt').read_text()
    (media/'安装说明.txt').write_text(readme)
    result={**metadata,'app':str(bundle),'payload_files':count,'source_files':source_rows,
            'knowledge_files':knowledge_rows,'code_signing_verified':True}
    if args.dmg:
        suffix='-unsigned' if args.identity=='-' else '-unnotarized'
        image=output/f'NERO-Disclosure-{VERSION}-macOS-{args.arch}{suffix}.dmg'
        run(['hdiutil','create','-volname','NERO 信披系统','-srcfolder',media,'-format','UDZO',image])
        result.update(dmg=str(image),dmg_sha256=digest(image),dmg_bytes=image.stat().st_size)
        run(['hdiutil','verify',image])
    (output/'BUILD_RECEIPT.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k not in ('source_files','knowledge_files')},ensure_ascii=False,indent=2))


def main():
    parser=argparse.ArgumentParser(description='正式 Mac 离线发行构建；不发布或提交公证')
    parser.add_argument('--arch',choices=('arm64','x86_64'),required=True)
    parser.add_argument('--python-root',type=Path,required=True)
    parser.add_argument('--site-packages',type=Path,required=True)
    parser.add_argument('--node-root',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--identity',default='-',help='Developer ID；默认只作 ad-hoc 完整性签名')
    parser.add_argument('--dmg',action='store_true')
    build(parser.parse_args())


if __name__=='__main__':main()
