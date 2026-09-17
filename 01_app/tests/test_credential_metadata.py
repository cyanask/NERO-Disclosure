"""Credential status uses attributes, never secret blobs or interactive access."""
import json
from backend.model_credentials import ModelCredentialVault,credential_metadata,decode_metadata


def test_metadata_contains_only_type_and_field_names():
    value={'type':'api_key','key':'SECRET','env':{'CLOUDFLARE_ACCOUNT_ID':'PRIVATE-ID'},'refresh':'PRIVATE-REFRESH'}
    metadata=credential_metadata(value)
    assert metadata=={'schema':1,'type':'api_key','env_keys':['CLOUDFLARE_ACCOUNT_ID']}
    assert not any(secret in json.dumps(metadata) for secret in ('SECRET','PRIVATE-ID','PRIVATE-REFRESH'))
    assert decode_metadata(json.dumps(metadata))=={'type':'api_key','env_keys':['CLOUDFLARE_ACCOUNT_ID']}


def test_old_records_and_revocation_metadata():
    assert decode_metadata(None)=={'type':'stored','env_keys':None}
    assert decode_metadata('unstructured existing comment')=={'type':'stored','env_keys':None}
    assert decode_metadata(json.dumps(credential_metadata({'type':'revoked'})))['type']=='revoked'


def test_status_never_dispatches_to_secret_read(tmp_path):
    vault=ModelCredentialVault(tmp_path);operations=[]
    def operation(action,account,raw=None):
        operations.append(action);assert action=='status';assert raw is None
        return {'type':'stored','env_keys':None}
    vault._operation=operation
    assert vault.status('provider:example')['type']=='stored'
    assert operations==['status']
