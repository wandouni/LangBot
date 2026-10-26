from __future__ import annotations

import os.path
import unicodedata

DISPLAY_FILE_NAME_MAX_LENGTH = 512

# Bidi controls can visually reorder an extension (for example, an "exe" name
# followed by U+202E). They have no legitimate place in a display-only label.
_BIDI_CONTROLS = frozenset(
    chr(code)
    for code in (0x061C, 0x200E, 0x200F, 0x202A, 0x202B, 0x202C, 0x202D, 0x202E, 0x2066, 0x2067, 0x2068, 0x2069)
)


def normalize_display_file_name(
    raw: object,
    *,
    allow_path: bool = False,
    max_length: int = DISPLAY_FILE_NAME_MAX_LENGTH,
) -> str | None:
    """Return a safe display-only file name.

    The result must never be used as a filesystem path, storage object key,
    authorization input, or uniqueness key.
    """
    if not isinstance(raw, str):
        return None

    name = raw.replace('\\', '/').strip()

    if allow_path:
        # Keep the relative directory so same-named entries from different ZIP
        # directories stay distinguishable, and resolve traversal segments.
        raw_parts = name.split('/')
        if len(raw_parts) >= 1 and len(raw_parts[0]) == 2 and raw_parts[0][1] == ':' and raw_parts[0][0].isalpha():
            raw_parts = raw_parts[1:]
        parts: list[str] = []
        for part in raw_parts:
            if part in ('', '.'):
                continue
            if part == '..':
                if parts:
                    parts.pop()
                continue
            parts.append(part)
        name = '/'.join(parts)
    else:
        name = name.rsplit('/', 1)[-1]

    name = ''.join(char for char in name if unicodedata.category(char) != 'Cc' and char not in _BIDI_CONTROLS).strip()
    if not name:
        return None

    if len(name) > max_length:
        _, extension = os.path.splitext(name)
        if extension and len(extension) <= 32:
            name = name[: max(0, max_length - len(extension) - 1)] + '…' + extension
        else:
            name = name[: max(0, max_length - 1)] + '…'

    return name
