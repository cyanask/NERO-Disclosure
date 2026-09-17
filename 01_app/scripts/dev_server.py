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
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend import paths as workspace_paths

FIXTURES = ROOT / 'tests/fixtures/knowledge'
MARKER = '.dev-fixtures.json'
NOTICE = ('开发样例模式：法规、案例、公告与公司均为虚构样例，'
          '不得用于业务判断、对外交付或披露文件编制。')


def prepare_knowledge(workspace, knowledge):
    """把虚构样例放到同级知识根；不覆盖没有样例标记的既有目录。"""
    if not FIXTURES.is_dir():
        raise SystemExit('缺少虚构样例目录：' + str(FIXTURES))
    if knowledge.exists() and not (knowledge / MARKER).is_file():
        raise SystemExit('检测到既有知识目录且没有样例标记，开发入口不会覆盖：' + str(knowledge))
    shutil.copytree(FIXTURES, knowledge, dirs_exist_ok=True)
    (knowledge / MARKER).write_text(json.dumps({
        'schema': 'nero.disclosure.dev-fixtures.v1',
        'source': '01_app/tests/fixtures/knowledge',
        'warning': NOTICE,
    }, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
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
    knowledge = prepare_knowledge(workspace, workspace / '02_knowledge')
    directory = (args.data_dir or workspace / '03_local/dev/var').resolve()
    directory.mkdir(parents=True, exist_ok=True)
    dist = args.web_root.resolve()
    if not (dist / 'index.html').is_file():
        raise SystemExit('尚无Web静态资源。请先在 01_app/frontend 执行 npm ci 和 npm run build。')

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
