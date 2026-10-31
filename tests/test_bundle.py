import functools
import http.server
import threading

import pytest

from vexpredict import bundle, publish
from vexpredict.dataset import load_season
from vexpredict.synth import add_upcoming, generate, make_live

pw = pytest.importorskip("playwright.sync_api")


def test_bundle_loads_in_browser(tmp_path, monkeypatch):
    raw = tmp_path / "raw"
    info = generate(raw, n_teams=150, n_events=25, n_skills_events=5, seed=4)
    now = make_live(raw, 50025, 0.5)
    add_upcoming(raw, now, [t for t in info["teams"] if t["grade"] == "High School"], n=12)
    publish.publish(load_season("t", root=raw), "t", out=tmp_path / "data", now_ts=now)
    monkeypatch.setattr(bundle, "CHUNK_BYTES", 200_000)        # force several chunks
    res = bundle.build(tmp_path / "dist", data_dir=tmp_path / "data")
    assert len(res["chunks"]) > 1
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(tmp_path / "dist"))
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{httpd.server_port}/index.html"
    errors = []
    with pw.sync_playwright() as p:
        b = p.chromium.launch()
        page = b.new_page()
        page.on("pageerror", lambda e: errors.append(str(e)))
        for h in ("", "#/leaderboard", "#/event/50025/forecast", "#/accuracy"):
            page.goto(url + h)
            page.wait_for_timeout(300)
            text = page.inner_text("main")
            assert "Couldn't load" not in text and "No data yet" not in text, h
        b.close()
    httpd.shutdown()
    assert not errors, errors
