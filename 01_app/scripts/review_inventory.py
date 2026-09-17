"""Generate a static HTTP-route index for reviewers; no app/data initialization."""
import argparse
import ast
from pathlib import Path

APP = Path(__file__).resolve().parents[1]
OUTPUT = APP / 'docs/review/API_INVENTORY.md'
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
        '# HTTP 接口声明索引', '',
        '由 `python 01_app/scripts/review_inventory.py` 从后端 AST 生成；'
        '用 `--check` 检查是否与源码同步。此表是静态声明索引，'
        '包括返回 410 的退役接口及条件挂载接口，不代表所有接口在所有运行模式中可用。'
        '实际挂载入口为 `backend/app.py:create_app`，权限和状态条件见各处理函数。', '',
        'Pi 的进程内工作流操作还须审阅 `backend/workflow_operations.py` 与 '
        '`backend/app.py:workflow_operation`；模型工具按意图与阶段动态授予，'
        '入口见审阅指南，不以 HTTP 声明数量代替功能覆盖率。', '',
        f'共 {len(rows)} 个 HTTP 方法与路径声明。', '',
        '| 方法 | 路径 | 实现与行号 | 处理函数 |', '| --- | --- | --- | --- |',
    ]
    for filename, line, method, route, function in sorted(rows):
        lines.append(f'| {method} | `{route}` | [{filename}:{line}](../../backend/{filename}#L{line}) | `{function}` |')
    return '\n'.join(lines) + '\n'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    content = render()
    if args.check:
        if not OUTPUT.is_file() or OUTPUT.read_text('utf-8') != content:
            raise SystemExit('接口索引与源码不一致，请运行 scripts/review_inventory.py')
        print('接口索引与源码一致')
    else:
        OUTPUT.parent.mkdir(parents=True, exist_ok=True)
        OUTPUT.write_text(content, encoding='utf-8')
        print(OUTPUT.relative_to(APP))


if __name__ == '__main__':
    main()
