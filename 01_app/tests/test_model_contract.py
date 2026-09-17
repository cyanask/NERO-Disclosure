"""Shared model defaults preserve explicit saved values and ship with the software."""
from pathlib import Path
from backend.model_settings import ModelSettings
from scripts import build_macos_release


def test_missing_fields_use_pi_defaults_without_rewriting_explicit_values():
    row={'key':'example','provider':'custom','id':'example','label':'Example','api':'openai-completions','baseUrl':'https://example.invalid/v1','auth_type':'api_key'}
    assert ModelSettings.normalize(row)['maxTokens']==16384
    assert ModelSettings.normalize(row)['contextWindow']==128000
    explicit={**row,'contextWindow':1000000,'maxTokens':8192}
    normalized=ModelSettings.normalize(explicit)
    assert normalized['maxTokens']==8192 and normalized['contextWindow']==1000000
    assert 'maxTokens' not in row


def test_source_packaging_retains_shared_contract(tmp_path,monkeypatch):
    # Copy a minimal source fixture; this never builds or installs an App.
    source=tmp_path/'source';(source/'config').mkdir(parents=True)
    contract=Path(__file__).resolve().parents[1]/'config/model-contract.json'
    (source/'config/model-contract.json').write_bytes(contract.read_bytes())
    monkeypatch.setattr(build_macos_release,'APP',source)
    target=tmp_path/'payload';target.mkdir()
    receipt=build_macos_release.copy_source(target)
    assert (target/'config/model-contract.json').read_bytes()==contract.read_bytes()
    assert any(item['path']=='config/model-contract.json' for item in receipt)
