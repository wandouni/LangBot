"""Optional offline IP geolocation for the Q&A dashboard."""

from __future__ import annotations

import collections
import os
import threading
import typing

from .text import is_local_ip


class GeoResolver:
    """Resolve visitor IPs through an optional GeoIP2 City database.

    The resolver is intentionally offline-only.  When GeoIP is disabled or the
    database is missing, callers receive an empty region and the dashboard
    displays "unknown".
    """

    def __init__(self, ap: typing.Any) -> None:
        self.ap = ap
        self._reader: typing.Any = None
        self._init_attempted = False
        self._lock = threading.Lock()
        self._cache: collections.OrderedDict[str, str] = collections.OrderedDict()
        self._cache_limit = 4096

    def _config(self) -> dict[str, typing.Any]:
        config = getattr(getattr(self.ap, 'instance_config', None), 'data', {}) or {}
        value = config.get('qa_analytics', {}).get('geoip', {})
        return value if isinstance(value, dict) else {}

    def _ensure_reader(self) -> typing.Any:
        if self._reader is not None or self._init_attempted:
            return self._reader
        with self._lock:
            if self._reader is not None or self._init_attempted:
                return self._reader
            self._init_attempted = True
            config = self._config()
            if not config.get('enabled', False):
                return None
            path = str(config.get('database_path', '') or '').strip()
            if not path:
                return None
            path = os.path.abspath(os.path.expanduser(path))
            if not os.path.isfile(path):
                self.ap.logger.warning('Q&A analytics GeoIP database was not found; regions stay unknown')
                return None
            try:
                import geoip2.database

                self._reader = geoip2.database.Reader(path)
            except Exception as exc:
                # Do not print the path; the failure mode is enough for
                # operators to diagnose a missing optional extra.
                self.ap.logger.warning(f'Q&A analytics GeoIP database could not be opened: {type(exc).__name__}')
                return None
        return self._reader

    def resolve(self, value: str | None) -> str:
        """Return a display region for one IP, or an empty string."""

        if not value:
            return ''
        text = str(value).strip()
        if not text:
            return ''
        if is_local_ip(text):
            return 'local'
        cached = self._cache.get(text)
        if cached is not None:
            self._cache.move_to_end(text)
            return cached
        reader = self._ensure_reader()
        region = ''
        if reader is not None:
            try:
                response = reader.city(text)
                parts = [
                    getattr(response.country, 'name', '') or '',
                    getattr(response.subdivisions.most_specific, 'name', '') or '',
                    getattr(response.city, 'name', '') or '',
                ]
                region = ', '.join(part for part in parts if part)[:255]
            except Exception:
                region = ''
        self._cache[text] = region
        while len(self._cache) > self._cache_limit:
            self._cache.popitem(last=False)
        return region

    def close(self) -> None:
        reader = self._reader
        self._reader = None
        if reader is not None:
            try:
                reader.close()
            except Exception:
                pass


def region_label(region: str | None) -> str:
    """Normalize stored region values for filtering."""

    return str(region or '').strip()
