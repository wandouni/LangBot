from __future__ import annotations

from langbot_plugin.api.definition.components.page import (
    Page,
    PageRequest,
    PageResponse,
)


class QAAnalyticsDashboardPage(Page):
    """Static page hosted by the plugin runtime.

    The dashboard's read-only data API is served by LangBot Core after it
    recognises this plugin's identity, so this component only has to exist for
    the runtime to mount the page. The fallback keeps older cores from
    returning an unhandled runtime error.
    """

    async def handle_api(self, request: PageRequest) -> PageResponse:
        del request
        return PageResponse.fail('Q&A analytics data is served by LangBot Core')
