"""Build one Release updater DMG, with both architectures and no user data."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys

APP=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(APP))
from scripts.build_macos_release import APP_NAME, VERSION, icon, run
from scripts.macos_bundle import verify_payload, digest


def validate_inputs(payloads, version):
    identities=[]
    for arch,bundle in payloads.items():
        metadata=verify_payload(bundle)
        if metadata.get('version')!=version or metadata.get('architecture')!=arch:
            raise ValueError('软件版本或架构不匹配')
        if metadata.get('software_only') is not True or metadata.get('personal_data_included') is not False:
            raise ValueError('更新包只接受不含个人资料的程序载荷')
        for path in bundle.rglob('*'):
            if any(part in ('02_knowledge','03_local','MigrationData') for part in path.relative_to(bundle).parts):
                raise ValueError('程序载荷含资料目录，拒绝打包')
        identities.append(metadata['source_commit'])
    if len(set(identities))!=1:raise ValueError('两个架构不属于同一源码提交')
    return identities[0]


def build(args):
    output=args.output.resolve()
    if output.exists():raise ValueError('目标已存在，拒绝覆盖')
    payloads={'arm64':args.arm64.resolve(),'x86_64':args.x86_64.resolve()}
    identity=validate_inputs(payloads,args.version)
    assembler=subprocess.check_output(['git','rev-parse','HEAD'],cwd=APP,text=True).strip()
    if assembler!=identity:raise ValueError('更新器与软件载荷不属于同一源码提交')
    output.mkdir(parents=True)
    media=output/'media';media.mkdir()
    updater=media/'更新 NERO 信披系统.app'
    resources=updater/'Contents/Resources';resources.mkdir(parents=True)
    binary=updater/'Contents/MacOS/NERO Disclosure Updater';binary.parent.mkdir()
    for arch,source in payloads.items():
        destination=resources/'Applications'/arch/APP_NAME
        destination.parent.mkdir(parents=True)
        shutil.copytree(source,destination,symlinks=True)
        verify_payload(destination)
    work=output/'build-work';work.mkdir()
    icon(updater,work)
    sdk=subprocess.check_output(['xcrun','--show-sdk-path'],text=True).strip()
    parts=[]
    for arch in payloads:
        part=work/('updater-'+arch)
        run(['xcrun','swiftc','-O','-whole-module-optimization','-swift-version','5',
             '-target',arch+'-apple-macos13.5','-sdk',sdk,'-module-cache-path',
             APP.parent/'03_local/cache/macos-release'/('swift-'+arch),
             APP/'native/macos/Launcher.swift','-o',part])
        parts.append(part)
    run(['lipo','-create',*parts,'-output',binary])
    info={'CFBundleIdentifier':'cn.nero.disclosure.updater','CFBundleName':'更新 NERO 信披系统',
          'CFBundleDisplayName':'更新 NERO 信披系统','CFBundleExecutable':binary.name,
          'CFBundlePackageType':'APPL','CFBundleShortVersionString':args.version,
          'CFBundleVersion':args.build_number,'LSMinimumSystemVersion':'13.5',
          'CFBundleIconFile':'AppIcon.icns','NSHighResolutionCapable':True,
          'NSPrincipalClass':'NSApplication','NEROSoftwareUpdateInstaller':True}
    (updater/'Contents/Info.plist').write_bytes(plistlib.dumps(info))
    # 更新包只交付更新器本身；安装与更新说明不随介质分发。
    metadata={'schema':'nero.disclosure.macos-update.v1','version':args.version,
              'source_commit':identity,'build_configuration':'Release','architectures':list(payloads),
              'built_at':datetime.now(timezone.utc).isoformat(),'minimum_macos':'13.5',
              'personal_data_included':False,'knowledge_included':False,
              'developer_id_signed':False,'notarized':False}
    (resources/'UPDATE_MANIFEST.json').write_text(json.dumps(metadata,ensure_ascii=False,indent=2)+'\n')
    run(['codesign','--force','--sign','-','--timestamp=none',updater])
    run(['codesign','--verify','--deep','--strict',updater])
    image=output/f'NERO-Disclosure-{args.version}-macOS-update-unsigned.dmg'
    run(['hdiutil','create','-volname','NERO 信披系统 '+args.version+' 程序更新',
         '-srcfolder',media,'-format','UDZO',image])
    run(['hdiutil','verify',image])
    result={**metadata,'dmg':str(image),'sha256':digest(image),'bytes':image.stat().st_size}
    (output/'BUILD_RECEIPT.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--arm64',type=Path,required=True)
    parser.add_argument('--x86-64',dest='x86_64',type=Path,required=True)
    parser.add_argument('--version',default=VERSION)
    parser.add_argument('--build-number',default='2026091801')
    parser.add_argument('--output',type=Path,required=True)
    build(parser.parse_args())
