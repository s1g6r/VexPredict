"""Minimal VEX Events API v2 client.

Standard library only, so the data pull runs on a stock macOS/Windows Python
with nothing installed. Handles pagination, rate limiting (HTTP 429) and
transient server errors with exponential backoff.
"""
from __future__ import annotations

import json
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Iterable

from .config import API_BASE

PER_PAGE = 250


class ApiError(RuntimeError):
    pass


def _ssl_context() -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    try:  # python.org macOS builds ship without system certs; certifi fixes that
        import certifi  # type: ignore

        ctx.load_verify_locations(certifi.where())
    except Exception:
        pass
    return ctx


class Client:
    def __init__(self, token: str, base: str = API_BASE, min_interval: float = 0.25,
                 max_retries: int = 8, verbose: bool = True):
        self.token = token
        self.base = base.rstrip("/")
        self.min_interval = min_interval
        self.max_retries = max_retries
        self.verbose = verbose
        self._last = 0.0
        self._ctx = _ssl_context()
        self.requests_made = 0

    # -- low level -----------------------------------------------------
    def _url(self, path: str, params: Iterable[tuple[str, Any]] = ()) -> str:
        q = urllib.parse.urlencode([(k, v) for k, v in params])
        return f"{self.base}/{path.lstrip('/')}" + (f"?{q}" if q else "")

    def get(self, path: str, params: Iterable[tuple[str, Any]] = ()) -> Any:
        url = self._url(path, list(params))
        delay = 2.0
        for attempt in range(self.max_retries + 1):
            wait = self.min_interval - (time.monotonic() - self._last)
            if wait > 0:
                time.sleep(wait)
            req = urllib.request.Request(url, headers={
                "Authorization": f"Bearer {self.token}",
                "Accept": "application/json",
                "User-Agent": "VexPredict/0.1 (VEX V5RC match prediction)",
            })
            self._last = time.monotonic()
            try:
                with urllib.request.urlopen(req, timeout=60, context=self._ctx) as resp:
                    self.requests_made += 1
                    return json.loads(resp.read().decode("utf-8"))
            except urllib.error.HTTPError as e:
                if e.code in (401, 403):
                    raise ApiError(
                        f"HTTP {e.code} for {url}: the API token was rejected. "
                        "Check VEX_TOKEN in .env (tokens come from "
                        "https://events.vex.com/api/v2)."
                    ) from None
                if e.code == 404:
                    raise ApiError(f"HTTP 404 for {url}") from None
                if e.code == 429 or e.code >= 500:
                    ra = e.headers.get("Retry-After") if e.headers else None
                    sleep_for = float(ra) if ra and ra.replace(".", "").isdigit() else delay
                    self._log(f"  HTTP {e.code}, waiting {sleep_for:.0f}s (attempt {attempt + 1})")
                    time.sleep(sleep_for)
                    delay = min(delay * 2, 300)
                    continue
                raise ApiError(f"HTTP {e.code} for {url}: {e.read()[:300]!r}") from None
            except ssl.SSLError as e:
                raise ApiError(
                    f"SSL error ({e}). On a python.org Mac install, run "
                    "'/Applications/Python 3.x/Install Certificates.command' "
                    "or `pip3 install certifi`."
                ) from None
            except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
                self._log(f"  network error {e}, retrying in {delay:.0f}s")
                time.sleep(delay)
                delay = min(delay * 2, 300)
        raise ApiError(f"Gave up on {url} after {self.max_retries} retries")

    def get_all(self, path: str, params: Iterable[tuple[str, Any]] = ()) -> list:
        """Fetch every page of a paginated endpoint."""
        params = [p for p in params if p[0] not in ("page", "per_page")]
        out: list = []
        page = 1
        while True:
            body = self.get(path, params + [("per_page", PER_PAGE), ("page", page)])
            out.extend(body.get("data", []))
            meta = body.get("meta") or {}
            last = meta.get("last_page") or 1
            if page >= last:
                return out
            page += 1

    def _log(self, msg: str) -> None:
        if self.verbose:
            print(msg, file=sys.stderr, flush=True)

    # -- endpoints -----------------------------------------------------
    def seasons(self, program_id: int) -> list:
        return self.get_all("seasons", [("program[]", program_id)])

    def season_events(self, season_id: int) -> list:
        return self.get_all("events", [("season[]", season_id)])

    def event_teams(self, event_id: int) -> list:
        return self.get_all(f"events/{event_id}/teams")

    def event_skills(self, event_id: int) -> list:
        return self.get_all(f"events/{event_id}/skills")

    def division_matches(self, event_id: int, division_id: int) -> list:
        return self.get_all(f"events/{event_id}/divisions/{division_id}/matches")

    def division_rankings(self, event_id: int, division_id: int) -> list:
        return self.get_all(f"events/{event_id}/divisions/{division_id}/rankings")
