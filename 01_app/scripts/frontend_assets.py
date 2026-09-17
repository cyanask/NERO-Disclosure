"""Plan, archive and activate local frontend bundles with verified rollback copies."""
import argparse
from contextlib import contextmanager
import hashlib
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import shutil
from urllib.parse import unquote, urlsplit


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def safe_file(root, relative):
    root = Path(root).resolve()
    relative = Path(relative)
    if relative.is_absolute() or '..' in relative.parts:
        raise ValueError('资源路径越界')
    path = root / relative
    if any(p.is_symlink() for p in (path, *path.parents) if p != root.parent):
        raise ValueError('资源目录不接纳符号链接')
    if not path.resolve().is_relative_to(root):
        raise ValueError('资源路径越界')
    return path


class HTMLReferences(HTMLParser):
    def __init__(self):
        super().__init__(); self.references = []

    def handle_starttag(self, tag, attrs):
        self.references.extend(value for key, value in attrs if key in ('src', 'href') and value)


def references(root, index_text=None):
    """Follow local HTML, JS chunks and CSS resources; retain more on ambiguity."""
    root = Path(root).resolve()
    parser = HTMLReferences()
    parser.feed(index_text if index_text is not None else safe_file(root, 'index.html').read_text())
    pending = [('index.html', value) for value in parser.references]
    retained = set()
    while pending:
        origin, value = pending.pop()
        url = urlsplit(value)
        if url.scheme or url.netloc or not url.path or value.startswith('#'):
            continue
        raw = unquote(url.path)
        target = root / raw.lstrip('/') if raw.startswith('/') else root / Path(origin).parent / raw
        if not target.resolve().is_relative_to(root):
            raise ValueError('资源引用越界')
        relative = target.resolve().relative_to(root).as_posix()
        path = safe_file(root, relative)
        if not path.is_file():
            raise ValueError('资源引用缺失：' + relative)
        if relative in retained:
            continue
        retained.add(relative)
        if path.suffix not in ('.js', '.css'):
            continue
        text = path.read_text()
        quoted = re.findall(r'''["']([^"'\s]+\.(?:js|css|png|jpe?g|gif|ico|avif|svg|webp|woff2?|ttf|otf|wasm|json)(?:\?[^"'\s]*)?)["']''', text)
        urls = re.findall(r'url\(\s*["\']?([^\s)"\']+)', text) if path.suffix == '.css' else []
        for item in quoted + urls:
            if '${' in item or item.startswith(('data:', 'http:', 'https:')):
                continue
            if item.startswith('assets/'):
                pending.append(('index.html', '/' + item)); continue
            # Plain JS strings may describe file types rather than load assets.
            public_file = item.startswith('/') and (root / item.lstrip('/')).is_file()
            sibling_file = (root / Path(relative).parent / urlsplit(item).path).is_file()
            if item in urls or public_file or sibling_file or item.startswith(('./', '../', '/assets/')):
                pending.append((relative, item))
    return retained


def inventory(root):
    rows = []
    for path in sorted(Path(root).rglob('*')):
        if path.name == '.frontend-maintenance.lock':
            continue
        if path.is_symlink():
            raise ValueError('资源目录不接纳符号链接')
        if path.is_file():
            rows.append({'path': path.relative_to(root).as_posix(), 'bytes': path.stat().st_size, 'sha256': digest(path)})
    return rows


def write_json(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    os.replace(temporary, path)


@contextmanager
def locked(root):
    path = Path(root) / '.frontend-maintenance.lock'
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        os.write(fd, str(os.getpid()).encode()); os.close(fd)
        yield
    finally:
        path.unlink()


def snapshot(root, destination):
    rows = inventory(root)
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=False)
    for row in rows:
        source = safe_file(root, row['path']); target = safe_file(destination, row['path'])
        target.parent.mkdir(parents=True, exist_ok=True); shutil.copy2(source, target)
        if digest(target) != row['sha256'] or digest(source) != row['sha256']:
            raise ValueError('备份期间资源发生变化')
    write_json(destination.parent / 'bundle-manifest.json', rows)
    return rows


def plan(root, previous_index=None):
    root = Path(root).resolve()
    retained = references(root)
    previous = None
    if previous_index:
        previous_index = Path(previous_index).resolve()
        retained |= references(root, previous_index.read_text())
        previous = {'path': str(previous_index), 'sha256': digest(previous_index)}
    unused = [r for r in inventory(root) if r['path'].startswith('assets/') and r['path'] not in retained]
    return {'root': str(root), 'index_sha256': digest(root / 'index.html'), 'previous_index': previous,
            'retained': sorted(retained), 'unused': unused, 'bytes': sum(r['bytes'] for r in unused)}


