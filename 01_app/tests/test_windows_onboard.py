import importlib.util
import json
from pathlib import Path
import tomllib
from types import SimpleNamespace
import pytest

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('windows_onboard',ROOT/'scripts/windows_onboard.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)


def test_non_windows_cannot_be_reported_as_windows_accepted(tmp_path):
    report=module.diagnose(tmp_path,windows=False)
    assert report['status']=='failed' and not report['windows_execution_verified']
    assert '此运行入口仅支持Windows x64' in report['issues']


def test_windows_lock_covers_existing_pins_and_native_dependencies():
    old=module.required_versions(ROOT/'requirements.lock.txt')
    windows=module.required_versions(ROOT/'runtime/windows-x64/requirements.windows.lock.txt')
    native=module.required_versions(ROOT/'native/macos/requirements.lock.txt')
    assert old.items()<=windows.items()
    assert {'pywin32','colorama','greenlet'}<=windows.keys()
    assert native['openpyxl']=='3.1.5' and native['et-xmlfile']=='2.0.0'
    assert windows['openpyxl']=='3.1.5' and windows['et-xmlfile']=='2.0.0'


def test_windows_utf8_bootstrap_reexecs_once_with_same_script_and_args(monkeypatch):
    monkeypatch.setattr(module.sys,'platform','win32');monkeypatch.setattr(module.sys,'flags',SimpleNamespace(utf8_mode=False))
    monkeypatch.setattr(module.sys,'executable','python.exe');monkeypatch.setattr(module.sys,'argv',['windows_onboard.py','--doctor'])
    calls=[];monkeypatch.setattr(module.os,'execve',lambda *args:calls.append(args))
    assert module.ensure_utf8(['--doctor'])
    assert calls and calls[0][0]=='python.exe' and calls[0][1][1]=='-X' and calls[0][1][-1]=='--doctor'
    assert calls[0][2]['PYTHONUTF8']=='1' and calls[0][2]['NERO_WINDOWS_UTF8_REEXEC']=='1'


def test_windows_utf8_bootstrap_does_not_loop_or_reexec_when_already_enabled(monkeypatch):
    monkeypatch.setattr(module.sys,'platform','win32');monkeypatch.setattr(module.sys,'flags',SimpleNamespace(utf8_mode=True))
    monkeypatch.setattr(module.os,'execve',lambda *args:pytest.fail('UTF-8 already enabled'))
    assert module.ensure_utf8(['--doctor']) is False
    monkeypatch.setattr(module.sys,'flags',SimpleNamespace(utf8_mode=False));monkeypatch.setenv('NERO_WINDOWS_UTF8_REEXEC','1')
    with pytest.raises(RuntimeError,match='重执行未生效'):module.ensure_utf8(['--doctor'])
