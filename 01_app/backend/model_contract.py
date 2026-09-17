"""Shared model configuration defaults and serialization vocabulary."""
import json
from pathlib import Path
from functools import lru_cache

CONTRACT=json.loads((Path(__file__).resolve().parents[1]/'config/model-contract.json').read_text())
DEFAULTS=CONTRACT['defaults']
APIS={item['id'] for item in CONTRACT['apis']}
LEVELS=CONTRACT['thinkingLevels']
ENV_FIELDS={provider:tuple(fields) for provider,fields in CONTRACT['credentialFields'].items()}

@lru_cache(maxsize=1)
def native_providers():
    from .model_control import command
    return {row['id']:row for row in command(Path(__file__).resolve().parents[1],{'operation':'catalog'})['providers']}

def supports_oauth(provider):
    return 'oauth' in native_providers().get(provider,{}).get('auth_types',[])
