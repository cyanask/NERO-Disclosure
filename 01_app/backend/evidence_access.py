"""Compact, factual source receipts. No model prose is used as access evidence."""
from urllib.parse import urlsplit

CATEGORIES = ('laws', 'cases', 'blacklist_cases', 'history', 'templates')
ALIASES = {'client_history': 'history', 'profiles': 'templates'}
FIELDS = ('id', 'title', 'name', 'article', 'instrument_id', 'source_kind', 'version',
          'effective_from', 'effective_to', 'sha256', 'text_sha256', 'document_sha256',
          'published_at', 'decision_number', 'url', 'publication_url', 'page_count',
          'stock_code', 'read_scope', 'schema_version')


def category(row, fallback=''):
    explicit = ALIASES.get(fallback, fallback)
    if explicit in CATEGORIES:
        return explicit
    kind = row.get('source_kind', '')
    if str(row.get('id', '')).startswith('announcement-'):
        return 'history'
    if kind == 'blacklist_case' or row.get('decision_number'):
        return 'blacklist_cases'
    if kind in ('official_case', 'imported_case_candidate', 'simulated'):
        return 'cases'
    if row.get('schema_version') == 'nero.disclosure.profile.v1':
        return 'templates'
    if row.get('article') or kind in ('official_rule', 'regulation', 'statute'):
        return 'laws'
    return ''


def compact(row, collection=''):
    if not isinstance(row, dict) or not row.get('id'):
        return None
    result = {k: row[k] for k in FIELDS if row.get(k) is not None}
    result['category'] = category(row, collection)
    if not result['category']:
        return None
    result['title'] = str(row.get('title') or row.get('name') or '名称未记录')
    url = row.get('publication_url') or row.get('url') or ''
    try: parsed = urlsplit(url) if isinstance(url, str) else None
    except ValueError: parsed = None
    result['url'] = url if parsed and parsed.scheme in ('https', 'http') and parsed.netloc and not parsed.username else ''
    if row.get('pages'):
        result['pages'] = [p['page'] for p in row['pages'] if isinstance(p, dict) and isinstance(p.get('page'), int)]
    return result


def access(name, args, data=None, *, failed=False):
    """Normalize known tool results; search lists and template options stay candidates."""
    args = args if isinstance(args, dict) else {}
    data = data if isinstance(data, dict) else {}
    collection = ALIASES.get(args.get('collection'), args.get('collection', ''))
    search = name in ('search_library', 'knowledge_search', 'library.search', 'task.library.search')
    read = name in ('read_library', 'knowledge_read', 'library.read', 'task.library.read')
    if name == 'knowledge_history':
        collection = 'history'; search = not args.get('item_id'); read = not search
    if read and str(args.get('item_id', '')).startswith('announcement-'):
        collection = 'history'
    if name == 'read_document_template':
        collection = 'templates'; read = True
    if not search and not read:
        return None
    collection = category(data, collection)
    if failed:
        return {'action': 'failed', 'category': collection, 'item_id': args.get('item_id') or args.get('template_id'), 'items': []}
    rows = data.get('items', []) if search else data.get('articles') or [data]
    items = [item for row in rows if (item := compact(row, collection))]
    if not collection and items and len({i['category'] for i in items}) == 1:
        collection = items[0]['category']
    return {'action': 'search' if search else 'read', 'category': collection,
            'items': items, 'status': data.get('status'), 'cache_hit': bool(data.get('cache_hit')),
            'total': data.get('total', len(rows)), 'fingerprint': data.get('fingerprint'),
            'coverage': data.get('coverage'), 'groups_only': args.get('view') == 'groups',
            'item_id': args.get('item_id') or args.get('template_id')}


def record(runtime, rid, name, args, response=None, *, failed=False):
    args = args if isinstance(args, dict) else {}
    data = response.get('data', {}) if isinstance(response, dict) else {}
    value = access(name, args, data, failed=failed)
    if value is not None:
        value.update(tool=name,request={k:args[k] for k in ('collection','query','item_id','template_id','page','view','offset') if k in args})
        runtime.trace(rid, 'evidence_access', value)
    # The document tool validated these bindings before returning successfully.
    if not failed and name in ('make_word', 'save_announcement'):
        for doc in data.get('documents', []):
            packet = next((d for d in args.get('documents', []) if d.get('title') == doc.get('title')), {})
            runtime.trace(rid, 'evidence_document', {
                'document_id': doc.get('document_id'), 'version': doc.get('version'),
                'title': doc.get('title'), 'template_id': doc.get('template_id'),
                'template_name': doc.get('template_name'),
                'source_ids': [b['source_id'][8:] for b in packet.get('basis', [])
                               if str(b.get('source_id', '')).startswith('library:')]})
