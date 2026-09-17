"""Lexical fallback only: a candidate match never establishes source coverage."""
import json
import re


NUMBER = r'[0-9]+|[零〇一二三四五六七八九十百千]+'
ARTICLE = re.compile(r'第\s*(' + NUMBER + r')\s*条(?:之(' + NUMBER + r'))?')
SEPARATORS = re.compile(r'[\s,，;；、|｜：:。？！?!]+')


def _number(value):
    if value.isdecimal():
        return str(int(value))
    digits = dict(zip('零〇一二三四五六七八九', (0, 0, 1, 2, 3, 4, 5, 6, 7, 8, 9)))
    if not any(char in '十百千' for char in value):
        return str(int(''.join(str(digits[char]) for char in value)))
    total = digit = 0
    for char in value:
        if char in digits:
            digit = digits[char]
        else:
            total += (digit or 1) * {'十': 10, '百': 100, '千': 1000}[char]
            digit = 0
    return str(total + digit)


def _article(match):
    return '第' + _number(match[1]) + '条' + ('之' + _number(match[2]) if match[2] else '')


def match_rows(rows, query):
    """Preserve exact results; only relax an empty result within supplied rows."""
    original_terms = list(dict.fromkeys(query.casefold().split()))
    indexed = [(row, json.dumps(row, ensure_ascii=False).casefold()) for row in rows]
    matched = [(row, original_terms) for row, content in indexed
               if all(term in content for term in original_terms)]
    terms = original_terms
    mode = 'exact_terms' if original_terms else 'browse'
    anchors = []
    if not matched and original_terms:
        normalized = ARTICLE.sub(lambda match: ' ' + _article(match) + ' ', query.casefold())
        terms = list(dict.fromkeys(term for term in SEPARATORS.split(normalized) if term))
        anchors = [term for term in terms if ARTICLE.fullmatch(term)]
        candidates = []
        for row, content in indexed:
            # A clause locator remains mandatory even when other words are relaxed.
            row_article = ARTICLE.sub(_article, str(row.get('article', ''))).strip()
            if anchors and row_article not in anchors:
                continue
            normalized_content = ARTICLE.sub(_article, content)
            hits = [term for term in terms if term in normalized_content]
            if hits:
                candidates.append((row, hits))
        matched = [(row, hits) for row, hits in candidates if len(hits) == len(terms)]
        mode = 'normalized_terms'
        if not matched:
            matched = sorted(candidates, key=lambda entry: -len(entry[1]))
            mode = 'partial_terms' if matched else 'no_match'
    strategy = {'mode': mode, 'original_query': query, 'terms': terms,
                'article_anchors': anchors, 'relaxed': mode == 'partial_terms',
                'coverage_complete': False,
                'limitations': '仅为本板块已登记资料的词面匹配；部分匹配可能遗漏条件，命中不表示适用、版本有效或法源覆盖完整。',
                'next_steps': (['用未匹配的短关键词分别检索', '用第N条定位条款或 view=groups 查找法规分组',
                                '读取相关全文核对定义、例外和有效版本；仍缺依据时明确资料缺口']
                               if mode in ('partial_terms', 'no_match') else [])}
    return matched, terms, strategy
