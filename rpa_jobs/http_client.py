"""Polite HTTP client with throttling, retries and robots.txt awareness."""

from __future__ import annotations

import logging
import random
import re
import time
import urllib.robotparser as robotparser
from typing import Callable
from urllib.parse import urlparse

import requests

LOGGER = logging.getLogger("rpa.jobs.http")


_CHARSET_RE = re.compile(r"charset\s*=\s*[\"']?([\w.:-]+)", re.I)
_META_CHARSET_RE = re.compile(
    rb"<meta[^>]+charset\s*=\s*[\"']?([\w.:-]+)", re.I
)
_STRUCTURED_PREFIXES = (b"{", b"[", b"<?xml", b"<rss", b"<feed")


def _charset_from_content_type(content_type: str) -> str:
    match = _CHARSET_RE.search(content_type or "")
    return match.group(1).strip().lower() if match else ""


def _charset_from_meta(body: bytes) -> str:
    match = _META_CHARSET_RE.search(body[:4096])
    return match.group(1).decode("ascii", errors="ignore").strip().lower() if match else ""


def _looks_structured(body: bytes) -> bool:
    """True for JSON/XML bodies even when the server sends a vague Content-Type."""
    head = body[:256].lstrip(b"\xef\xbb\xbf \t\r\n")
    return head.startswith(_STRUCTURED_PREFIXES)


class FetchError(Exception):
    """Raised when a page cannot be retrieved after all retries."""

    def __init__(self, message: str, *, permanent: bool = False) -> None:
        super().__init__(message)
        self.permanent = permanent


class RobotsDenied(FetchError):
    """Raised when robots.txt forbids the requested URL."""

    def __init__(self, url: str) -> None:
        super().__init__(f"Blocked by robots.txt: {url}", permanent=True)


class HttpClient:
    """Small requests wrapper modelled on UiPath's HTTP Request activity.

    * one session per bot run (connection reuse)
    * per-host throttle so the portal is not hammered
    * exponential backoff with jitter on transient failures / 5xx / 429
    * robots.txt check (cached per host, failures are treated as allow)
    """

    def __init__(
        self,
        *,
        user_agent: str = "RPAJobBot/1.0",
        timeout: float = 20.0,
        retries: int = 3,
        backoff: float = 1.2,
        delay: float = 0.4,
        respect_robots: bool = True,
        session: requests.Session | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.user_agent = user_agent
        self.timeout = timeout
        self.retries = max(1, retries)
        self.backoff = backoff
        self.delay = max(0.0, delay)
        self.respect_robots = respect_robots
        self.sleep = sleep
        self.session = session or requests.Session()
        self.session.headers.update(
            {
                "User-Agent": user_agent,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
            }
        )
        self._last_request: dict[str, float] = {}
        self._robots_cache: dict[str, robotparser.RobotFileParser | None] = {}

    # ------------------------------------------------------------------ public
    def get(self, url: str) -> str:
        self._check_robots(url)
        origin = self._origin(url)
        last_error: Exception | None = None

        for attempt in range(1, self.retries + 1):
            self._throttle(origin)
            try:
                response = self.session.get(url, timeout=self.timeout)
            except requests.RequestException as exc:
                last_error = exc
                if attempt >= self.retries:
                    break
                self._backoff_wait(attempt)
                continue

            if response.status_code in (429, 503):
                wait = self._retry_after(response) or self.backoff * (2 ** (attempt - 1))
                last_error = FetchError(f"HTTP {response.status_code} for {url}")
                if attempt >= self.retries:
                    break
                LOGGER.warning("HTTP %s for %s - waiting %.1fs", response.status_code, url, wait)
                self.sleep(wait + random.uniform(0, 0.25))
                continue

            if 500 <= response.status_code < 600:
                last_error = FetchError(f"HTTP {response.status_code} for {url}")
                if attempt >= self.retries:
                    break
                self._backoff_wait(attempt)
                continue

            if 400 <= response.status_code < 500:
                raise FetchError(f"HTTP {response.status_code} for {url}", permanent=True)

            return self._decode(response)

        raise FetchError(f"Failed to fetch {url}: {last_error}") from last_error

    # ----------------------------------------------------------------- internal
    @staticmethod
    def _decode(response: requests.Response) -> str:
        """Decode the body without guessing the wrong charset.

        JSON and XML are UTF-8 by specification, yet ``requests`` leaves
        ``response.encoding`` unset for ``application/json`` and we would then
        fall back to ``apparent_encoding``, which happily guesses cp1252 and
        turns "it's" into "itâ€™s". Only HTML is worth guessing.
        """
        content_type = (response.headers.get("Content-Type") or "").lower()
        charset = _charset_from_content_type(content_type)

        if charset:
            try:
                return response.content.decode(charset, errors="replace")
            except LookupError:
                pass  # Unknown label: fall through to the sniffing below.

        structured = (
            "json" in content_type
            or "xml" in content_type
            or _looks_structured(response.content)
        )
        if structured:
            return response.content.decode("utf-8-sig", errors="replace")

        meta_charset = _charset_from_meta(response.content)
        if meta_charset:
            try:
                return response.content.decode(meta_charset, errors="replace")
            except LookupError:
                pass

        if not response.encoding or response.encoding.lower() == "iso-8859-1":
            response.encoding = response.apparent_encoding or "utf-8"
        return response.text

    @staticmethod
    def _origin(url: str) -> str:
        parsed = urlparse(url)
        return f"{parsed.scheme}://{parsed.netloc}"

    @staticmethod
    def _retry_after(response: requests.Response) -> float | None:
        raw = response.headers.get("Retry-After", "").strip()
        if not raw:
            return None
        try:
            return min(float(raw), 30.0)
        except ValueError:
            return None

    def _backoff_wait(self, attempt: int) -> None:
        self.sleep(self.backoff * (2 ** (attempt - 1)) + random.uniform(0, 0.25))

    def _throttle(self, origin: str) -> None:
        interval = self.delay
        parser = self._robots_cache.get(origin)
        if parser is not None:
            try:
                crawl_delay = parser.crawl_delay(self.user_agent)
                if crawl_delay:
                    interval = max(interval, float(crawl_delay))
            except Exception:  # pragma: no cover - defensive, robotparser is lenient
                pass
        if interval <= 0:
            self._last_request[origin] = time.monotonic()
            return
        elapsed = time.monotonic() - self._last_request.get(origin, 0.0)
        if elapsed < interval:
            self.sleep(interval - elapsed)
        self._last_request[origin] = time.monotonic()

    def _check_robots(self, url: str) -> None:
        if not self.respect_robots:
            return
        parser = self._robots_for(url)
        if parser is None:
            return
        if not parser.can_fetch(self.user_agent, url):
            raise RobotsDenied(url)

    def _robots_for(self, url: str) -> robotparser.RobotFileParser | None:
        origin = self._origin(url)
        if origin in self._robots_cache:
            return self._robots_cache[origin]

        parser = robotparser.RobotFileParser()
        parser.set_url(f"{origin}/robots.txt")
        try:
            response = self.session.get(f"{origin}/robots.txt", timeout=self.timeout)
            if response.status_code == 200:
                parser.parse(response.text.splitlines())
            elif response.status_code in (401, 403):
                # Convention: restricted robots.txt means "stay out".
                parser.disallow_all = True
            else:
                parser.allow_all = True
        except requests.RequestException:
            parser.allow_all = True
        self._robots_cache[origin] = parser
        return parser
