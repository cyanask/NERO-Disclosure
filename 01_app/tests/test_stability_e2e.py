"""Drafting recovery across the real Python/Pi/HTTP/Word boundaries.

Only the external model is simulated. Requests, tool switching, confirmation,
replay, the Word subprocess and downloads use the production implementations.
"""
import copy
import io
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from uuid import uuid4

from docx import Document
import pytest
from test_pi_runtime import client, settled
from backend import document_runtime


@pytest.mark.parametrize('protocol', ['openai-completions', 'openai-responses'])
def test_native_preflight_then_gap_choice_produces_downloadable_word(client, protocol):
    c, runtime, _ = client
    session = runtime.store.create_session('chinext', '', '隔离稳定性回归', str(uuid4()))
    title = '董事会秘书变动公告工作稿'
    labels = ['原任及新任董秘资料', '会议及审议结果']
    document = {
        'title': title, 'kind': 'announcement',
        'checked_topics': ['变动主体、人员资料与审议程序'],
        'gaps': [{'label': label, 'reason': '尚未提供', 'category': 'content', 'state': 'missing'}
                 for label in labels],
    }
    template = next(t for t in document_runtime.seeds_for(runtime, {'board': 'chinext'}).templates()
                    if t.get('kind') == 'management_change')
    first = '公司拟更换董秘，请制作公告Word。'
    second = '选择B，先制作Word。'
    state = {'turn': 1, 'saved': False, 'assessed': False, 'notice': None}
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            packet = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            requests.append((state['turn'], packet))
            names = [t.get('function', t)['name'] for t in packet.get('tools', [])]
            tool, args, answer = None, None, None
            if 'assess_document_readiness' in names and not state['assessed']:
                state['assessed'] = True
                tool, args = 'assess_document_readiness', {
                    'output':'word', 'documents': [document], 'request_quote': first if state['turn'] == 1 else second,
                    'decision': 'assess' if state['turn'] == 1 else 'proceed_with_gaps',
                }
                if state['turn'] == 2:
                    args.update(notice_id=state['notice'], choice_quote=second)
            elif 'make_word' in names and not state['saved']:
                state['saved'] = True
                tool, args = 'make_word', {'documents': [{
                    'title': title, 'kind': 'announcement', 'template_id': template['id'],
                    'text': '# '+title+'\n\n一、变动情况\n【待补：'+labels[0]+'】\n\n二、审议程序\n【待补：'+labels[1]+'】',
                    'pending': labels, 'basis': [],
                }]}
            else:
                answer = '请查看已登记的缺口。' if state['turn'] == 1 else 'Word工作稿已生成，待审阅。'
            if tool:
                delta = {'role': 'assistant', 'tool_calls': [{'index': 0, 'id': 'call-'+str(uuid4()),
                    'type': 'function', 'function': {'name': tool, 'arguments': json.dumps(args, ensure_ascii=False)}}]}
                stop = 'tool_calls'
            else:
                delta, stop = {'role': 'assistant', 'content': answer}, 'stop'
            raw = ('data: '+json.dumps({'id': 'offline', 'object': 'chat.completion.chunk',
                'choices': [{'index': 0, 'delta': delta, 'finish_reason': stop}]})+'\n\ndata: [DONE]\n\n').encode()
            if protocol == 'openai-responses':
                identity = str(uuid4())
                item = ({'type': 'function_call', 'id': 'fc_'+identity, 'call_id': 'call_'+identity,
                         'name': tool, 'arguments': json.dumps(args, ensure_ascii=False), 'status': 'completed'}
                        if tool else {'type': 'message', 'id': 'msg_'+identity, 'role': 'assistant',
                                      'status': 'completed', 'content': [{'type': 'output_text', 'text': answer, 'annotations': []}]})
                events = [
                    {'type': 'response.created', 'response': {'id': 'resp_'+identity}},
                    {'type': 'response.output_item.added', 'output_index': 0, 'item': item},
                    {'type': 'response.output_item.done', 'output_index': 0, 'item': item},
                    {'type': 'response.completed', 'response': {'id': 'resp_'+identity, 'status': 'completed', 'output': [item]}},
                ]
                raw = ''.join('data: '+json.dumps(event)+'\n\n' for event in events).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream')
            self.send_header('Content-Length', str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    runtime.config_override = copy.deepcopy(runtime.config_override)
    runtime.config_override['models'][0]['baseUrl'] = f'http://127.0.0.1:{server.server_port}/v1'
    runtime.config_override['models'][0]['api'] = protocol
    runtime.runner = None

    def send(text, request_id=None):
        return c.post(f'/api/chat/sessions/{session["id"]}/runs', json={
            'text': text, 'model_key': 'fixture-a', 'expected_revision': 0,
            'request_id': request_id or str(uuid4()),
        })

    try:
        notice = settled(c, send(first), timeout=30)
        assert notice['run']['status'] == 'waiting_user', notice
        assert not any(e['kind']=='completion_repair_started' for e in notice['events'])
        state['notice'] = notice['run']['document_preflight']['notice_id']
        messages_key = 'messages' if protocol == 'openai-completions' else 'input'
        assert c.get(f'/api/chat/sessions/{session["id"]}/documents').json()['items'] == []

        state['turn'] = 2
        state['assessed'] = False
        request_id = str(uuid4())
        completed = settled(c, send(second, request_id), timeout=30)
        assert completed['run']['status'] == 'completed', completed
        assert not any(e['kind'] in ('completion_repair_started', 'document_gap_notice') for e in completed['events'])
        second_wire = next(p for turn, p in requests if turn == 2)
        user_messages = [m['content'] if isinstance(m['content'], str)
                         else ''.join(block.get('text', '') for block in m['content'])
                         for m in second_wire[messages_key] if m.get('role') == 'user']
        assert user_messages == [first, second]
        surface = [e['body']['tools'] for e in completed['events'] if e['kind'] == 'model_tool_surface']
        assert any('assess_document_readiness' in tools for tools in surface)
        assert any('make_word' in tools for tools in surface)
        items = c.get(f'/api/chat/sessions/{session["id"]}/documents').json()['items']
        assert len(items) == 1 and items[0]['review_status'] == 'pending'
        download = c.get(items[0]['download'])
        assert download.status_code == 200
        word = Document(io.BytesIO(download.content))
        text = '\n'.join(p.text for p in word.paragraphs)
        assert title in text and all(label in text for label in labels)
        assert send(second, request_id).json()['id'] == completed['run']['id']
        assert c.get(f'/api/chat/sessions/{session["id"]}/documents').json()['items'][0]['version'] == 1
    finally:
        server.shutdown()
        server.server_close()
        thread.join(2)
