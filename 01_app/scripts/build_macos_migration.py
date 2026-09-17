"""One compressed universal Mac installer, two software payloads, one data snapshot."""
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
from scripts.build_macos_release import VERSION, APP_NAME, icon, run
from scripts.macos_bundle import verify_payload, digest
from scripts.migration_install import snapshot_manifest


def build(args):
    output=args.output.resolve()
    if output.exists():raise ValueError('目标已存在，拒绝覆盖')
    value=snapshot_manifest(args.snapshot)
    payloads={'arm64':args.arm64.resolve(),'x86_64':args.x86_64.resolve()}
    identities=[]
    for arch,bundle in payloads.items():
        verified=verify_payload(bundle)
        if verified['version']!=VERSION or verified['architecture']!=arch:
            raise ValueError('软件载荷版本或架构不匹配')
        identities.append(verified['source_commit'])
    if len(set(identities))!=1:raise ValueError('两个架构的软件不属于同一提交')
    output.mkdir(parents=True,mode=0o700)
    media=output/'media';media.mkdir()
    installer=media/'安装 NERO 信披系统.app'
    resources=installer/'Contents/Resources';resources.mkdir(parents=True)
    binary=installer/'Contents/MacOS/NERO Disclosure Installer';binary.parent.mkdir()
    for arch,source in payloads.items():
        destination=resources/'Applications'/arch/APP_NAME
        destination.parent.mkdir(parents=True)
        shutil.copytree(source,destination,symlinks=True)
    data=resources/'MigrationData'
    shutil.copytree(args.snapshot,data)
    # Distribution files must be readable by a different Mac account/UID.
    # The resulting DMG is private on the author's disk; restored homes are 0700.
    for path in (data,*data.rglob('*')):
        path.chmod(0o755 if path.is_dir() or path.stat().st_mode & 0o111 else 0o644)
    work=output/'build-work';work.mkdir()
    icon(installer,work)
    sdk=subprocess.check_output(['xcrun','--show-sdk-path'],text=True).strip()
    parts=[]
    for arch in payloads:
        part=work/('installer-'+arch)
        run(['xcrun','swiftc','-O','-whole-module-optimization','-swift-version','5',
             '-target',arch+'-apple-macos13.5','-sdk',sdk,'-module-cache-path',
             APP.parent/'03_local/cache/macos-release'/('swift-'+arch),
             APP/'native/macos/Launcher.swift','-o',part])
        parts.append(part)
    run(['lipo','-create',*parts,'-output',binary])
    info={'CFBundleIdentifier':'cn.nero.disclosure.installer','CFBundleName':'安装 NERO 信披系统',
          'CFBundleDisplayName':'安装 NERO 信披系统','CFBundleExecutable':binary.name,
          'CFBundlePackageType':'APPL','CFBundleShortVersionString':VERSION,'CFBundleVersion':'2026091703',
          'LSMinimumSystemVersion':'13.5','CFBundleIconFile':'AppIcon.icns','NSHighResolutionCapable':True,
          'NSPrincipalClass':'NSApplication','NEROFullMigrationInstaller':True}
    (installer/'Contents/Info.plist').write_bytes(plistlib.dumps(info))
    shutil.copy2(APP/'native/macos/INSTALL_FULL.txt',media/'安装说明.txt')
    run(['codesign','--force','--sign','-','--timestamp=none',installer])
    run(['codesign','--verify','--deep','--strict',installer])
    image=output/f'NERO-Disclosure-{VERSION}-macOS-full-unsigned.dmg'
    run(['hdiutil','create','-volname','NERO 信披系统 1.0 完整迁移版','-srcfolder',media,'-format','UDZO',image])
    run(['hdiutil','verify',image])
    image.chmod(0o600)
    result={'version':VERSION,'source_commit':identities[0],'migration_id':value['migration_id'],
            'assembler_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=APP,text=True).strip(),
            'built_at':datetime.now(timezone.utc).isoformat(),'dmg':str(image),
            'sha256':digest(image),'bytes':image.stat().st_size,'architectures':list(payloads),
            'data_files':len(value['files']),'developer_id_signed':False,'notarized':False}
    (output/'BUILD_RECEIPT.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--arm64',type=Path,required=True)
    parser.add_argument('--x86-64',dest='x86_64',type=Path,required=True)
    parser.add_argument('--snapshot',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    build(parser.parse_args())
