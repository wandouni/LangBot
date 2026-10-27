from __future__ import annotations

from langbot_plugin.api.definition.plugin import BasePlugin


class QAAnalyticsPlugin(BasePlugin):
    """Hosts the Q&A analytics page.

    Collection and read-only queries live in LangBot Core; this plugin only
    contributes the page asset and the sidebar entry.
    """

    async def initialize(self) -> None:
        pass
