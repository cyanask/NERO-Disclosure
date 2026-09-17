"""Knowledge-package compatibility and content checks, with no data mutation."""
import hashlib
import json
from pathlib import Path
from . import paths

SCHEMA = 'nero.disclosure.knowledge-package.v1'
INDEX_SCHEMA = 'nero.disclosure.knowledge-packages-index.v1'
SOFTWARE_CONTRACT = 'nero.disclosure.knowledge-loader.v1'
CAPABILITIES = {
    'read': ('backend/library.py', 'backend/announcement_history.py'),
    'search': ('backend/public_library_index.py', 'backend/announcement_index.py'),
    'edit': ('backend/library_admin.py', 'backend/library_write.py'),
    'import': ('backend/file_ingestion.py',),
    'validate': ('scripts/verify_board_libraries.py',),
    'rebuild_index': ('scripts/sync_sqlite_library.py', 'scripts/sync_announcement_history_index.py'),
    'templates': ('backend/template_authoring.py',),
    'word': ('scripts/agent_word.py', 'scripts/word_renderer.py'),
    'pdf': ('backend/document_extract.py',),
}


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def contained(base, relative):
    # Package members always belong to the selected knowledge root, not to any
    # neighbouring local state or another package root.
    relative = paths._normalized(relative)
    target = Path(base) / relative
    for p in (target, *target.parents):
        if p == Path(base).parent:
            break
        if p.is_symlink():
            raise ValueError('知识包不接纳外部链接：' + relative)
    if not target.resolve().is_relative_to(Path(base).resolve()):
        raise ValueError('知识包路径越界')
    return target


def load(base, app=None, *, full=False):
    """Check identities/dependencies on load; full=True also compares every byte.

    Existing update/import operations keep their original atomic commit contract.
    Content hashes describe the last package snapshot; refresh them before moving
    an edited package. Normal startup checks compatibility, not snapshot freshness.
    """
    base = Path(base).resolve()
    app = Path(app or paths.app_of(base)).resolve()
    index_path = base / 'packages/index.json'
    if not index_path.is_file():
        if base.name == paths.KNOWLEDGE_DIR:
            raise ValueError('知识包清单缺失，请运行 refresh_knowledge_packages.py')
        return {'mode': 'legacy-root', 'packages': [], 'files_checked': 0}
    index = json.loads(index_path.read_text('utf-8'))
    if index.get('schema') != INDEX_SCHEMA:
        raise ValueError('知识包索引结构版本不兼容')
    packages = {}
    for entry in index['packages']:
        identity = entry['id']
        if identity in packages:
            raise ValueError('知识包身份重复')
        manifest = contained(base / 'packages', entry['file'])
        if digest(manifest) != entry['sha256']:
            raise ValueError('知识包清单哈希不一致：' + identity)
        package = json.loads(manifest.read_text('utf-8'))
        if package.get('schema') != SCHEMA or package.get('id') != identity or not package.get('version'):
            raise ValueError('知识包身份或版本无效：' + identity)
        if package.get('software_contract') != SOFTWARE_CONTRACT:
            raise ValueError('知识包需要不同的软件加载合同')
        for capability in package['requires_software']:
            required = CAPABILITIES.get(capability)
            if not required or any(not contained(app, p).is_file() for p in required):
                raise ValueError('软件能力缺失：' + capability)
        if package['board'] != 'chinext':
            raise ValueError('当前软件仅开放创业板知识包')
        packages[identity] = package
    checked = 0
    for identity, package in packages.items():
        for dependency in package['depends_on']:
            if dependency not in packages:
                raise ValueError('知识包缺少依赖：' + dependency)
        seen = set()
        for row in package['files']:
            relative = row['path']
            if relative in seen or relative.split('/')[0] not in ('data', 'templates'):
                raise ValueError('知识包路径重复或包含本机资料')
            seen.add(relative)
            path = contained(base, relative)
            if full:
                if not path.is_file() or path.stat().st_size != row['bytes'] or digest(path) != row['sha256']:
                    raise ValueError('知识包文件与快照不符：' + relative)
                checked += 1
        for relative in package['required_files']:
            if not contained(base, relative).is_file():
                raise ValueError('知识包必要文件缺失：' + relative)
    return {'mode': 'full_hashes' if full else 'compatibility',
            'packages': [{'id': p['id'], 'version': p['version'], 'depends_on': p['depends_on']}
                         for p in packages.values()],
            'files_checked': checked}
