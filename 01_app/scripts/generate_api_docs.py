"""Generate HTTP API reference from route declarations without starting the app."""
import argparse
import ast
from pathlib import Path

APP = Path(__file__).resolve().parents[1]
OUTPUT = APP.parent / 'DEVELOPMENT.md'
START = '<!-- API-REFERENCE:START -->'
END = '<!-- API-REFERENCE:END -->'
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
        f'共 {len(rows)} 个 HTTP 方法与路径声明。', '',
        '| 方法 | 路径 | 实现与行号 | 处理函数 |', '| --- | --- | --- | --- |',
    ]
    for filename, line, method, route, function in sorted(rows):
        lines.append(f'| {method} | `{route}` | [{filename}:{line}](01_app/backend/{filename}#L{line}) | `{function}` |')
    return '\n'.join(lines) + '\n'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    original = OUTPUT.read_text('utf-8')
    if original.count(START) != 1 or original.count(END) != 1 or original.index(START) >= original.index(END):
        raise SystemExit('开发文档的接口区域标记缺失或重复，未改写文件')
    before, rest = original.split(START)
    _, after = rest.split(END)
    content = before + START + '\n' + render() + END + after
    if args.check:
        if original != content:
            raise SystemExit('接口文档与源码不一致，请运行 scripts/generate_api_docs.py')
        print('接口索引与源码一致')
    else:
        OUTPUT.write_text(content, encoding='utf-8')
        print(OUTPUT.name)


if __name__ == '__main__':
    main()
