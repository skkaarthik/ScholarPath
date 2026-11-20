"""Fetching is kept separate from parsing.

* ``LiveFetcher`` makes polite HTTP requests: robots.txt check, allowed hosts
  only, timeouts, a delay between requests and bounded retries for transient
  failures. It never handles logins or bypasses access controls.
* ``SnapshotFetcher`` serves pages from saved HTML snapshots under
  ``data/snapshots/<source>/`` (see that folder's manifest.json). It lets the
  same parsers run offline.

Parsers receive HTML text and return canonical-record dicts; they never fetch.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from urllib import robotparser
from urllib.parse import urlparse

import requests

from .. import config


class FetchError(RuntimeError):
    """A page could not be retrieved (network, HTTP status, robots, host)."""

    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


class StructureError(RuntimeError):
    """A page was retrieved but did not have the structure the parser expects."""


@dataclass
class FetchedPage:
    url: str
    html: str
    fetched_at: str  # ISO UTC
    method: str  # live_http | browser_snapshot


class LiveFetcher:
    TRANSIENT_STATUSES = {429, 500, 502, 503, 504}

    def __init__(self, allowed_hosts: set[str], session: requests.Session | None = None,
                 delay_seconds: float = config.HTTP_DELAY_SECONDS,
                 timeout: float = config.HTTP_TIMEOUT_SECONDS,
                 max_retries: int = config.HTTP_MAX_RETRIES,
                 sleep=time.sleep):
        self.allowed_hosts = allowed_hosts
        self.session = session or requests.Session()
        self.session.headers.setdefault("User-Agent", config.HTTP_USER_AGENT)
        self.delay_seconds = delay_seconds
        self.timeout = timeout
        self.max_retries = max_retries
        self._sleep = sleep
        self._robots: dict[str, robotparser.RobotFileParser] = {}
        self._last_request = 0.0

    def _polite_wait(self) -> None:
        elapsed = time.monotonic() - self._last_request
        if elapsed < self.delay_seconds:
            self._sleep(self.delay_seconds - elapsed)
        self._last_request = time.monotonic()

    def _raw_get(self, url: str) -> requests.Response:
        last_error: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            self._polite_wait()
            try:
                response = self.session.get(url, timeout=self.timeout)
            except (requests.ConnectionError, requests.Timeout) as exc:
                last_error = exc
            else:
                if response.status_code not in self.TRANSIENT_STATUSES:
                    return response
                last_error = FetchError(f"HTTP {response.status_code}", response.status_code)
            if attempt < self.max_retries:
                self._sleep(2 ** attempt)
        raise FetchError(f"{url}: gave up after {self.max_retries} attempts ({last_error})")

    def _robots_allows(self, url: str) -> bool:
        parsed = urlparse(url)
        root = f"{parsed.scheme}://{parsed.netloc}"
        if root not in self._robots:
            parser = robotparser.RobotFileParser()
            response = self._raw_get(root + "/robots.txt")
            if response.status_code == 200:
                parser.parse(response.text.splitlines())
            elif response.status_code in (401, 403):
                parser.disallow_all = True
            else:  # 404 and similar: no robots rules published
                parser.allow_all = True
            self._robots[root] = parser
        return self._robots[root].can_fetch(config.HTTP_USER_AGENT, url)

    def get(self, url: str) -> FetchedPage:
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.netloc not in self.allowed_hosts:
            raise FetchError(f"{url}: host not in the configured allow-list {sorted(self.allowed_hosts)}")
        if not self._robots_allows(url):
            raise FetchError(f"{url}: disallowed by robots.txt")
        response = self._raw_get(url)
        if response.status_code != 200:
            raise FetchError(f"{url}: HTTP {response.status_code}", response.status_code)
        return FetchedPage(url=url, html=response.text, fetched_at=config.utc_now_iso(), method="live_http")


class SnapshotFetcher:
    """Serve pages from ``<snapshot_root>/<source_id>/manifest.json``."""

    def __init__(self, source_id: str, snapshot_root: Path = config.SNAPSHOT_DIR):
        self.folder = Path(snapshot_root) / source_id
        manifest_path = self.folder / "manifest.json"
        if not manifest_path.exists():
            raise FetchError(f"No snapshot manifest at {manifest_path}")
        self.manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    def get(self, url: str) -> FetchedPage:
        entry = self.manifest["pages"].get(url)
        if entry is None:
            raise FetchError(f"{url}: not present in snapshot manifest")
        html = (self.folder / entry["file"]).read_text(encoding="utf-8")
        return FetchedPage(url=url, html=html, fetched_at=entry["captured_at"], method="browser_snapshot")
