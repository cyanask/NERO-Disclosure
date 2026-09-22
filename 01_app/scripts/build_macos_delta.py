"""Build a native, runtime-free updater for one exact pair of signed app trees."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import plistlib
import shutil
import stat
import subprocess
import sys

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP))
from scripts.build_macos_update import validate_inputs
from scripts.macos_bundle import digest, verify_payload
from scripts.build_macos_release import icon, run


def inventory(root):
    root = Path(root)
    rows = {}
    for p in sorted(root.rglob('*')):
        relative = p.relative_to(root).as_posix()
        if p.name == '.DS_Store':continue
        mode = stat.S_IMODE(p.lstat().st_mode)
        if p.is_symlink():
            if not p.resolve().is_relative_to(root.resolve()):raise ValueError('软件链接越界')
            rows[relative] = {'kind':'link', 'link':os.readlink(p)}
        elif p.is_dir():rows[relative] = {'kind':'directory', 'mode':mode}
        elif p.is_file():rows[relative] = {'kind':'file','mode':mode,'sha256':digest(p),'bytes':p.stat().st_size}
        else:raise ValueError('不支持的软件文件类型')
    return rows


def make_delta(old, new, destination):
    before, after = inventory(old), inventory(new)
    destination.mkdir(parents=True)
    changed = [p for p in after if before.get(p) != after[p]]
    blobs = destination/'blobs';blobs.mkdir()
    for name in changed:
        row = after[name]
        if row['kind']=='file':
            target=blobs/row['sha256']
            if not target.exists():shutil.copyfile(new/name,target)
    old_info=plistlib.loads((old/'Contents/Info.plist').read_bytes())
    new_info=plistlib.loads((new/'Contents/Info.plist').read_bytes())
    value={'schema':'nero.disclosure.delta.v1','baseline_version':old_info['CFBundleShortVersionString'],
           'baseline_build':old_info['CFBundleVersion'],'version':new_info['CFBundleShortVersionString'],
           'build':new_info['CFBundleVersion'],'before':before,'after':after}
    (destination/'manifest.json').write_text(json.dumps(value,ensure_ascii=False,separators=(',',':'))+'\n')
    return {'changed_entries':len(changed),'removed_entries':len(set(before)-set(after)),
            'payload_bytes':sum(p.stat().st_size for p in blobs.iterdir()),
            'manifest_sha256':digest(destination/'manifest.json')}


def build(args):
    out=args.output.resolve()
    if out.exists():raise ValueError('拒绝覆盖已有构建目录')
    new={'arm64':args.arm64.resolve(),'x86_64':args.x86_64.resolve()}
    identity=validate_inputs(new,'1.0.2')
    baseline=json.loads((APP/'docs/release-baselines/1.0.1.json').read_text())
    base_root=args.baseline_root.resolve()
    out.mkdir(parents=True)
    media=out/'media';media.mkdir()
    updater=media/'更新 NERO 信披系统.app';resources=updater/'Contents/Resources';resources.mkdir(parents=True)
    binaries=updater/'Contents/MacOS';binaries.mkdir()
    rows={}
    for arch in new:
        old=base_root/arch/'NERO 信披系统.app'
        verify_payload(old)
        expected=baseline['payload_manifests'][arch]['payload']['sha256']
        if digest(old/'Contents/Resources/PAYLOAD_MANIFEST.json')!=expected:raise ValueError('不是冻结的 1.0.1 基线')
        rows[arch]=make_delta(old,new[arch],resources/'Deltas'/arch)
    work=out/'build-work';work.mkdir();icon(updater,work)
    sdk=subprocess.check_output(['xcrun','--show-sdk-path'],text=True).strip()
    for source,name in [('Launcher.swift','NERO Disclosure Updater'),('DeltaApply.swift','DeltaApply')]:
        parts=[]
        for arch in new:
            target=work/(name.replace(' ','-')+'-'+arch)
            run(['xcrun','swiftc','-O','-whole-module-optimization','-swift-version','5','-target',arch+'-apple-macos13.5',
                 '-sdk',sdk,'-module-cache-path',APP.parent/'03_local/cache/macos-release'/('swift-'+arch),APP/'native/macos'/source,'-o',target])
            parts.append(target)
        run(['lipo','-create',*parts,'-output',binaries/name])
        run(['codesign','--force','--sign','-','--timestamp=none',binaries/name])
    info={'CFBundleIdentifier':'cn.nero.disclosure.updater','CFBundleName':'更新 NERO 信披系统',
          'CFBundleDisplayName':'更新 NERO 信披系统','CFBundleExecutable':'NERO Disclosure Updater',
          'CFBundlePackageType':'APPL','CFBundleShortVersionString':'1.0.2','CFBundleVersion':args.build_number,
          'LSMinimumSystemVersion':'13.5','CFBundleIconFile':'AppIcon.icns','NSHighResolutionCapable':True,
          'NSPrincipalClass':'NSApplication','NEROSoftwareUpdateInstaller':True,'NERODeltaUpdateInstaller':True}
    (updater/'Contents/Info.plist').write_bytes(plistlib.dumps(info))
    metadata={'schema':'nero.disclosure.delta-release.v1','version':'1.0.2','baseline':'1.0.1',
              'baseline_build':baseline['build_number'],'build':args.build_number,'architectures':list(new),
              'target_source_commit':identity,'updater_source_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=APP,text=True).strip(),
              'build_configuration':'Release','built_at':datetime.now(timezone.utc).isoformat(),
              'runtime_included':False,'knowledge_included':False,'personal_data_included':False,
              'developer_id_signed':False,'notarized':False,'deltas':rows}
    (resources/'UPDATE_MANIFEST.json').write_text(json.dumps(metadata,ensure_ascii=False,indent=2)+'\n')
    run(['codesign','--force','--sign','-','--timestamp=none',updater]);run(['codesign','--verify','--deep','--strict',updater])
    image=out/'NERO-Disclosure-1.0.2-delta-from-1.0.1-macOS-unsigned.dmg'
    run(['hdiutil','create','-volname','NERO 1.0.2 差分更新','-srcfolder',media,'-format','UDZO',image]);run(['hdiutil','verify',image])
    metadata.update(dmg=str(image),bytes=image.stat().st_size,sha256=digest(image))
    (out/'BUILD_RECEIPT.json').write_text(json.dumps(metadata,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(metadata,ensure_ascii=False,indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--baseline-root',type=Path,required=True)
    parser.add_argument('--arm64',type=Path,required=True);parser.add_argument('--x86-64',dest='x86_64',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True);parser.add_argument('--build-number',required=True)
    build(parser.parse_args())
