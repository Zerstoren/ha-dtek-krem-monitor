"""Live HTTP tests against the public DTEK KREM shutdowns site.

These tests are skipped in CI unless LIVE_DTEK=1 is set.

Incapsula first returns an ~800-byte iframe stub and sets cookies.
The next GET on the same curl_cffi session is the real Laravel page.
"""

from __future__ import annotations

import asyncio
import os
import unittest

from component_loader import load_component_module

dtek_client = load_component_module("dtek_client")

LIVE_ENABLED = os.environ.get("LIVE_DTEK") == "1"


def _run(coro):
    return asyncio.run(coro)


def _page_report(html: str, status_code: int | None = None) -> str:
    token = dtek_client._extract_csrf_token(html)
    report = (
        f"status={status_code} "
        f"{dtek_client._html_debug_summary(html)} "
        f"csrf={bool(token)} protection={dtek_client._is_protection_page(html)}"
    )
    if len(html) < 2000:
        report = f"{report} html={html!r}"
    return report


async def _get_shutdowns(session, headers=None):
    resp = await session.get(
        dtek_client.DTEK_SHUTDOWNS_URL,
        headers=headers,
        timeout=dtek_client.REQUEST_TIMEOUT,
        allow_redirects=True,
    )
    return resp.status_code, resp.text


@unittest.skipUnless(LIVE_ENABLED, "Set LIVE_DTEK=1 to run live DTEK requests")
class LiveDtekHandshakeTests(unittest.TestCase):
    """Document the live Incapsula handshake against www.dtek-krem.com.ua."""

    def test_first_get_is_incapsula_stub(self) -> None:
        """The first GET is the ~800-byte Incapsula iframe, not Laravel."""
        from curl_cffi.requests import AsyncSession

        async def _check() -> tuple[int, str]:
            async with AsyncSession(impersonate="chrome120") as session:
                return await _get_shutdowns(session)

        status_code, html = _run(_check())
        report = _page_report(html, status_code)
        self.assertEqual(status_code, 200, report)
        self.assertTrue(dtek_client._is_protection_page(html), report)
        self.assertIsNone(dtek_client._extract_csrf_token(html), report)
        self.assertIn("_Incapsula_Resource", html, report)

    def test_second_get_same_session_is_laravel_page(self) -> None:
        """Keeping Incapsula cookies and repeating GET yields the real page."""
        from curl_cffi.requests import AsyncSession

        async def _check() -> tuple[tuple[int, str], tuple[int, str]]:
            async with AsyncSession(impersonate="chrome120") as session:
                first = await _get_shutdowns(session)
                second = await _get_shutdowns(session)
                return first, second

        first, second = _run(_check())
        first_report = _page_report(first[1], first[0])
        second_report = _page_report(second[1], second[0])
        self.assertTrue(dtek_client._is_protection_page(first[1]), first_report)
        self.assertEqual(second[0], 200, second_report)
        self.assertGreater(len(second[1]), 2000, second_report)
        self.assertFalse(dtek_client._is_protection_page(second[1]), second_report)
        self.assertIsNotNone(dtek_client._extract_csrf_token(second[1]), second_report)

    def test_second_get_works_with_client_page_headers(self) -> None:
        """Production PAGE_HEADERS must not break the Incapsula cookie handshake."""
        from curl_cffi.requests import AsyncSession

        async def _check() -> str:
            async with AsyncSession(impersonate="chrome120") as session:
                await _get_shutdowns(session, dtek_client.PAGE_HEADERS)
                _status, html = await _get_shutdowns(session, dtek_client.PAGE_HEADERS)
                return html

        html = _run(_check())
        report = _page_report(html)
        self.assertGreater(len(html), 2000, report)
        self.assertFalse(dtek_client._is_protection_page(html), report)
        self.assertIsNotNone(dtek_client._extract_csrf_token(html), report)


@unittest.skipUnless(LIVE_ENABLED, "Set LIVE_DTEK=1 to run live DTEK requests")
class LiveDtekClientTests(unittest.TestCase):
    """Exercise the real DTEK KREM endpoints with the production client."""

    def test_shutdowns_page_has_csrf_token(self) -> None:
        """The client must retry past Incapsula and return the Laravel HTML."""

        async def _check() -> str:
            client = dtek_client.DTEKClient()
            try:
                return await client._load_shutdowns_page()
            finally:
                await client.close()

        html = _run(_check())
        report = _page_report(html)
        token = dtek_client._extract_csrf_token(html)

        self.assertGreater(len(html), 2000, report)
        self.assertFalse(dtek_client._is_protection_page(html), report)
        self.assertIsNotNone(token, report)

    def test_get_streets_returns_cities(self) -> None:
        """A warmed session must be able to fetch the city/street dictionary."""

        async def _check() -> dict:
            client = dtek_client.DTEKClient()
            try:
                return await client.get_streets()
            finally:
                await client.close()

        streets = _run(_check())
        self.assertIsInstance(streets, dict)
        self.assertGreater(len(streets), 0, f"empty streets payload: {streets!r}")


if __name__ == "__main__":
    unittest.main()
