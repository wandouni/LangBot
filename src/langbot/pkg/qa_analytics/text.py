"""Text normalization and keyword extraction for the Q&A dashboard."""

from __future__ import annotations

import collections
import ipaddress
import re
import unicodedata
import warnings

# Common Chinese and English stopwords.  The list is intentionally small: the
# dashboard is a frequency view, so domain words must survive even when they
# overlap with generic question words.
_STOPWORDS = frozenset(
    {
        '的',
        '了',
        '和',
        '是',
        '在',
        '我',
        '有',
        '你',
        '他',
        '她',
        '它',
        '们',
        '这',
        '那',
        '哪',
        '什么',
        '怎么',
        '怎样',
        '如何',
        '哪些',
        '哪个',
        '多少',
        '是否',
        '可以',
        '能否',
        '请问',
        '一下',
        '吗',
        '呢',
        '吧',
        '啊',
        '呀',
        '哦',
        '嗯',
        '一个',
        '这个',
        '那个',
        '我们',
        '你们',
        '他们',
        '以及',
        '还有',
        '但是',
        '因为',
        '所以',
        '如果',
        '需要',
        '关于',
        '对于',
        '进行',
        '相关',
        '问题',
        '学校',
        'a',
        'an',
        'the',
        'is',
        'are',
        'am',
        'be',
        'to',
        'of',
        'and',
        'or',
        'in',
        'on',
        'at',
        'for',
        'from',
        'with',
        'by',
        'how',
        'what',
        'which',
        'who',
        'when',
        'where',
        'why',
        'can',
        'could',
        'do',
        'does',
        'did',
        'i',
        'you',
        'we',
        'they',
        'it',
        'this',
        'that',
        'please',
        'about',
    }
)

_TOKEN_RE = re.compile(r'^[\w㐀-鿿]+$', re.UNICODE)
_JIEBA = None
_JIEBA_FAILED = False


def normalize_question(text: str) -> str:
    """Normalize a question for grouping.

    Whitespace, punctuation, symbols, and full-width/half-width differences are
    ignored.  Case is folded so the same English question groups together.
    """

    if not text:
        return ''
    normalized = unicodedata.normalize('NFKC', str(text)).casefold()
    chars = []
    for char in normalized:
        category = unicodedata.category(char)
        if category[0] in {'L', 'N'} or category == 'Mn':
            chars.append(char)
    return ''.join(chars)[:512]


def _tokenize_with_jieba(text: str) -> list[str]:
    global _JIEBA, _JIEBA_FAILED
    if _JIEBA_FAILED:
        return []
    if _JIEBA is None:
        try:
            with warnings.catch_warnings():
                # jieba still emits Python 3.12 invalid-escape and deprecated
                # pkg_resources warnings on import. They are not actionable for
                # operators and would otherwise appear on the first dashboard
                # request.
                warnings.simplefilter('ignore')
                import jieba

            # Keep startup quiet; the first dashboard render may initialize it.
            jieba.setLogLevel(20)
            _JIEBA = jieba
        except Exception:
            _JIEBA_FAILED = True
            return []
    return list(_JIEBA.cut(text))


def _fallback_tokens(text: str) -> list[str]:
    """Small dependency-free fallback used when jieba is unavailable."""

    tokens = []
    for run in re.findall(r'[A-Za-z0-9]+|[㐀-鿿]+', text):
        if re.match(r'^[A-Za-z0-9]+$', run):
            tokens.append(run.lower())
        elif len(run) <= 2:
            tokens.append(run)
        else:
            # CJK bigrams approximate segmentation well enough for a word cloud
            # and keep the dashboard usable in constrained deployments.
            tokens.extend(run[index : index + 2] for index in range(len(run) - 1))
    return tokens


def extract_keywords(text: str) -> list[str]:
    """Return display-ready keywords from one question."""

    if not text:
        return []
    tokens = _tokenize_with_jieba(text)
    if not tokens:
        tokens = _fallback_tokens(text)
    keywords = []
    for token in tokens:
        word = unicodedata.normalize('NFKC', str(token)).strip().casefold()
        if not word or word in _STOPWORDS or not _TOKEN_RE.match(word):
            continue
        # Single-character CJK tokens are rarely useful; keep short Latin
        # words such as "AI" when they are at least two characters.
        if len(word) < 2:
            continue
        if word.isdigit():
            continue
        keywords.append(word)
    return keywords


def build_word_cloud(texts: list[str], limit: int = 100) -> list[dict[str, int | str]]:
    """Count keywords across a bounded sample of questions."""

    counts: collections.Counter[str] = collections.Counter()
    for text in texts:
        counts.update(extract_keywords(text))
    return [{'word': word, 'count': count} for word, count in counts.most_common(max(int(limit), 1))]


def mask_ip(value: str | None) -> str:
    """Mask the host portion of an IP for list views."""

    if not value:
        return ''
    text = str(value).strip()
    try:
        address = ipaddress.ip_address(text)
    except ValueError:
        return text
    if address.version == 4:
        parts = text.split('.')
        return '.'.join(parts[:2] + ['*', '*'])
    parts = address.exploded.split(':')
    return ':'.join(parts[:3] + ['*'] * 5)


def is_local_ip(value: str | None) -> bool:
    if not value:
        return False
    try:
        address = ipaddress.ip_address(str(value).strip())
    except ValueError:
        return False
    return address.is_private or address.is_loopback or address.is_link_local
