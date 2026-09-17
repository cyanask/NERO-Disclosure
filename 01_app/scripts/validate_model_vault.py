"""Approved V2 only: round trip an owned synthetic OS-vault entry and remove it."""
import argparse
import json
import sys
from pathlib import Path
from uuid import uuid4
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from backend import paths as workspace_paths
VAR=workspace_paths.var(ROOT)
from backend.model_credentials import ModelCredentialVault

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--approved-v2',action='store_true')
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if not args.approved_v2:parser.error('须先取得本次系统凭据库合成记录验证的 V2 批准')
    directory=VAR/'model-vault-validation'/str(uuid4())
    vault=ModelCredentialVault(directory);account='synthetic-round-trip';created=False
    result={'level':'V2','scope':'owned synthetic OS-vault entry','real_credentials_accessed':False,'external_calls':False,'storage':vault.label,'status':'failed'}
    try:
        if vault.has(account):raise RuntimeError('验证目标已存在，停止且不改动')
        # Mark ownership before the call, so an interrupted write is still cleaned.
        created=True;value={'type':'api_key','key':'PUBLIC-REGENERABLE-VALIDATION-'+str(uuid4())}
        vault.set(account,value)
        if not vault.has(account) or vault.get(account)!=value:raise RuntimeError('系统凭据库读写未通过')
        value['key']='PUBLIC-REGENERABLE-REPLACEMENT-'+str(uuid4());vault.set(account,value)
        if vault.get(account)!=value:raise RuntimeError('系统凭据库更新未通过')
        result['status']='passed'
    finally:
        if created:
            vault.delete(account);result['owned_entry_removed']=not vault.has(account)
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(result,ensure_ascii=False))

if __name__=='__main__':main()
