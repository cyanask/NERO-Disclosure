"""Generate HTTP API reference from route declarations without starting the app."""
import argparse
import ast
from pathlib import Path

APP = Path(__file__).resolve().parents[1]
OUTPUT = APP / 'docs/API.md'
METHODS = {'get', 'post', 'put', 'patch', 'delete', 'head', 'options'}


def render():
    rows = []
    for source in sorted((APP / 'backend').glob('*.py')):
        for node in ast.walk(ast.parse(source.read_text('utf-8'))):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for decorator in node.decorator_list:
                if (isinstance(decorator, ast.Call) and isinstance(decorator.func, ast.Attribute)
                        and decorator.func.attr in METHODS and decorator.args):
                    route = decorator.args[0]
                    if isinstance(route, ast.Constant) and isinstance(route.value, str):
                        rows.append((source.name, node.lineno, decorator.func.attr.upper(), route.value, node.name))
    lines = [
        '# HTTP API', '',
        '从后端路由声明生成。权限和状态条件见处理函数；'
        '表中包含返回 410 的退役接口及条件挂载接口。'
        '应用入口为 `backend/app.py:create_app`。', '',
        '更新文档：`python3 01_app/scripts/generate_api_docs.py`；'
        '检查同步：在命令后添加 `--check`。', '',
        'Pi 进程内操作见 `backend/workflow_operations.py`，'
        '模型工具按 `backend/pi_runtime.py:PiRuntime.tools` 的阶段规则开放。', '',
        f'共 {len(rows)} 个 HTTP 方法与路径声明。', '',
        '| 方法 | 路径 | 实现与行号 | 处理函数 |', '| --- | --- | --- | --- |',
    ]
    for filename, line, method, route, function in sorted(rows):
        lines.append(f'| {method} | `{route}` | [{filename}:{line}](../backend/{filename}#L{line}) | `{function}` |')
    return '\n'.join(lines) + '\n'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    content = render()
    if args.check:
        if not OUTPUT.is_file() or OUTPUT.read_text('utf-8') != content:
            raise SystemExit('接口文档与源码不一致，请运行 scripts/generate_api_docs.py')
        print('接口索引与源码一致')
    else:
        OUTPUT.parent.mkdir(parents=True, exist_ok=True)
        OUTPUT.write_text(content, encoding='utf-8')
        print(OUTPUT.relative_to(APP))


if __name__ == '__main__':
    main()
