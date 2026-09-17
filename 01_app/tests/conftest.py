"""Shared test seeding.

Default runs seed from the repository's fictional fixture workspace
(``tests/fixtures/knowledge``), so the suite needs no licensed knowledge pack
and copies a few hundred KB per test instead of the full business library.

Set ``NERO_DISCLOSURE_KNOWLEDGE_ROOT`` to a licensed knowledge root to run the
``knowledge_pack`` integration tests against real data; those tests are skipped
otherwise.

macOS APFS clones (``cp -c``) give the same isolation for a few hundred KB and
stay copy-on-write: writing to the clone never reaches the project source,
including in-place writes. Other platforms keep the ordinary copy.
"""
import shutil
import subprocess
import sys
import os
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = ROOT.parent
# 默认使用仓库自带的虚构样例；显式设置环境变量时改用经授权的知识包。
FIXTURE_KNOWLEDGE = ROOT / 'tests' / 'fixtures' / 'knowledge'
_external = os.environ.get('NERO_DISCLOSURE_KNOWLEDGE_ROOT')
KNOWLEDGE = Path(_external).expanduser().resolve() if _external else FIXTURE_KNOWLEDGE
KNOWLEDGE_IS_FIXTURE = not _external
# 三类布局：知识与本机资料位于软件根同级；旧式单根目录三者都落在 ROOT 内。
LOCAL = WORKSPACE / '03_local'
# 测试禁止写入的正式资料范围：样例目录、正式知识原件与模板、本项目 Skill 与本机业务目录。
PROTECTED = (FIXTURE_KNOWLEDGE, WORKSPACE / '02_knowledge', ROOT / 'skills',
             LOCAL / 'var', LOCAL / 'work', LOCAL / 'output', LOCAL / 'design-output')


def pytest_collection_modifyitems(config, items):
    """Skip tests that need a licensed knowledge pack unless one is configured."""
    if not KNOWLEDGE_IS_FIXTURE:
        return
    skip = pytest.mark.skip(reason='需要经授权的知识包：设置 NERO_DISCLOSURE_KNOWLEDGE_ROOT 后运行')
    for item in items:
        if 'knowledge_pack' in item.keywords:
            item.add_marker(skip)


def seed_tree(source, target):
    """Create a writable tree that cannot modify the project source."""
    source, target = Path(source), Path(target)
    if any(target.resolve().is_relative_to(p) for p in (ROOT, KNOWLEDGE, LOCAL)) or target.exists():
        raise ValueError('测试资料必须复制到项目外的全新临时目录')
    if source.is_dir() and sys.platform == 'darwin':
        result = subprocess.run(['cp', '-c', '-R', str(source), str(target)],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if result.returncode == 0 and target.is_dir():
            return target
        # Only this helper's newly-created failed clone may be removed.
        if target.is_dir():
            shutil.rmtree(target)
    return Path(shutil.copytree(source, target))


def isolated_root(tmp_path):
    """API test roots include knowledge writes, not just an isolated SQLite file."""
    root = tmp_path / 'project'
    if root.resolve().is_relative_to(ROOT):
        raise ValueError('测试根目录必须在项目外，例如 /tmp；不得以正式目录启动模拟服务')
    marker = root / '.isolated-test-seed'
    if root.exists():
        if marker.is_file() and marker.read_text() == str(ROOT):
            return root
        raise ValueError('拒绝复用未经本测试初始化的目录')
    root.mkdir()
    seed_project(root)
    marker.write_text(str(ROOT))
    return root


def seed_project(root):
    """把测试所需知识与规则复制到隔离根：data、templates 来自知识根，skills 来自软件根。"""
    root = Path(root)
    for folder in ('data', 'templates'):
        seed_tree(KNOWLEDGE / folder, root / folder)
    seed_tree(ROOT / 'skills', root / 'skills')
    return root


_protect_live_data = False


def deny_live_write(event, args):
    """Fail before a Python test writes real knowledge/runtime data (also via symlinks)."""
    if not _protect_live_data:
        return
    paths = []
    if event == 'open':
        path, mode, flags = args
        if (mode and any(c in mode for c in 'wax+')) or flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND):
            paths = [path]
    elif event in ('os.remove', 'os.rmdir', 'os.mkdir', 'os.chmod', 'os.utime', 'os.truncate'):
        paths = args[:1]
    elif event in ('os.rename', 'os.link', 'os.symlink'):
        paths = args[:2]
    elif event == 'sqlite3.connect':
        value = str(args[0])
        if value != ':memory:' and 'mode=ro' not in value:
            paths = [value.removeprefix('file:').split('?')[0]]
    for value in paths:
        if isinstance(value, (str, bytes, os.PathLike)):
            path = Path(os.fsdecode(value)).resolve()
            if any(path.is_relative_to(part) for part in PROTECTED):
                raise PermissionError('测试禁止写入正式资料，请使用 isolated_root/seed_tree：' + str(path))


def pytest_sessionstart(session):
    global _protect_live_data
    _protect_live_data = True
    sys.addaudithook(deny_live_write)


def pytest_sessionfinish(session, exitstatus):
    global _protect_live_data
    _protect_live_data = False


def ready_layout(root):
    """Synthetic layout readiness for workflow tests; never alter the real template gate."""
    import json
    path=Path(root)/'templates/boards/chinext/layout_profiles.json'
    if any(path.resolve().is_relative_to(part) for part in PROTECTED):raise ValueError('禁止改写正式版式')
    rows=json.loads(path.read_text())
    for row in rows:row['scope_review_status']='synthetic_fixture_only_not_human_acceptance'
    path.write_text(json.dumps(rows,ensure_ascii=False))
