from __future__ import annotations

from langbot.pkg.utils.filename import DISPLAY_FILE_NAME_MAX_LENGTH, normalize_display_file_name


def test_keeps_a_plain_file_name():
    assert normalize_display_file_name('报告.pdf') == '报告.pdf'


def test_strips_windows_and_posix_directories():
    assert normalize_display_file_name('C:\\fakepath\\报告.pdf') == '报告.pdf'
    assert normalize_display_file_name('/tmp/uploads/report.pdf') == 'report.pdf'


def test_drops_traversal_segments_from_basenames():
    assert normalize_display_file_name('../evil.pdf') == 'evil.pdf'
    assert normalize_display_file_name('..\\..\\evil.pdf') == 'evil.pdf'


def test_keeps_relative_paths_when_allowed():
    assert normalize_display_file_name('a/../b/./c.pdf', allow_path=True) == 'b/c.pdf'
    assert normalize_display_file_name('C:/docs/report.pdf', allow_path=True) == 'docs/report.pdf'
    assert normalize_display_file_name('/docs/report.pdf', allow_path=True) == 'docs/report.pdf'


def test_removes_control_and_bidi_characters():
    assert normalize_display_file_name('a\u202eb.pdf') == 'ab.pdf'
    assert normalize_display_file_name('line\nbreak.pdf') == 'linebreak.pdf'


def test_returns_none_for_missing_or_blank_values():
    assert normalize_display_file_name(None) is None
    assert normalize_display_file_name(123) is None
    assert normalize_display_file_name('   ') is None
    assert normalize_display_file_name('/') is None


def test_truncates_long_names_and_keeps_the_extension():
    name = normalize_display_file_name('x' * 600 + '.pdf')

    assert len(name) == DISPLAY_FILE_NAME_MAX_LENGTH
    assert name.endswith('….pdf')


def test_truncates_long_names_without_an_extension():
    name = normalize_display_file_name('x' * 600, max_length=32)

    assert len(name) == 32
    assert name.endswith('…')
