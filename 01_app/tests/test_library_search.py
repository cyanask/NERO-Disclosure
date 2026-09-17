"""Deterministic retrieval checks against isolated, synthetic board catalogs."""
import json

import pytest
from fastapi import HTTPException

from backend.domain import Seeds
from backend.library import search


@pytest.fixture
def search_seeds(tmp_path):
    public = tmp_path / 'data/public/boards/chinext'
    public.mkdir(parents=True)
    def law(id, article, text, **extra):
        return {'id': id, 'title': '测试公司规则', 'article': article, 'text': text,
                'library_board': 'chinext', 'layers': ['chinext'], 'event_kinds': ['related_transaction'],
                'effective_from': '2025-01-01', 'as_of': '2026-09-01', **extra}
    catalog = {'board': 'chinext', 'as_of': '2026-09-01', 'sources': [
        law('a12', '第十二条', '关联交易应审议累计金额。'),
        law('a13', '第十三条', '关联交易需回避表决。'),
        law('a14', '第十四条', '关联交易应披露。'),
        law('a15', '第十五条', '董事会召集程序。', event_kinds=['board_resolution']),
    ], 'cases': [
        {'id': 'admitted', 'text': '关联交易', 'kind': 'related_transaction',
         'library_board': 'chinext', 'layers': ['chinext'], 'eligible_as_case_evidence': True,
         'verification_status': 'official_original_indexed', 'original_path': 'data/public/test.pdf',
         'layer_at_publication': 'chinext', 'case_scope': {'verified_board_at_publication': 'chinext'}},
        {'id': 'pending', 'text': '关联交易', 'kind': 'related_transaction',
         'library_board': 'chinext', 'layers': ['chinext']},
    ]}
    (public / 'catalog.json').write_text(json.dumps(catalog), encoding='utf-8')
    (public / 'instruments.json').write_text(json.dumps([
        {'id': 'group', 'title': '测试公司规则', 'library_board': 'chinext', 'layers': ['chinext']}
    ]), encoding='utf-8')
    return Seeds(tmp_path, 'chinext')


def test_long_combination_falls_back_with_visible_missing_terms(search_seeds):
    result = search(search_seeds, 'laws', '关联交易 累计金额 回避 备案', limit=2)
    assert result['total'] == 3
    assert [row['id'] for row in result['items']] == ['a12', 'a13']
    assert result['search_strategy']['mode'] == 'partial_terms'
    assert result['search_strategy']['relaxed'] is True
    assert result['search_strategy']['coverage_complete'] is False
    assert result['items'][0]['matched_terms'] == ['关联交易', '累计金额']
    assert result['items'][0]['unmatched_terms'] == ['回避', '备案']
    assert search(search_seeds, 'laws', '关联交易 累计金额 回避 备案', offset=2)['items'][0]['id'] == 'a14'


def test_exact_results_keep_catalog_order_and_do_not_broaden(search_seeds):
    result = search(search_seeds, 'laws', '关联交易 累计金额')
    assert [row['id'] for row in result['items']] == ['a12']
    assert result['search_strategy']['mode'] == 'exact_terms'
    assert [row['id'] for row in search(search_seeds, 'laws', '关联交易')['items']] == ['a12', 'a13', 'a14']


def test_punctuation_keywords_and_numeric_article_locator(search_seeds):
    result = search(search_seeds, 'laws', '关联交易，累计金额')
    assert [row['id'] for row in result['items']] == ['a12']
    assert result['search_strategy']['mode'] == 'normalized_terms'
    result = search(search_seeds, 'laws', '第 12 条 回避')
    assert [row['id'] for row in result['items']] == ['a12']
    assert result['items'][0]['unmatched_terms'] == ['回避']
    # A missing clause must not silently degrade into an unrelated keyword hit.
    assert search(search_seeds, 'laws', '第99条 关联交易')['total'] == 0


def test_partial_matching_preserves_kind_and_case_admission_views(search_seeds):
    assert search(search_seeds, 'laws', '关联交易 备案', kind='board_resolution')['total'] == 0
    assert [r['id'] for r in search(search_seeds, 'cases', '关联交易 备案')['items']] == ['admitted']
    assert [r['id'] for r in search(search_seeds, 'cases', '关联交易 备案', view='candidates')['items']] == ['pending']
    result = search(search_seeds, 'laws', '公司规则 备案', view='groups')
    assert [r['id'] for r in result['items']] == ['group']
    assert result['view'] == 'groups'


def test_date_priority_is_retained_for_partial_candidates(search_seeds):
    path = search_seeds.public_dir / 'catalog.json'
    catalog = json.loads(path.read_text())
    catalog['sources'][0]['effective_to'] = '2025-02-01'
    path.write_text(json.dumps(catalog), encoding='utf-8')
    result = search(search_seeds, 'laws', '关联交易 累计金额 备案', as_of='2026-01-01')
    assert [row['id'] for row in result['items']] == ['a13', 'a14', 'a12']


def test_empty_result_advises_short_terms_without_claiming_coverage(search_seeds):
    result = search(search_seeds, 'laws', '找不到的完整自然语言问题')
    assert result['total'] == 0
    assert result['search_strategy']['mode'] == 'no_match'
    assert result['search_strategy']['coverage_complete'] is False
    assert result['search_strategy']['next_steps']


@pytest.mark.parametrize('query', ['，；', '第1百条', '第零条'])
def test_nonmatching_punctuation_and_malformed_article_do_not_fail(search_seeds, query):
    result = search(search_seeds, 'laws', query)
    assert result['total'] == 0
    assert result['search_strategy']['mode'] == 'no_match'


def test_wrong_board_catalog_is_still_rejected(search_seeds):
    path = search_seeds.public_dir / 'catalog.json'
    catalog = json.loads(path.read_text())
    catalog['sources'][0]['library_board'] = 'innovation'
    path.write_text(json.dumps(catalog), encoding='utf-8')
    with pytest.raises(HTTPException) as exc:
        search(search_seeds, 'laws', '关联交易 备案')
    assert exc.value.status_code == 409