def archive_unused(planned, archive):
    root = Path(planned['root']); archive = Path(archive).resolve()
    if archive.is_relative_to(root.resolve()):
        raise ValueError('归档目录必须位于服务目录之外')
    with locked(root):
        if digest(root / 'index.html') != planned['index_sha256']:
            raise ValueError('页面入口已变化，请重新生成清单')
        previous = planned.get('previous_index')
        if previous and digest(previous['path']) != previous['sha256']:
            raise ValueError('上一版入口已变化')
        fresh = plan(root, previous['path'] if previous else None)
        if fresh != planned:
            raise ValueError('资源已变化，请重新生成清单')
        snapshot(root, archive / 'bundle-before')
        if previous:
            prior = archive / 'previous-bundle'; prior.mkdir()
            prior_text = Path(previous['path']).read_text()
            paths = references(root, prior_text) | {r['path'] for r in inventory(root) if not r['path'].startswith('assets/') and r['path'] != 'index.html'}
            for relative in sorted(paths):
                source, target = safe_file(root, relative), safe_file(prior, relative)
                target.parent.mkdir(parents=True, exist_ok=True); shutil.copy2(source, target)
                if digest(source) != digest(target):
                    raise ValueError('上一版资源备份校验失败')
            (prior / 'index.html').write_text(prior_text)
            references(prior)
            write_json(archive / 'previous-manifest.json', inventory(prior))
        moved = []
        try:
            for row in planned['unused']:
                if digest(root / 'index.html') != planned['index_sha256']:
                    raise ValueError('归档期间入口已变化')
                source = safe_file(root, row['path'])
                if digest(source) != row['sha256']:
                    raise ValueError('归档期间文件已变化')
                target = safe_file(archive / 'unused', row['path'])
                target.parent.mkdir(parents=True, exist_ok=True)
                os.replace(source, target); moved.append(row)
                if digest(target) != row['sha256']:
                    raise ValueError('移动期间资源发生变化')
            if digest(root / 'index.html') != planned['index_sha256']:
                raise ValueError('归档期间入口已变化')
            references(root)
        except Exception:
            for row in moved:
                source = safe_file(archive / 'unused', row['path']); target = safe_file(root, row['path'])
                if not target.exists():
                    target.parent.mkdir(parents=True, exist_ok=True); os.replace(source, target)
            raise
        receipt = {**planned, 'archive': str(archive), 'status': 'archived', 'moved': moved,
                   'previous_bundle': str(archive / 'previous-bundle') if previous else None}
        write_json(archive / 'receipt.json', receipt)
        return receipt


def activate(candidate, root, archive):
    candidate, root, archive = map(lambda p: Path(p).resolve(), (candidate, root, archive))
    if candidate.is_relative_to(root) or root.is_relative_to(candidate) or archive.is_relative_to(root) or archive.is_relative_to(candidate):
        raise ValueError('构建与归档目录必须独立于服务目录')
    references(candidate)
    with locked(root):
        before = digest(root / 'index.html')
        snapshot(root, archive / 'bundle-before')
        candidate_rows = inventory(candidate)
        for row in candidate_rows:
            if row['path'] == 'index.html':
                continue
            source, target = safe_file(candidate, row['path']), safe_file(root, row['path'])
            if target.exists() and row['path'].startswith('assets/') and digest(target) != row['sha256']:
                raise ValueError('同名哈希资源内容不同，拒绝覆盖')
            target.parent.mkdir(parents=True, exist_ok=True)
            temp = target.with_name(target.name + '.staging'); shutil.copy2(source, temp)
            if digest(temp) != row['sha256']:
                raise ValueError('复制校验失败')
            os.replace(temp, target)
        if digest(root / 'index.html') != before:
            raise ValueError('页面入口被其他任务更新，停止切换')
        temp = root / 'index.html.staging'; shutil.copy2(candidate / 'index.html', temp)
        expected = next(row['sha256'] for row in candidate_rows if row['path'] == 'index.html')
        if digest(temp) != expected:
            raise ValueError('候选入口在切换前发生变化')
        os.replace(temp, root / 'index.html')
        receipt = {'status': 'activated', 'root': str(root), 'candidate': str(candidate),
                   'before': before, 'after': digest(root / 'index.html'), 'files': candidate_rows,
                   'rollback': str(archive / 'bundle-before')}
        write_json(archive / 'receipt.json', receipt)
        return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    p = sub.add_parser('plan'); p.add_argument('--dist', type=Path, required=True); p.add_argument('--previous-index', type=Path); p.add_argument('--output', type=Path, required=True)
    p = sub.add_parser('archive'); p.add_argument('--plan', type=Path, required=True); p.add_argument('--archive-dir', type=Path, required=True)
    p = sub.add_parser('activate'); p.add_argument('--candidate', type=Path, required=True); p.add_argument('--dist', type=Path, required=True); p.add_argument('--archive-dir', type=Path, required=True)
    args = parser.parse_args()
    if args.action == 'plan':
        value = plan(args.dist, args.previous_index); write_json(args.output, value)
        print(json.dumps({'unused': len(value['unused']), 'bytes': value['bytes'], 'plan': str(args.output)}))
    elif args.action == 'archive':
        value = archive_unused(json.loads(args.plan.read_text()), args.archive_dir)
        print(json.dumps({'archived': len(value['moved']), 'bytes': value['bytes'], 'archive': str(args.archive_dir)}))
    else:
        value = activate(args.candidate, args.dist, args.archive_dir)
        print(json.dumps({'status': value['status'], 'rollback': value['rollback']}))


if __name__ == '__main__':
    main()
