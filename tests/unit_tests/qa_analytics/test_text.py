"""Unit tests for Q&A analytics text helpers."""

from __future__ import annotations

from langbot.pkg.qa_analytics import text


def test_normalize_question_ignores_case_width_and_punctuation():
    assert text.normalize_question('  Ｈｏｗ  MUCH，学费？ ') == 'howmuch学费'
    assert text.normalize_question(None) == ''


def test_extract_keywords_removes_question_stopwords():
    keywords = text.extract_keywords('请问护理专业能去哪些科室？')
    assert '护理' in keywords
    assert '专业' in keywords
    assert '科室' in keywords
    assert '哪些' not in keywords
    assert '请问' not in keywords


def test_build_word_cloud_orders_by_frequency():
    words = text.build_word_cloud(['学费是多少', '学费怎么交', '护理专业'], limit=10)
    assert words[0] == {'word': '学费', 'count': 2}
    assert all(item['word'] for item in words)


def test_mask_ip_masks_host_portion():
    assert text.mask_ip('203.0.113.42') == '203.0.*.*'
    assert text.mask_ip('2001:db8:85a3::8a2e:370:7334') == '2001:0db8:85a3:*:*:*:*:*'
    assert text.mask_ip('') == ''
    assert text.mask_ip('not-an-ip') == 'not-an-ip'


def test_is_local_ip():
    assert text.is_local_ip('127.0.0.1')
    assert text.is_local_ip('10.1.2.3')
    assert text.is_local_ip('192.168.1.10')
    assert not text.is_local_ip('8.8.8.8')
    assert not text.is_local_ip('not-an-ip')
