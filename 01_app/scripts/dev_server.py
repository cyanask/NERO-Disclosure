"""开发服务器：用仓库自带的虚构样例启动本机工作台。

与正式运行的区别只有资料边界：本入口把 `tests/fixtures/knowledge` 复制成
工作区同级的 `02_knowledge`（该目录不进版本库），把本机数据写到
`03_local/dev/var`。它不读取作者的正式知识库或历史业务数据，也不加载
知识包清单；缺少样例标记的既有 `02_knowledge` 会被拒绝覆盖。

正式运行仍使用 `scripts/run.py` 与经授权的知识包。
"""
import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend import paths as workspace_paths

FIXTURES = ROOT / 'tests/fixtures/knowledge'
MARKER = '.dev-fixtures.json'
NOTICE = ('开发样例模式：法规、案例、公告与公司均为虚构样例，'
          '不得用于业务判断、对外交付或披露文件编制。')


def prepare_knowledge(workspace, knowledge):
    """首次初始化虚构样例；再次启动保留开发者的所有修改。"""
    workspace = Path(workspace).resolve()
    knowledge = Path(knowledge).absolute()
    if knowledge != workspace / '02_knowledge' or knowledge.is_symlink():
        raise SystemExit('开发知识目录须为工作区同级普通目录')
    if not FIXTURES.is_dir():
        raise SystemExit('缺少虚构样例目录：' + str(FIXTURES))
    if knowledge.exists():
        marker = knowledge / MARKER
        try:
            if marker.is_symlink():
                raise ValueError('样例标记不能是链接')
            value = json.loads(marker.read_text('utf-8'))
            if not isinstance(value, dict) or value.get('schema') != 'nero.disclosure.dev-fixtures.v1':
                raise ValueError('样例标记无效')
        except (OSError, ValueError):
            raise SystemExit('既有知识目录没有有效样例标记，未覆盖：' + str(knowledge)) from None
        if any(path.is_symlink() for path in knowledge.rglob('*')):
            raise SystemExit('开发知识目录包含链接，未启动服务')
        return knowledge
    if FIXTURES.is_symlink() or any(path.is_symlink() for path in FIXTURES.rglob('*')):
        raise SystemExit('样例来源包含链接，未复制')
    # 完整复制后再发布目录；失败只清理本次创建的暂存目录。
    with tempfile.TemporaryDirectory(prefix='.dev-seed-', dir=workspace) as temporary:
        staging = Path(temporary) / 'knowledge'
        shutil.copytree(FIXTURES, staging)
        (staging / MARKER).write_text(json.dumps({
            'schema': 'nero.disclosure.dev-fixtures.v1',
            'source': '01_app/tests/fixtures/knowledge',
            'warning': NOTICE,
        }, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        # 仅开发入口生成虚构公司，免联网即可进入各功能页；不伪造公司核实回执。
        company = staging / 'data/client_announcements/chinext/000000/catalog.json'
        company.parent.mkdir(parents=True, exist_ok=True)
        company.write_text(json.dumps({
            'board': 'chinext', 'stock_code': '000000',
            'company_name': '虚构审查公司（仅开发）', 'items': [], 'revision': 0,
            'coverage': {'from': None, 'through': None, 'complete': False, 'note': NOTICE},
        }, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        if knowledge.exists() or knowledge.is_symlink():
            raise SystemExit('知识目录已由其他进程创建，未覆盖')
        staging.rename(knowledge)
    return knowledge


def main():
    parser = argparse.ArgumentParser(description='使用虚构样例启动本机开发服务器')
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--data-dir', type=Path, default=None)
    parser.add_argument('--web-root', type=Path, default=ROOT / 'frontend/dist')
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error('端口应在1024至65535之间')

    workspace = ROOT.parent
    dist = args.web_root.resolve()
    if not (dist / 'index.html').is_file():
        raise SystemExit('尚无Web静态资源。请先在 01_app/frontend 执行 npm ci 和 npm run build。')
    # 在资料写入前验证三类根，不能将资料复制到链接指向的正式工作区。
    workspace_paths.local_of(ROOT)
    knowledge = prepare_knowledge(workspace, workspace / '02_knowledge')
    directory = (args.data_dir or workspace / '03_local/dev/var').resolve()
    directory.mkdir(parents=True, exist_ok=True)

    from backend.app import create_app
    from fastapi.staticfiles import StaticFiles
    import uvicorn

    app = create_app(data_dir=directory, seed_root=knowledge)
    app.mount('/', StaticFiles(directory=dist, html=True), name='workbench')
    print('本机开发入口 http://127.0.0.1:%d ，按 Ctrl+C 停止。' % args.port)
    print('知识根：%s（虚构样例）' % knowledge)
    print('本机数据：%s' % directory)
    print(NOTICE)
    uvicorn.run(app, host='127.0.0.1', port=args.port, log_level='warning', access_log=False)


if __name__ == '__main__':
    main()
