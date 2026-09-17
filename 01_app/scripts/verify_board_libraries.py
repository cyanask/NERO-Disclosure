"""Read-only board structure and file integrity checks; no legal acceptance claim."""
import hashlib
import json
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from backend import paths as workspace_paths
KNOWLEDGE=workspace_paths.knowledge_of(ROOT)
from backend.domain import Seeds
from backend.library import admitted_case
from backend.boards import ACTIVE_BOARDS


def verify(root=KNOWLEDGE, boards=None):
    root=Path(root);reports={}
    selected=tuple(boards) if boards is not None else tuple(ACTIVE_BOARDS)
    for board in selected:
        seed=Seeds(root,board);catalog=seed.catalog();errors=[]
        sources={r['id']:r for r in catalog['sources']};cases={r['id']:r for r in catalog['cases']}
        layouts={r['id']:r for r in catalog['layout_profiles']}
        for key in ('sources','cases','profiles','rules','templates','instruments'):
            rows=catalog[key]
            if len({r['id'] for r in rows})!=len(rows):errors.append('duplicate:'+key)
            for row in rows:
                if row.get('library_board')!=board:errors.append('board:'+row['id'])
                if row.get('layers') and row['layers']!=[board]:errors.append('layers:'+row['id'])
                for path_key,hash_key in (('original_path','sha256'),('document_path','document_sha256')):
                    if row.get(path_key):
                        path=(root/row[path_key]).resolve()
                        if not path.is_relative_to((root/'data/public').resolve()) or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=row.get(hash_key):errors.append('asset:'+row['id'])
        for profile in catalog['profiles']:
            if not set(profile['normative_source_ids'])<=sources.keys():errors.append('profile_law:'+profile['id'])
            if not {e['case_id'] for e in profile['case_evidence']}<=cases.keys():errors.append('profile_case:'+profile['id'])
            if profile['layout_profile_id'] not in layouts:errors.append('profile_layout:'+profile['id'])
        for rule in catalog['rules']:
            if not set(rule['source_ids'])<=sources.keys():errors.append('rule_source:'+rule['id'])
        for template in catalog['templates']:
            if len(catalog['template_asset_state'].get(template['id'],''))!=64:errors.append('template_asset:'+template['id'])
        for layout in layouts.values():
            if catalog['asset_state'].get(layout['source_observations_path'])!=layout['source_observations_sha256']:errors.append('layout_asset:'+layout['id'])
        reports[board]={'structural_status':'passed' if not errors else 'failed','issues':errors,
            'counts':{key:len(catalog[key]) for key in ('sources','cases','profiles','templates','rules')},
            'imported_cases_pending_originals':sum(r.get('verification_status')=='imported_source_unverified' for r in cases.values()),
            'cases_without_original_path':sum(not r.get('original_path') for r in cases.values()),
            'admitted_cases':sum(admitted_case(r,board) for r in cases.values()),
            'candidate_cases':sum(not admitted_case(r,board) for r in cases.values()),
            'registered_official_cases':sum(r.get('verification_status')=='official_original_indexed' for r in cases.values()),
            'pending_publication_layer':sum(r.get('scope_review_status')=='publication_layer_unverified' for r in cases.values()),
            'pending_layout_review':sum(r.get('scope_review_status')=='layout_scope_review_required' for r in layouts.values()),
            'legal_correctness_verified':False,'human_acceptance':False,
            'active_scope':board in ACTIVE_BOARDS}
    return reports


if __name__=='__main__':
    result=verify();print(json.dumps(result,ensure_ascii=False,indent=2))
    raise SystemExit(0 if all(r['structural_status']=='passed' for r in result.values()) else 1)
