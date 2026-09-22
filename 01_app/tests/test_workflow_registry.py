"""Static workflow-operation registry contract checks."""
import ast
from pathlib import Path

from backend import workflow_operations


APP_SOURCE = Path(__file__).resolve().parents[1] / 'backend' / 'app.py'


def handler_keys(source_path=APP_SOURCE):
    tree = ast.parse(Path(source_path).read_text(encoding='utf-8'))
    workflow = next((node for node in ast.walk(tree)
                     if isinstance(node, ast.FunctionDef) and node.name == 'workflow_operation'), None)
    assert workflow is not None, 'workflow_operation 函数不存在'
    assignments = [node for node in workflow.body
                   if isinstance(node, ast.Assign)
                   and any(isinstance(target, ast.Name) and target.id == 'handlers' for target in node.targets)]
    assert len(assignments) == 1, 'workflow_operation.handlers 必须只有一个静态赋值'
    value = assignments[0].value
    assert isinstance(value, ast.Dict), 'workflow_operation.handlers 必须是字典字面量'
    keys = []
    for key in value.keys:
        assert isinstance(key, ast.Constant) and isinstance(key.value, str), \
            'workflow_operation.handlers 的键必须全部是静态字符串'
        keys.append(key.value)
    assert len(keys) == len(set(keys)), 'workflow_operation.handlers 存在重复键'
    return set(keys)


def assert_registry_matches(models, handlers):
    expected = set(models)
    actual = set(handlers)
    assert actual == expected, f'workflow operation registry mismatch: missing={expected - actual}, extra={actual - expected}'


def test_workflow_models_and_app_handlers_are_exactly_registered():
    assert_registry_matches(workflow_operations.MODELS, handler_keys())
