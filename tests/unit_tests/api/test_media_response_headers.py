"""Content-safety headers for public media-cache downloads."""

from langbot.pkg.api.http.controller.groups.files import _media_response_headers


def test_plain_images_stay_inline():
    headers = _media_response_headers('image/png')

    assert headers['Content-Disposition'] == 'inline'
    assert headers['X-Content-Type-Options'] == 'nosniff'
    assert headers['Cache-Control'] == 'public, max-age=86400'


def test_svg_is_downloaded_instead_of_rendered():
    headers = _media_response_headers('image/svg+xml')

    assert headers['Content-Disposition'] == 'attachment'
    assert headers['Content-Security-Policy'] == "default-src 'none'; sandbox"


def test_non_media_types_are_attachments():
    for mime_type in ('text/html', 'application/javascript', 'application/octet-stream'):
        headers = _media_response_headers(mime_type)

        assert headers['Content-Disposition'] == 'attachment'
        assert headers['X-Content-Type-Options'] == 'nosniff'
