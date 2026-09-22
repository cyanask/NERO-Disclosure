"""Focused event/task listing checks against isolated API and Store seams."""
import time
from uuid import uuid4

from internal_workflow import invoke
from backend.storage import Store
from test_agent_tasks import env, post


def issuer(client, code):
    response = client.post('/api/events', json={
        'company_name': '测试公司' + code,
        'stock_code': code,
        'board': 'chinext',
        'kind': 'unclassified',
        'title': '列表事项' + code,
        'summary': '仅用于列表隔离测试。',
        'facts': {},
        'request_id': str(uuid4()),
    })
    assert response.status_code == 200, response.text
    return response.json()


def task_request(client, event):
    response = post(client, event, 'agent-tasks', stage='assessment', instruction='仅用于列表读取测试')
    assert response.status_code == 200, response.text
    return response.json()['agent_tasks'][-1]


def test_event_listing_filters_order_and_reads_only_selected_events(env, monkeypatch):
    client, _, _, _ = env
    store = client.app.state.store
    first = issuer(client, '300101')
    second = issuer(client, '300102')
    original_get = store.get
    original_save = store.save
    reads = []
    writes = []

    def counted_get(conn, event_id):
        reads.append(event_id)
        return original_get(conn, event_id)

    def counted_save(conn, event):
        writes.append(event['id'])
        return original_save(conn, event)

    monkeypatch.setattr(store, 'get', counted_get)
    monkeypatch.setattr(store, 'save', counted_save)

    scoped = client.get('/api/events', params={'board': 'chinext', 'company': '300101'})
    assert scoped.status_code == 200
    assert [row['id'] for row in scoped.json()] == [first['id']]
    assert reads == [first['id']] and writes == []

    reads.clear()
    all_events = client.get('/api/events')
    assert all_events.status_code == 200
    assert [row['id'] for row in all_events.json()] == [second['id'], first['id']]
    assert reads == [second['id'], first['id']] and writes == []

    reads.clear()
    empty = client.get('/api/events', params={'board': 'chinext', 'company': '399999'})
    assert empty.status_code == 200 and empty.json() == []
    assert reads == [] and writes == []


def test_task_listing_order_scope_and_expired_lease_repair(env, monkeypatch):
    client, tokens, _, _ = env
    store = client.app.state.store
    first = issuer(client, '300101')
    second = issuer(client, '300102')
    first_task = task_request(client, first)
    second_task = task_request(client, second)
    claimed = post(client, first, f"agent-tasks/{first_task['id']}/claim", tokens[0],
                   host_family='pi', host_run_ref='synthetic-listing')
    assert claimed.status_code == 200, claimed.text

    original_get = store.get
    original_save = store.save
    reads = []
    writes = []

    def counted_get(conn, event_id):
        reads.append(event_id)
        return original_get(conn, event_id)

    def counted_save(conn, event):
        writes.append(event['id'])
        return original_save(conn, event)

    monkeypatch.setattr(store, 'get', counted_get)
    monkeypatch.setattr(store, 'save', counted_save)
    listed = invoke(client, tokens[0], 'task.list', {'board': 'chinext'})
    assert listed.status_code == 200
    assert [row['event_id'] for row in listed.json()] == [second['id'], first['id']]
    assert reads == [second['id'], first['id']] and writes == []

    clock = time.time()
    monkeypatch.setattr('backend.agent_tasks.time.time', lambda: clock + 1000)
    expired = invoke(client, tokens[0], 'task.list', {'board': 'chinext'})
    assert expired.status_code == 200
    first_row = next(row for row in expired.json() if row['event_id'] == first['id'])
    assert first_row['status'] == 'expired'
    saved = client.get('/api/events/' + first['id'])
    assert saved.status_code == 200
    assert saved.json()['agent_tasks'][0]['status'] == 'expired'


def test_store_event_ids_filters_board_and_company_without_loading_bodies(tmp_path):
    store = Store(tmp_path / 'events.sqlite3')
    rows = [
        {'id': 'chinext-300101', 'layer': 'chinext', 'stock_code': '300101', 'revision': 1},
        {'id': 'innovation-300102', 'layer': 'innovation', 'stock_code': '300102', 'revision': 1},
    ]
    with store.transaction() as conn:
        for row in rows:
            store.save(conn, row)

    with store.read() as conn:
        assert store.event_ids(conn) == ['innovation-300102', 'chinext-300101']
        assert store.event_ids(conn, board='chinext') == ['chinext-300101']
        assert store.event_ids(conn, company='300102') == ['innovation-300102']
        assert store.event_ids(conn, board='chinext', company='399999') == []
