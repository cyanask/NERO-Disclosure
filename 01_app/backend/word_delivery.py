"""Read case-backed layout rules; Word production belongs to the external host."""
import hashlib
import json
from .document_content import WordDeliveryError


def layout(seeds,event):
    seeds = seeds.for_event(event)
    from . import library
    selected=(event.get('draft') or {}).get('template_id')
    template=next((t for t in seeds.templates() if t['id']==selected),None)
    if selected and template is None:raise WordDeliveryError(409,'已选模板不在当前事项范围，请重新核对模板版本')
    if template is None:
        options=library.applicable_templates(seeds,event);template=options[0] if options else {}
    key=template.get('layout_profile_id')
    if not key:return None
    path=seeds.template_dir/'layout_profiles.json'
    try:result=next(p for p in json.loads(path.read_text('utf-8')) if p['id']==key)
    except (OSError,ValueError,StopIteration):raise WordDeliveryError(409,'版式profile缺失或无法读取')
    evidence=library.safe_file(seeds,result['source_observations_path'])
    if hashlib.sha256(evidence.read_bytes()).hexdigest()!=result['source_observations_sha256']:
        raise WordDeliveryError(409,'版式案例归纳记录发生变化，请重新接纳')
    return {**result,'template_authority':'user_uploaded'} if template.get('authority')=='user_uploaded' else result
