"""The data pull against a fake VEX Events API: pagination, a 429, resume,
and refreshing an event that isn't final yet."""
import datetime as dt
import http.server
import json
import threading
import urllib.parse

import pytest

from vexpredict import api as apimod
from vexpredict import config, fetch
from vexpredict.dataset import load_season

NOW = dt.datetime.now(dt.timezone.utc)
OLD = (NOW - dt.timedelta(days=30)).isoformat()
RECENT = (NOW - dt.timedelta(hours=5)).isoformat()


def _match(i, red, blue, rs, bs, scored=True):
    return {"id": i, "division": {"id": 1}, "round": 2, "instance": 1, "matchnum": i, "scored": scored,
            "started": OLD if scored else None,
            "alliances": [{"color": "red", "score": rs, "teams": [{"team": {"id": t, "name": str(t)}, "sitting": False} for t in red]},
                          {"color": "blue", "score": bs, "teams": [{"team": {"id": t, "name": str(t)}, "sitting": False} for t in blue]}]}


class Fake(http.server.BaseHTTPRequestHandler):
    hits = []
    throttled = []

    def log_message(self, *a):
        pass

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(u.query)
        Fake.hits.append(u.path)
        if self.headers.get("Authorization") != "Bearer tok":
            return self._send(401, {"message": "no"})
        if u.path.endswith("/skills") and Fake.throttled.count(u.path) < 3:
            Fake.throttled.append(u.path)     # three 429s in a row with "Retry-After: 0"
            self.send_response(429)
            self.send_header("Retry-After", "0")
            self.end_headers()
            return
        page = int(q.get("page", ["1"])[0])
        p = u.path.split("/api/v2/")[1]
        if p == "seasons":
            data = [{"id": 1, "name": "VEX V5 Robotics Competition 2024-2025: High Stakes", "years_start": 2024},
                    {"id": 2, "name": "VEX V5 Robotics Competition 2025-2026: Push Back", "years_start": 2025}]
            return self._page(data, page)
        if p == "events":
            assert q["season[]"] == ["2"]
            evs = [{"id": 10 + i, "sku": f"RE-V5RC-25-{i}", "name": f"Event {i}", "start": OLD, "end": OLD,
                    "event_type": "tournament", "divisions": [{"id": 1, "name": "D"}]} for i in range(3)]
            evs.append({"id": 20, "sku": "RE-V5RC-25-20", "name": "Live one", "start": RECENT, "end": RECENT,
                        "event_type": "tournament", "divisions": [{"id": 1, "name": "D"}]})
            evs.append({"id": 30, "sku": "W", "name": "Workshop", "start": OLD, "end": OLD, "event_type": "workshop", "divisions": []})
            return self._page(evs, page, per=2)
        if p.endswith("/teams"):
            return self._page([{"id": t, "number": f"{t}A", "grade": "High School"} for t in range(1, 5)], page)
        if p.endswith("/skills"):
            return self._page([{"team": {"id": 1, "name": "1A"}, "type": "driver", "score": 50}], page)
        if p.endswith("/matches"):
            ms = [_match(i, (1, 2), (3, 4), 10 + i, 12) for i in range(1, 6)] + [_match(6, (1, 3), (2, 4), 0, 0, scored=False)]
            return self._page(ms, page, per=4)
        if p.endswith("/rankings"):
            return self._page([{"rank": 1, "team": {"id": 1}, "division": {"id": 1}, "wins": 3, "losses": 2, "ties": 0,
                                "wp": 7, "ap": 20, "sp": 50}], page)
        return self._send(404, {})

    def _page(self, data, page, per=250):
        chunk = data[(page - 1) * per: page * per]
        last = max(1, -(-len(data) // per))
        return self._send(200, {"data": chunk, "meta": {"current_page": page, "last_page": last}})

    def _send(self, code, body):
        b = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b)


@pytest.fixture
def api(tmp_path, monkeypatch):
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Fake)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    monkeypatch.setattr(config, "API_BASE", f"http://127.0.0.1:{srv.server_port}/api/v2")
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(fetch, "season_dir", lambda slug: tmp_path / "raw" / slug)
    monkeypatch.setenv("VEX_TOKEN", "tok")
    monkeypatch.setattr(apimod, "BACKOFF_START", 0.01)
    monkeypatch.setattr(apimod, "MAX_INTERVAL", 0.02)
    Fake.hits.clear()
    Fake.throttled.clear()
    yield tmp_path
    srv.shutdown()


def test_pull_resume_and_load(api):
    fetch.main(["--season", "Push Back", "--min-interval", "0"])
    files = sorted(p.name for p in (api / "raw" / "push-back" / "events").glob("*.json"))
    assert files == ["10.json", "11.json", "12.json", "20.json"]           # workshop skipped
    rec = json.loads((api / "raw" / "push-back" / "events" / "10.json").read_text())
    assert len(rec["matches"]) == 6 and rec["rankings"] and rec["skills"]   # all pages, 429 retried
    assert rec["final"] is True
    live = json.loads((api / "raw" / "push-back" / "events" / "20.json").read_text())
    assert live["final"] is False

    # second run: finished events are not downloaded again, the live one is
    Fake.hits.clear()
    fetch.main(["--season", "Push Back", "--min-interval", "0"])
    touched = {h.split("/events/")[1].split("/")[0] for h in Fake.hits if "/events/" in h}
    assert touched == {"20"}

    season = load_season("push-back", root=api / "raw" / "push-back")
    assert len(season.matches) == 4 * 5                                     # unscored match dropped
    assert len(season.pending[10]) == 1
    assert season.rankings[10][1].awp == 1
    assert season.teams[1].is_hs


def test_bad_token_stops_with_clear_message(api, monkeypatch):
    monkeypatch.setenv("VEX_TOKEN", "wrong")
    with pytest.raises(Exception) as e:
        fetch.main(["--season", "Push Back", "--min-interval", "0"])
    assert "token was rejected" in str(e.value)


def test_retry_after_zero_still_backs_off(monkeypatch):
    """A 429 saying 'Retry-After: 0' must not cause instant retries."""
    import io
    import urllib.error
    calls, sleeps = [], []

    def fake_urlopen(req, timeout, context):
        calls.append(1)
        if len(calls) <= 3:
            raise urllib.error.HTTPError(req.full_url, 429, "Too Many", {"Retry-After": "0"}, io.BytesIO(b""))
        return io.BytesIO(b'{"data": [], "meta": {"last_page": 1}}')

    monkeypatch.setattr(apimod.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(apimod.time, "sleep", lambda s: sleeps.append(s))
    c = apimod.Client("tok", base="http://x", min_interval=0.25, verbose=False)
    assert c.get("seasons") == {"data": [], "meta": {"last_page": 1}}
    backoffs = [s for s in sleeps if s >= apimod.BACKOFF_START]
    assert backoffs[:3] == [5.0, 10.0, 20.0]
    assert c.min_interval > 0.25          # slowed down after the 429s
