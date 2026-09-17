"""Release native desktop entry for this existing workspace, without copying data."""
import argparse
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP))
from scripts.portable_runtime import platform_key, check_python
from scripts.build_macos_release import icon, VERSION


def build(output):
    import json
    key = platform_key()
    base = APP/'runtime/portable'/key
    pointer = json.loads((base/'current-python.json').read_text())
    environment = (base/pointer['directory']).resolve()
    python = environment/'bin/python'
    if not environment.is_relative_to(base.resolve()) or pointer['identity']['root'] != str(APP):
        raise ValueError('现有 Python 环境不属于本工作区')
    if check_python(python, APP/'requirements.lock.txt').returncode:
        raise ValueError('现有运行环境校验未通过；未重建或修改环境')
    output = output.resolve()
    if output.exists():raise ValueError('拒绝覆盖已有应用')
    binary = output/'Contents/MacOS/NERO Disclosure'
    resources = output/'Contents/Resources'
    binary.parent.mkdir(parents=True);resources.mkdir()
    arch = 'arm64' if key == 'macos-arm64' else 'x86_64'
    cache = APP.parent/'03_local/cache/macos-release'/('swift-'+arch)
    sdk = subprocess.check_output(['xcrun','--show-sdk-path'],text=True).strip()
    subprocess.run(['xcrun','swiftc','-O','-whole-module-optimization','-swift-version','5',
                    '-target',arch+'-apple-macos13.5','-sdk',sdk,'-module-cache-path',str(cache),
                    str(APP/'native/macos/Launcher.swift'),'-o',str(binary)],check=True)
    work = output.parent/(output.stem+'-icon-build');work.mkdir()
    icon(output,work)
    shutil.copy2(APP/'native/macos/brand.json',resources/'brand.json')
    info = {'CFBundleIdentifier':'cn.nero.disclosure.workspace','CFBundleName':'NERO 信披系统',
            'CFBundleDisplayName':'NERO 信披系统','CFBundleExecutable':'NERO Disclosure',
            'CFBundlePackageType':'APPL','CFBundleShortVersionString':VERSION,
            'CFBundleVersion':'2026091703','LSMinimumSystemVersion':'13.5',
            'CFBundleIconFile':'AppIcon.icns','NSHighResolutionCapable':True,
            'NSPrincipalClass':'NSApplication','NEROBuildConfiguration':'Release',
            'NEROWorkspaceRoot':str(APP.parent),'NEROWorkspacePython':str(python)}
    (output/'Contents/Info.plist').write_bytes(plistlib.dumps(info))
    subprocess.run(['codesign','--force','--sign','-','--timestamp=none',str(output)],check=True)
    subprocess.run(['codesign','--verify','--deep','--strict',str(output)],check=True)
    print(output)


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description='正式构建本机工作区应用入口，不制作迁移安装包')
    parser.add_argument('--output',type=Path,required=True)
    build(parser.parse_args().output)
