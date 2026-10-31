"""Loads every page of the site in a real browser against freshly published
synthetic data and fails on any JavaScript error. Skipped if Playwright
isn't installed."""
import functools
import http.server
import shutil
import threading
from pathlib import Path

import pytest

from vexpredict import publish
from vexpredict.dataset import load_season
from vexpredict.synth import add_upcoming, generate, make_live

pw = pytest.importorskip("playwright.sync_api")
SITE = Path(__file__).resolve().parent.parent / "site"


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    root = tmp_path_factory.mktemp("www")
    for f in ("index.html", "app.js", "style.css"):
        shutil.copy(SITE / f, root / f)
    raw = tmp_path_factory.mktemp("raw")
    info = generate(raw, n_teams=200, n_events=40, n_skills_events=10, seed=3)
    now = make_live(raw, 50040, 0.5)
    add_upcoming(raw, now, [t for t in info["teams"] if t["grade"] == "High School"], n=16)
    publish.publish(load_season("t", root=raw), "t", out=root / "data", now_ts=now)
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(root))
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_port}/", root
    httpd.shutdown()


def test_every_page_renders_without_errors(server):
    url, root = server
    import json
    ev = json.loads((root / "data" / "t" / "events" / "50040.json").read_text())
    me = ev["pending"][0]["red"][0]
    num_me = next(t["number"] for t in ev["teams"] if t["id"] == me)
    pages = ["#/", "#/events", "#/leaderboard", "#/accuracy", "#/event/50040/matches", "#/event/50040/forecast",
             "#/event/50040/picks", "#/event/50040/teams", "#/event/50040/brief", "#/event/90000/forecast",
             "#/event/50000/forecast", f"#/team/{me}", "#/nope"]
    with pw.sync_playwright() as p:
        b = p.chromium.launch()
        ctx = b.new_context(viewport={"width": 390, "height": 844})
        ctx.add_init_script(f"localStorage.setItem('vp:t:me', '{me}')")
        page = ctx.new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("console", lambda m: m.type == "error" and "fonts" not in m.text and "TUNNEL" not in m.text
                and errors.append(m.text))
        for h in pages:
            page.goto(url + h)
            page.wait_for_timeout(250)
            assert "Couldn't load" not in page.inner_text("main"), h
            width = page.evaluate("document.documentElement.scrollWidth")
            assert width <= 391, f"{h} scrolls sideways ({width}px)"
        # pick list interaction: marking a team picked moves it out of the numbered list
        page.goto(url + "#/event/50040/picks")
        page.wait_for_timeout(200)
        first = page.locator("tbody tr").first.locator("td.t a").inner_text()
        page.locator("tbody tr").first.get_by_role("button", name=f"{first} was picked").click()
        page.wait_for_timeout(100)
        assert page.locator("tbody tr").first.locator("td.t a").inner_text() != first
        assert page.locator("tbody tr.picked td.t a").inner_text() == first
        # divisions: the event opens on my team's division; switching shows the other division's teams
        page.goto(url + "#/event/50040/forecast")
        page.wait_for_timeout(200)
        sel = page.locator("#div")
        assert sel.count() == 1
        mine = sel.input_value()
        before = set(page.locator("tbody td.t a").all_inner_texts())
        assert num_me in before
        other = [o for o in page.locator("#div option").evaluate_all("os => os.map(o => o.value)") if o != mine][0]
        sel.select_option(other)
        page.wait_for_timeout(200)
        after = set(page.locator("tbody td.t a").all_inner_texts())
        assert after and not (after & before)
        sel = page.locator("#div")
        sel.select_option(mine)
        page.wait_for_timeout(200)
        # home shows the next match for my team
        page.goto(url + "#/")
        page.wait_for_timeout(200)
        assert "Your next match" in page.inner_text("main")
        b.close()
    assert not errors, errors
