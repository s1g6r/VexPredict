"""Pull a full V5RC season from the VEX Events API into data/raw/<season>/.

Usage (from the project folder):
    python3 -m vexpredict.fetch --season "Push Back"
    python3 -m vexpredict.fetch --season "Override"      # current season

Each event is saved as its own JSON file, so the pull is resumable: stop it
any time (Ctrl-C) and rerun the same command to pick up where it left off.
Finished events are never downloaded twice; events that are still ongoing or
very recent are refreshed on every run.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import time
from pathlib import Path

from .api import ApiError, Client
from . import config
from .config import V5RC_PROGRAM_ID, load_token, season_dir, slugify

FINAL_AFTER_DAYS = 3  # results are treated as final this long after an event ends
LEAGUE_DAYS = 2       # events longer than this are leagues (one night a week for months)
LEAGUE_REFRESH_HOURS = 6
PLAN_DAYS = 150          # team lists are kept for events up to this far ahead (event planner)
FUTURE_REFRESH_DAYS = 3  # how often those far-off team lists are re-pulled
SKIP_EVENT_TYPES = {"workshop"}


def parse_date(s: str | None) -> dt.datetime | None:
    if not s:
        return None
    try:
        d = dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=dt.timezone.utc)
    return d


def write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(obj, separators=(",", ":")))
    os.replace(tmp, path)


def find_season(client: Client, query: str) -> dict:
    q = query.lower()
    seasons = client.seasons(V5RC_PROGRAM_ID)
    hits = [s for s in seasons if q in s.get("name", "").lower()]
    if not hits:  # program ids could change after the VEX/RECF split; search everything
        seasons = [s for s in client.get_all("seasons")
                   if "v5" in s.get("name", "").lower() or "vrc" in s.get("name", "").lower()]
        hits = [s for s in seasons if q in s.get("name", "").lower()]
    if not hits:
        names = "\n  ".join(s.get("name", "?") for s in seasons[:15])
        raise SystemExit(f"No V5RC season matching {query!r}. Some seasons:\n  {names}")
    hits.sort(key=lambda s: s.get("years_start") or 0, reverse=True)
    return hits[0]


def is_final(event: dict, now: dt.datetime) -> bool:
    end = parse_date(event.get("end")) or parse_date(event.get("start"))
    return bool(end) and (now - end).days >= FINAL_AFTER_DAYS


def wanted_now(event: dict, saved: dict | None, now: dt.datetime) -> bool:
    """--live-only: is this event worth re-pulling on a frequent (event-day)
    run? Events on today (a day either side, for time zones) always; leagues
    at most every few hours; nothing else that is already saved."""
    if saved is None:
        return True
    start, end = parse_date(event.get("start")), parse_date(event.get("end")) or parse_date(event.get("start"))
    if not start or not end:
        return False
    if not (start - dt.timedelta(days=1) <= now <= end + dt.timedelta(days=1)):
        return False
    if (end - start).days > LEAGUE_DAYS:
        got = parse_date(saved.get("fetched_at"))
        return not got or now - got > dt.timedelta(hours=LEAGUE_REFRESH_HOURS)
    return True


def fetch_event(client: Client, event: dict, now: dt.datetime | None = None) -> dict:
    eid = event["id"]
    teams = client.event_teams(eid)
    start = parse_date(event.get("start"))
    if now and start and start - now > dt.timedelta(days=1):
        # not started: only the registered teams exist yet
        return {"event": event, "teams": teams, "skills": [], "matches": [], "rankings": [], "awards": [],
                "fetched_at": dt.datetime.now(dt.timezone.utc).isoformat(), "teams_only": True}
    skills = client.event_skills(eid)
    matches, rankings = [], []
    for div in event.get("divisions") or []:
        try:
            div_matches = client.division_matches(eid, div["id"])
        except ApiError as e:
            if "404" in str(e):
                continue
            raise
        matches.extend(div_matches)
        if not div_matches:          # skills-only or cancelled: no rankings to fetch
            continue
        try:
            rankings.extend(client.division_rankings(eid, div["id"]))
        except ApiError as e:
            if "404" not in str(e):
                raise
    try:
        awards = client.event_awards(eid)
    except ApiError as e:
        if "404" not in str(e):
            raise
        awards = []
    return {"event": event, "teams": teams, "skills": skills, "matches": matches, "rankings": rankings,
            "awards": awards, "fetched_at": dt.datetime.now(dt.timezone.utc).isoformat()}


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--season", default="Push Back", help="part of the season name, e.g. 'Push Back' or 'Override'")
    ap.add_argument("--max-events", type=int, default=0, help="stop after this many downloads (0 = no limit)")
    ap.add_argument("--include-future", action="store_true", help="also save every event that has not started")
    ap.add_argument("--ahead-days", type=float, default=14,
                    help="re-pull events starting within this many days on every run (pre-event forecasts)")
    ap.add_argument("--plan-days", type=float, default=PLAN_DAYS,
                    help="keep team lists for events up to this many days ahead, refreshed every few days")
    ap.add_argument("--min-interval", type=float, default=0.25, help="seconds between API requests")
    ap.add_argument("--live-only", action="store_true",
                    help="quick refresh: only events on today (and leagues every few hours); for frequent runs")
    args = ap.parse_args(argv)

    client = Client(load_token(), base=config.API_BASE, min_interval=args.min_interval)
    season = find_season(client, args.season)
    slug = slugify(args.season)
    out = season_dir(slug)
    print(f"Season: {season['name']} (id {season['id']}) -> {out}")

    events = client.season_events(season["id"])
    now = dt.datetime.now(dt.timezone.utc)
    events = [e for e in events if (e.get("event_type") or "").lower() not in SKIP_EVENT_TYPES]
    calendar = list(events)   # every event of the season, for the event planner
    soon = now + dt.timedelta(days=args.ahead_days)
    if not args.include_future:
        horizon = now + dt.timedelta(days=args.plan_days)
        events = [e for e in events if (parse_date(e.get("start")) or now) <= horizon]
    events.sort(key=lambda e: e.get("start") or "")
    write_json(out / "season.json", {"season": season, "event_count": len(events),
                                     "calendar": calendar, "calendar_at": now.isoformat()})
    print(f"{len(events)} events to check")

    downloaded = skipped = failed = 0
    t0 = time.monotonic()
    try:
        for i, ev in enumerate(events, 1):
            path = out / "events" / f"{ev['id']}.json"
            if args.live_only:
                try:
                    saved = json.loads(path.read_text()) if path.exists() else None
                except json.JSONDecodeError:
                    saved = None
                if not wanted_now(ev, saved, now):
                    skipped += 1
                    continue
            start = parse_date(ev.get("start"))
            if path.exists() and start and start > soon and not args.include_future:
                # far-off event: its team list only needs a refresh every few days
                try:
                    got = parse_date(json.loads(path.read_text()).get("fetched_at"))
                except json.JSONDecodeError:
                    got = None
                if got and now - got < dt.timedelta(days=FUTURE_REFRESH_DAYS):
                    skipped += 1
                    continue
            if path.exists() and is_final(ev, now):
                try:
                    saved = json.loads(path.read_text())
                    if saved.get("final") and "rankings" in saved:
                        if "awards" not in saved:   # saved before awards were pulled: add just those
                            try:
                                saved["awards"] = client.event_awards(ev["id"])
                            except ApiError as e:
                                if "404" not in str(e):
                                    raise
                                saved["awards"] = []
                            write_json(path, saved)
                            downloaded += 1
                            continue
                        skipped += 1
                        continue
                except json.JSONDecodeError:
                    pass
            try:
                rec = fetch_event(client, ev, now)
            except ApiError as e:
                failed += 1
                print(f"[{i}/{len(events)}] {ev.get('sku')} FAILED: {e}", file=sys.stderr)
                if "token was rejected" in str(e):
                    raise SystemExit(1)
                continue
            rec["final"] = is_final(ev, now)
            write_json(path, rec)
            downloaded += 1
            rate = downloaded / max(time.monotonic() - t0, 1e-9) * 60
            print(f"[{i}/{len(events)}] {ev.get('sku')} {ev.get('name', '')[:50]!r}: "
                  f"{len(rec['matches'])} matches, {len(rec['skills'])} skills "
                  f"({rate:.0f} events/min)", flush=True)
            if args.max_events and downloaded >= args.max_events:
                break
    except KeyboardInterrupt:
        print("\nStopped. Rerun the same command to resume.")
    print(f"Done: {downloaded} downloaded, {skipped} already saved, {failed} failed, "
          f"{client.requests_made} API requests.")


if __name__ == "__main__":
    main()
