"""Run in the external Agent: create Word from a frozen word.context packet."""
import argparse
import base64
import hashlib
import json
import sys
import tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.word_renderer import render, render_document


def main():
    parser=argparse.ArgumentParser(description='外部 Agent Word 制作工具，不改变 Harness 状态')
    parser.add_argument('--context',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();packet=json.loads(args.context.read_text('utf-8'))
    if 'data' in packet:packet=packet['data']
    raw=base64.b64decode(packet['template_base64'],validate=True) if packet.get('template_base64') else None
    if raw is not None and hashlib.sha256(raw).hexdigest()!=packet['template_sha256']:raise ValueError('模板哈希不符')
    if packet.get('kind')=='runtime_document':
        from backend.document_files import inspect
        if packet.get('source_base64') and hashlib.sha256(base64.b64decode(packet['source_base64'],validate=True)).hexdigest()!=packet['source_sha256']:
            raise ValueError('人工源稿哈希不符')
        result=render_document(packet,raw)
        inspect(result)
    else:
        with tempfile.TemporaryDirectory(prefix='disclosure-word-') as work:
            template=Path(work)/'template.docx';template.write_bytes(raw)
            result,_=render(packet['event'],packet['layout'],template)
    with args.output.open('xb') as target:target.write(result)
    print(json.dumps({'path':str(args.output.resolve()),'sha256':hashlib.sha256(result).hexdigest(),
        'input_fingerprint':packet['input_fingerprint'],'bytes':len(result),
        'next_action':'由宿主完成内容及视觉复核后，通过 artifact.register 登记；不得宣称人工验收。'},ensure_ascii=False))

if __name__=='__main__':
    try:
        main()
    except Exception as exc:
        from backend.document_content import WordDeliveryError
        # Return an actionable bounded receipt; never expose a traceback or
        # arbitrary exception content from dependencies to the conversation.
        if isinstance(exc,WordDeliveryError):message=str(exc.detail)[:1500]
        elif isinstance(exc,FileExistsError):message='输出文件已经存在；请使用新的工作副本路径'
        else:message='Word 制作失败（'+type(exc).__name__+'），请核对模板及输入结构'
        print(json.dumps({'status':'failed','error':message,'error_type':type(exc).__name__},ensure_ascii=False))
        sys.exit(1)
