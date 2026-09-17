"""三类工作根的统一定位与历史路径解析。

01_app 软件、02_knowledge 知识、03_local 本机资料；旧式单根目录（软件、
知识、本机资料同处一个目录）继续可用。命名为三类根的目录使用固定的同级
位置；本机根尚不存在时也不会把业务状态写入软件目录。旧式独立根就地解析。

历史记录（事项、回执、治理清单、索引投影）保存的是“相对统一根”的路径串，
例如 ``var/disclosure.sqlite3`` 或 ``data/public/originals/<sha>.pdf``。
``base_for`` 按登记前缀把这些串解析到对应根，迁移后仍然可读可写。
"""
import os
from pathlib import Path, PureWindowsPath

APP_DIR = '01_app'
KNOWLEDGE_DIR = '02_knowledge'
LOCAL_DIR = '03_local'
KNOWLEDGE_PREFIXES = {'data', 'templates'}
LOCAL_PREFIXES = {'work', 'var', 'output', 'design-output', 'cache', 'records'}


def app_root(start=None):
    """软件根：包含 backend/ 与 scripts/ 的目录。"""
    return Path(start).resolve() if start is not None else Path(__file__).resolve().parents[1]


def _root(root, category):
    requested=Path(root).absolute()
    if requested.name in (APP_DIR,KNOWLEDGE_DIR,LOCAL_DIR) and requested.is_symlink():
        raise ValueError('三类根目录不能是符号链接')
    root = requested.resolve()
    # Installed macOS software is read-only inside .app. Only this process's
    # actual app root and explicitly selected data roots use the packaged map;
    # arbitrary roots (including isolated tests) keep their existing ownership.
    home = os.environ.get('NERO_DISCLOSURE_HOME')
    if home:
        home_path = Path(home).expanduser()
        if not home_path.is_absolute() or home_path.is_symlink():
            raise ValueError('安装版数据目录须为绝对路径且不能是符号链接')
        home_path = home_path.resolve()
        installed_app = app_root()
        mapping = {APP_DIR: installed_app, KNOWLEDGE_DIR: home_path / KNOWLEDGE_DIR,
                   LOCAL_DIR: home_path / LOCAL_DIR}
        if root in mapping.values():
            candidate = mapping[category]
            if candidate.is_symlink():raise ValueError('三类根目录不能是符号链接')
            return candidate
    # Only the declared three-directory layout shares sibling roots. A legacy or
    # isolated arbitrary root never discovers another project's data or methods.
    if root.name in (APP_DIR, KNOWLEDGE_DIR, LOCAL_DIR):
        candidate=root.parent/category
        if candidate.is_symlink():raise ValueError('三类根目录不能是符号链接')
        return candidate
    return root


def knowledge_root(app=None):
    """知识根：三类布局的固定同级位置；旧式单根就地解析。"""
    app = Path(app).resolve() if app is not None else app_root()
    return knowledge_of(app)


def local_root(app=None):
    """本机根：三类布局的固定同级位置，首次运行可以创建它。"""
    app = Path(app).resolve() if app is not None else app_root()
    return local_of(app)


def knowledge_of(root):
    """由软件根或本机根解析知识根；已是知识根或旧式单根时返回自身。"""
    return _root(root, KNOWLEDGE_DIR)


def local_of(root):
    """由软件根或知识根解析本机根；已是本机根或旧式单根时返回自身。"""
    return _root(root, LOCAL_DIR)


def app_of(root):
    """由知识根或本机根解析软件根；已是软件根或旧式单根时返回自身。"""
    return _root(root, APP_DIR)


def _normalized(relative):
    text = str(relative).replace('\\', '/')
    path = Path(text)
    if not text or path.is_absolute() or PureWindowsPath(text).drive or '..' in path.parts or '\x00' in text:
        raise ValueError('登记路径须为范围内的相对路径')
    return path.as_posix()


def base_for(root, relative):
    """按登记前缀选择根：data/templates→知识根，work/var/output/…→本机根，其余→软件根。"""
    text = _normalized(relative)
    prefix = text.split('/')[0]
    if prefix in KNOWLEDGE_PREFIXES:
        return knowledge_of(root)
    if prefix in LOCAL_PREFIXES:
        return local_of(root)
    return app_of(root)


def resolve(root, relative):
    """把登记的相对路径解析为绝对路径；读取与写入都从这里出发。"""
    base = base_for(root, relative)
    target = base / _normalized(relative)
    if base.is_symlink() or not target.resolve().is_relative_to(base.resolve()):
        raise ValueError('登记路径超出所属目录')
    return target


def store_path(root, path):
    """把绝对路径登记为兼容旧记录的相对路径串（知识根、本机根优先）。"""
    path = Path(path).resolve()
    for base in (knowledge_of(root), local_of(root), app_of(root)):
        try:
            return path.relative_to(base).as_posix()
        except ValueError:
            continue
    raise ValueError('文件不属于当前工作区')


def credential_scope(directory):
    """Keep this workspace's existing vault namespace across the var move.

    No secrets or namespace pointers are copied. A different workspace location
    computes a different scope and still requires separate authorization.
    """
    directory = Path(directory).resolve()
    if directory.name == 'var' and directory.parent.name == LOCAL_DIR:
        return directory.parent.parent / 'var'
    return directory


def data(root):
    return knowledge_of(root) / 'data'


def templates(root):
    return knowledge_of(root) / 'templates'


def var(root):
    return local_of(root) / 'var'


def work(root):
    return local_of(root) / 'work'


def repository_root(app=None):
    """最近的上层 Git 仓库（版本记录读取提交用）；找不到时返回软件根。"""
    current = Path(app).resolve() if app is not None else app_root()
    for candidate in (current, *current.parents):
        if (candidate / '.git').exists():
            return candidate
    return current


def roots(app=None):
    """三类根快照，供入口、健康检查与治理输出使用。"""
    app = Path(app).resolve() if app is not None else app_root()
    knowledge = knowledge_root(app)
    local = local_root(app)
    return {'app': app, 'knowledge': knowledge, 'local': local,
            'layout': 'single-root' if knowledge == app and local == app else 'three-root'}
