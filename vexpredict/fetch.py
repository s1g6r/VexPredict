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


def fetch_event(client: Client, event: dict) -> dict:
    eid = event["id"]
    teams = client.event_teams(eid)
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
    return {"event": event, "teams": teams, "skills": skills, "matches": matches, "rankings": rankings,
            "fetched_at": dt.datetime.now(dt.timezone.utc).isoformat()}


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--season", default="Push Back", help="part of the season name, e.g. 'Push Back' or 'Override'")
    ap.add_argument("--max-events", type=int, default=0, help="stop after this many downloads (0 = no limit)")
    ap.add_argument("--include-future", action="store_true", help="also save events that have not started")
    ap.add_argument("--min-interval", type=float, default=0.25, help="seconds between API requests")
    args = ap.parse_args(argv)

    client = Client(load_token(), base=config.API_BASE, min_interval=args.min_interval)
    season = find_season(client, args.season)
    slug = slugify(args.season)
    out = season_dir(slug)
    print(f"Season: {season['name']} (id {season['id']}) -> {out}")

    events = client.season_events(season["id"])
    now = dt.datetime.now(dt.timezone.utc)
    events = [e for e in events if (e.get("event_type") or "").lower() not in SKIP_EVENT_TYPES]
    if not args.include_future:
        events = [e for e in events if (parse_date(e.get("start")) or now) <= now]
    events.sort(key=lambda e: e.get("start") or "")
    write_json(out / "season.json", {"season": season, "event_count": len(events)})
    print(f"{len(events)} events to check")

    downloaded = skipped = failed = 0
    t0 = time.monotonic()
    try:
        for i, ev in enumerate(events, 1):
            path = out / "events" / f"{ev['id']}.json"
            if path.exists() and is_final(ev, now):
                try:
                    saved = json.loads(path.read_text())
                    if saved.get("final") and "rankings" in saved:
                        skipped += 1
                        continue
                except json.JSONDecodeError:
                    pass
            try:
                rec = fetch_event(client, ev)
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
