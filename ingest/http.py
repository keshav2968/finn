"""HTTP plumbing: per-host throttling, retries with backoff, and a disk cache.

Every network call in the ingest layer goes through `PoliteSession`, so throttling
and retry behaviour is defined once.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable
from urllib.parse import urlsplit

import requests

from .common import IST, get_logger, iso_ist, now_ist

log = get_logger("http")

RETRYABLE_STATUS = {408, 425, 429, 500, 502, 503, 504}


class FetchError(RuntimeError):
    """A request failed after all retries (or a non-retryable status)."""

    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


class NotFound(FetchError):
    pass


class OfflineMiss(FetchError):
    """--offline was set and the cache has no copy of this URL."""


@dataclass
class CachedResponse:
    url: str
    text: str
    fetched_at: str
    from_cache: bool


class PoliteSession:
    def __init__(
        self,
        user_agent: str,
        timeout: float = 20,
        retries: int = 3,
        backoff: float = 2.0,
        extra_headers: dict[str, str] | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": user_agent,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
            }
        )
        if extra_headers:
            self.session.headers.update(extra_headers)
        self.timeout = timeout
        self.retries = max(1, retries)
        self.backoff = backoff
        self._sleep = sleep
        self._min_interval: dict[str, float] = {}
        self._last_call: dict[str, float] = {}

    def set_min_interval(self, host: str, seconds: float) -> None:
        self._min_interval[host] = seconds

    def _throttle(self, host: str) -> None:
        gap = self._min_interval.get(host, 0.0)
        last = self._last_call.get(host)
        if last is not None and gap > 0:
            wait = gap - (time.monotonic() - last)
            if wait > 0:
                self._sleep(wait)
        self._last_call[host] = time.monotonic()

    def get(
        self,
        url: str,
        params: dict | None = None,
        headers: dict[str, str] | None = None,
        accept: Callable[[requests.Response], bool] | None = None,
        attempts: int | None = None,
    ) -> requests.Response:
        """GET with retries. `accept` can reject a 200 response (e.g. an HTML error
        page where JSON was expected); rejected responses are retried like a 5xx.
        `attempts` overrides the session's retry count for this call."""
        host = urlsplit(url).netloc
        tries = max(1, attempts or self.retries)
        last_error = "no attempt made"
        for attempt in range(1, tries + 1):
            self._throttle(host)
            try:
                resp = self.session.get(url, params=params, headers=headers, timeout=self.timeout)
            except requests.RequestException as exc:
                last_error = short_error(exc)
            else:
                if resp.status_code == 404:
                    raise NotFound(f"404 Not Found: {resp.url}", status=404)
                if resp.status_code in RETRYABLE_STATUS:
                    last_error = f"HTTP {resp.status_code}"
                    retry_after = resp.headers.get("Retry-After", "")
                    if retry_after.isdigit() and attempt < tries:
                        self._sleep(min(int(retry_after), 60))
                        continue
                elif not resp.ok:
                    raise FetchError(f"HTTP {resp.status_code} for {resp.url}", status=resp.status_code)
                elif accept is not None and not accept(resp):
                    last_error = f"unexpected response body from {resp.url}"
                else:
                    return resp
            if attempt < tries:
                delay = self.backoff * (2 ** (attempt - 1))
                log.debug("retry %d/%d for %s in %.1fs (%s)", attempt, tries, url, delay, last_error)
                self._sleep(delay)
        host_path = urlsplit(url)
        raise FetchError(f"{host_path.netloc}{host_path.path}: {last_error} (x{tries})")

    def pause(self, seconds: float) -> None:
        if seconds > 0:
            self._sleep(seconds)


def short_error(exc: BaseException) -> str:
    """urllib3 nests the real cause several layers deep ("...Caused by ProxyError(
    'Unable to connect', OSError('Tunnel connection failed: 403 Forbidden'))").
    Keep the innermost quoted reason so the summary stays readable."""
    msg = str(exc)
    if "Caused by" in msg:
        quoted = re.findall(r"'([^']{3,})'", msg)
        if quoted:
            msg = quoted[-1]
    return f"{type(exc).__name__}: {msg[:160]}"


class DiskCache:
    """Caches response bodies on disk, keyed by URL, with a TTL.

    Layout: <dir>/<sha1>.body and <sha1>.meta.json (url, fetched_at).
    """

    def __init__(self, directory: Path):
        self.dir = directory
        self.dir.mkdir(parents=True, exist_ok=True)

    def _paths(self, url: str) -> tuple[Path, Path]:
        key = hashlib.sha1(url.encode("utf-8")).hexdigest()
        return self.dir / f"{key}.body", self.dir / f"{key}.meta.json"

    def load(self, url: str, max_age: timedelta | None) -> CachedResponse | None:
        body, meta = self._paths(url)
        if not body.exists() or not meta.exists():
            return None
        try:
            info = json.loads(meta.read_text(encoding="utf-8"))
            fetched = datetime.fromisoformat(info["fetched_at"])
        except (ValueError, KeyError, json.JSONDecodeError):
            return None
        if max_age is not None and now_ist() - fetched.astimezone(IST) > max_age:
            return None
        return CachedResponse(url, body.read_text(encoding="utf-8"), info["fetched_at"], True)

    def save(self, url: str, text: str) -> CachedResponse:
        body, meta = self._paths(url)
        fetched_at = iso_ist(now_ist())
        body.write_text(text, encoding="utf-8")
        meta.write_text(json.dumps({"url": url, "fetched_at": fetched_at}), encoding="utf-8")
        return CachedResponse(url, text, fetched_at, False)


def cached_get_text(
    http: PoliteSession,
    cache: DiskCache,
    url: str,
    ttl: timedelta,
    refresh: bool = False,
    offline: bool = False,
) -> CachedResponse:
    """Serve from cache when fresh; otherwise fetch and store.

    offline: never touch the network; any cached copy is used regardless of age.
    refresh: ignore the cache and fetch.
    """
    if offline:
        hit = cache.load(url, max_age=None)
        if hit is None:
            raise OfflineMiss(f"--offline: no cached copy of {url}")
        return hit
    if not refresh:
        hit = cache.load(url, max_age=ttl)
        if hit is not None:
            return hit
    try:
        resp = http.get(url)
    except NotFound:
        raise
    except FetchError as exc:
        # An old copy beats nothing: fundamentals change once a quarter.
        stale = cache.load(url, max_age=None)
        if stale is None:
            raise
        log.warning("%s unreachable (%s); using cached copy from %s", url, exc, stale.fetched_at)
        return stale
    return cache.save(url, resp.text)
