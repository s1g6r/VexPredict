"""Build the static JSON the website reads.

    python3 -m vexpredict.publish --season "Override"

Writes site/data/<season>/:
  meta.json          season, model, generated time, event index
  leaderboard.json   every High School team's current rating and rank
  events/<id>.json   teams (rating, skills, auton rates), every match with the
                     prediction made *before* it was played, predicted final
                     rankings and captain odds (pre-event, and live if quals
                     remain), final rankings when finished
  teams/<id>.json    rating history and match log for one team
  accuracy.json      backtest + simulator check results, if they have been run

The API token never leaves the machine running this; the site is plain files.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import os
from collections import defaultdict
from pathlib import Path

import numpy as np

from .config import REPORTS_DIR, ROOT, slugify
from .dataset import Match, Season, load_season
from .models.epa import EPA, EPASkills, fit_skills_map
from .simulator import (ScoreNoise, SimInputs, captain_count, fit_score_noise, simulate,
                        standings_from_matches, standings_from_rankings, team_rates)

SITE_DATA = ROOT / "site" / "data"
SIMS = 1500


def _iso(ts: float) -> str:
    return dt.datetime.fromtimestamp(ts, dt.timezone.utc).strftime("%Y-%m-%d")


def _r(x, nd=1):
    return None if x is None else round(float(x), nd)


def _write(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(obj, separators=(",", ":")))
    os.replace(tmp, path)


def build_model(season: Season, slug: str, tune_from: str | None = None) -> tuple[EPA, dict]:
    """EPA + skills prior with the best available settings: this season's
    backtest if it exists, else another season's (e.g. Push Back settings for
    Override), else defaults. The skills-to-points map is refit on this season
    once there is enough data, since each game scores differently."""
    for src in (slug, tune_from):
        metrics = REPORTS_DIR / src / "metrics.json" if src else None
        if metrics and metrics.exists():
            p = dict(json.loads(metrics.read_text())["results"]["EPA + skills prior"]["params"])
            p["skills_map"] = (p.pop("skills_a"), p.pop("skills_b"))
            source = "tuned by backtest" if src == slug else f"tuned by the {src} backtest"
            if src != slug and season.matches:
                a, b, _, n = fit_skills_map(season, season.matches[-1].ts + 1)
                if n >= 200:
                    p["skills_map"] = (a, b)
            return EPASkills(**p), {"source": source, **{k: v for k, v in p.items() if k != "skills_map"},
                                    "skills_map": list(p["skills_map"])}
    split = season.matches[int(len(season.matches) * 0.4)].ts if season.matches else math.inf
    a, b, _, _ = fit_skills_map(season, split)
    return EPASkills(skills_map=(a, b)), {"source": "defaults (run the backtest to tune)", "skills_map": [a, b]}


def _sim_settings(slug: str, tune_from: str | None = None) -> float:
    for src in (slug, tune_from):
        path = REPORTS_DIR / src / "simcheck.json" if src else None
        if path and path.exists():
            return float(json.loads(path.read_text())["u0"])
    return 0.3


def _random_schedule(teams: list[int], per_team: int, rng: np.random.Generator):
    out = []
    for _ in range(per_team):
        p = list(rng.permutation(teams))
        for i in range(0, len(p) - 3, 4):
            out.append((tuple(p[i:i + 2]), tuple(p[i + 2:i + 4])))
    return out


def run_sim(season: Season, teams: list[int], rating: dict[int, float], played_n: dict[int, int],
            score_std: float, noise: ScoreNoise, u0: float, before_ts: float, eid: int,
            played: list[Match] | None = None, remaining=None, live_rankings=None, per_team: int = 8) -> dict:
    """Predicted final rankings. With no published schedule, averages over
    several random schedules (V5RC schedules are random)."""
    rates = team_rates(season, before_ts)
    unc = {t: u0 * score_std / math.sqrt(1 + played_n.get(t, 0) / 4) for t in teams}
    if live_rankings:
        st = standings_from_rankings({t: r for t, r in live_rankings.items() if t in set(teams)})
    else:
        st = standings_from_matches(played or [], rates)
    rng = np.random.default_rng(eid)
    if remaining is not None:
        res = simulate(SimInputs(teams, st, remaining, rating, unc, rates, noise), sims=SIMS, seed=eid)
        probs, mean = res.rank_probs, res.mean_rank
    else:
        k = 8
        probs = np.zeros((len(teams), len(teams)))
        mean = np.zeros(len(teams))
        for j in range(k):
            res = simulate(SimInputs(teams, st, _random_schedule(teams, per_team, rng), rating, unc, rates, noise),
                           sims=SIMS // k, seed=eid * 31 + j)
            probs += res.rank_probs / k
            mean += res.mean_rank / k
    caps = captain_count(len(teams))
    p_cap = probs[:, :caps].sum(axis=1)
    return {"captains": caps, "teams": {str(t): {"mean_rank": _r(mean[i], 2), "p_captain": _r(p_cap[i], 3),
                                                "p_first": _r(probs[i, 0], 3)} for i, t in enumerate(teams)},
            "rates": {str(t): {"awp": _r(rates.awp.get(t, rates.awp_default), 3),
                               "auton": _r(rates.ap_share.get(t, 0.5), 3)} for t in teams}}


def _merge(sims: list[tuple[int, dict]]) -> dict | None:
    """One forecast object for the event: each division is simulated on its
    own (divisions rank and pick alliances separately), then merged with every
    team tagged by division and the captain count kept per division."""
    if not sims:
        return None
    out = {"captains": sims[0][1]["captains"] if len(sims) == 1 else None,
           "by_div": {str(d): s["captains"] for d, s in sims}, "teams": {}, "rates": {}}
    for d, s in sims:
        for t, v in s["teams"].items():
            out["teams"][t] = {**v, "div": d}
        out["rates"].update(s["rates"])
    return out


def _qual_groups(ms: list[Match], pend) -> dict[int, list]:
    groups: dict[int, list] = defaultdict(list)
    for m in ms:
        if m.is_qual:
            groups[m.division_id].append(m)
    for p in pend:
        groups[p.division_id].append(p)
    return groups


def publish(season: Season, slug: str, out: Path | None = None, now_ts: float | None = None,
            tune_from: str | None = None) -> Path:
    out = (out or SITE_DATA) / slug
    model, model_info = build_model(season, slug, tune_from)
    u0 = _sim_settings(slug, tune_from)
    model.reset(season)

    by_event: dict[int, list[Match]] = defaultdict(list)
    for m in season.matches:
        by_event[m.event_id].append(m)
    first_qual = {}
    for eid, ms in by_event.items():
        q = [m for m in ms if m.is_qual]
        if q:
            first_qual[q[0].idx] = eid

    played_n: dict[int, int] = defaultdict(int)
    preds: dict[int, dict] = {}
    pre_event: dict[int, dict] = {}
    pairs = []
    history: dict[int, list] = defaultdict(list)
    snaps = {}
    for m in season.matches:
        if m.idx in first_qual:
            eid = first_qual[m.idx]
            if hasattr(model, "feed"):
                model.feed.advance(m.ts)
            teams = sorted({t for x in by_event[eid] if x.is_qual for t in x.teams})
            rating = {t: (model.e[t] if t in model.e else model._initial(t, m)) for t in teams}
            snaps[eid] = (teams, rating, {t: played_n[t] for t in teams}, model.scale.std, m.ts)
        p = model.predict(m)
        preds[m.idx] = {"p": p.p_red, "r": p.red, "b": p.blue}
        pairs.append((p.red, m.red_score))
        pairs.append((p.blue, m.blue_score))
        model.update(m)
        for t in m.teams:
            played_n[t] += 1
    noise = fit_score_noise(pairs)

    # rating history: replay cheaply by recording ratings at the end of each event
    model2, _ = build_model(season, slug, tune_from)
    model2.reset(season)
    ends: dict[int, int] = {}
    for m in season.matches:
        ends[m.event_id] = m.idx
    end_idx = defaultdict(list)
    for eid, idx in ends.items():
        end_idx[idx].append(eid)
    for m in season.matches:
        model2.predict(m)
        model2.update(m)
        for eid in end_idx.get(m.idx, []):
            for t in {t for x in by_event[eid] for t in x.teams}:
                history[t].append({"event": eid, "date": _iso(season.events[eid].start),
                                   "rating": _r(model2.e.get(t))})

    for eid, (teams, rating, pn, std, ts) in snaps.items():
        # The qualification schedule is published when quals start, so the
        # "before the first match" forecast can use the real schedule.
        sims = []
        for did, group in sorted(_qual_groups(by_event[eid], season.pending.get(eid, [])).items()):
            dteams = sorted({t for x in group for t in x.teams})
            if len(dteams) < 4:
                continue
            sims.append((did, run_sim(season, dteams, rating, pn, std, noise, u0, ts, eid * 100 + did, played=[],
                                      remaining=[(x.red, x.blue) for x in group])))
        pre_event[eid] = _merge(sims)

    now_ts = now_ts if now_ts is not None else dt.datetime.now(dt.timezone.utc).timestamp()
    current = dict(model.e)

    def rating_now(t: int) -> float:
        return current[t] if t in current else model._initial(t, season.matches[-1]) if season.matches else 0.0

    # --- events -----------------------------------------------------------
    index = []
    for eid, ev in sorted(season.events.items(), key=lambda kv: kv[1].start):
        ms = by_event.get(eid, [])
        pend = season.pending.get(eid, [])
        teams = sorted(set(season.event_teams.get(eid, [])) | {t for m in ms for t in m.teams}
                       | {t for p in pend for t in p.teams})
        hs = [t for t in teams if season.teams.get(t) and season.teams[t].is_hs]
        if not hs:
            continue
        status = "done" if ms and not pend and ev.end < now_ts else ("live" if ms or pend else "upcoming")
        if ev.start > now_ts:
            status = "upcoming"
        if not ms and not pend and ev.end < now_ts:
            status = "skills-only" if any(s.event_id == eid for s in season.skills) else "no-results"
        rec = {"id": eid, "sku": ev.sku, "name": ev.name, "date": _iso(ev.start), "status": status,
               "worlds": ev.is_worlds, "teams": [], "matches": [], "pending": []}
        ranks = season.rankings.get(eid, {})
        # each team's division: from the rankings, else from its qualification matches
        div_of = {t: r.division_id for t, r in ranks.items() if r.division_id}
        for x in [m for m in ms if m.is_qual] + list(pend):
            for t in x.teams:
                div_of.setdefault(t, x.division_id)
        used = sorted(set(div_of.values()) | {m.division_id for m in ms})
        if len(used) > 1:
            names = dict(ev.divisions)
            qual_divs = set(div_of.values())
            rec["divisions"] = [{"id": d, "name": names.get(d, f"Division {d}"), **({} if d in qual_divs else {"finals": True})}
                                for d in used]
        skills_best = {}
        for s in season.skills:
            if s.event_id == eid:
                skills_best[s.team_id] = s.combined
        for t in teams:
            tm = season.teams.get(t)
            r = ranks.get(t)
            rec["teams"].append({
                "id": t, "number": tm.number if tm else str(t), "name": tm.name if tm else "",
                "hs": bool(tm and tm.is_hs), "div": div_of.get(t),
                "rating_pre": _r(snaps[eid][1].get(t)) if eid in snaps else None,
                "rating_now": _r(rating_now(t)),
                "skills": skills_best.get(t),
                "rank": r.rank if r else None,
                "record": f"{r.wins}-{r.losses}-{r.ties}" if r else None,
                "wp": r.wp if r else None, "ap": r.ap if r else None, "sp": r.sp if r else None,
            })
        for m in ms:
            p = preds[m.idx]
            rec["matches"].append({"round": m.round, "inst": m.instance, "num": m.matchnum, "div": m.division_id,
                                   "red": list(m.red), "blue": list(m.blue), "rs": m.red_score, "bs": m.blue_score,
                                   "p": _r(p["p"], 3), "pr": _r(p["r"]), "pb": _r(p["b"])})
        if pre_event.get(eid):
            rec["sim_pre"] = pre_event[eid]
        if pend:
            pend_rating = {t: rating_now(t) for t in teams}
            for p in pend:
                r_ = sum(pend_rating[t] for t in p.red)
                b_ = sum(pend_rating[t] for t in p.blue)
                pr = 1 / (1 + math.exp(-(r_ - b_) / (model.prob_k * model.scale.std)))
                rec["pending"].append({"num": p.matchnum, "div": p.division_id, "red": list(p.red), "blue": list(p.blue),
                                       "p": _r(pr, 3), "pr": _r(r_), "pb": _r(b_)})
            live = []
            for did, group in sorted(_qual_groups(ms, pend).items()):
                dpend = [x for x in group if not isinstance(x, Match)]
                if not dpend:          # this division's quals are over
                    continue
                dplayed = [x for x in group if isinstance(x, Match)]
                qual_teams = sorted({t for x in group for t in x.teams})
                dranks = {t: r for t, r in ranks.items() if r.division_id in (did, 0)}
                live.append((did, run_sim(season, qual_teams, pend_rating, played_n, model.scale.std, noise, u0,
                                          now_ts, eid * 100 + did, played=dplayed,
                                          remaining=[(p.red, p.blue) for p in dpend], live_rankings=dranks or None)))
            if live:
                rec["sim_live"] = _merge(live)
        elif status == "upcoming" and len(ev.divisions) > 1:
            rec["divisions_pending"] = True   # teams aren't split into divisions until the schedule is out
        elif status == "upcoming" and len(teams) >= 8:
            rec["sim_pre"] = _merge([(0, run_sim(season, teams, {t: rating_now(t) for t in teams}, played_n,
                                                 model.scale.std, noise, u0, now_ts, eid, played=[]))])
        _write(out / "events" / f"{eid}.json", rec)
        index.append({"id": eid, "sku": ev.sku, "name": ev.name, "date": _iso(ev.start), "status": status,
                      "teams": len(teams), "hs_teams": len(hs), "matches": len(ms), "worlds": ev.is_worlds})

    # --- leaderboard + team pages ------------------------------------------
    hs_rated = [(t, v) for t, v in current.items() if season.teams.get(t) and season.teams[t].is_hs and played_n[t] > 0]
    hs_rated.sort(key=lambda kv: -kv[1])
    best_skills: dict[int, int] = {}
    for s in season.skills:
        best_skills[s.team_id] = max(best_skills.get(s.team_id, 0), s.combined)
    record = defaultdict(lambda: [0, 0, 0])
    for m in season.matches:
        o = m.outcome
        for side, win in ((m.red, o), (m.blue, 1 - o)):
            for t in side:
                record[t][0 if win == 1 else (2 if win == 0.5 else 1)] += 1
    board = []
    for rank, (t, v) in enumerate(hs_rated, 1):
        tm = season.teams[t]
        w, l, ti = record[t]
        board.append({"rank": rank, "id": t, "number": tm.number, "name": tm.name, "region": tm.region,
                      "country": tm.country, "rating": _r(v), "matches": played_n[t], "record": f"{w}-{l}-{ti}",
                      "skills": best_skills.get(t)})
    _write(out / "leaderboard.json", board)

    team_matches: dict[int, list] = defaultdict(list)
    for m in season.matches:
        p = preds[m.idx]
        for side, other, sc, osc, pw in ((m.red, m.blue, m.red_score, m.blue_score, p["p"]),
                                         (m.blue, m.red, m.blue_score, m.red_score, 1 - p["p"])):
            for t in side:
                team_matches[t].append({"event": m.event_id, "round": m.round, "num": m.matchnum,
                                        "inst": m.instance, "partner": [x for x in side if x != t], "opp": list(other),
                                        "score": sc, "opp_score": osc, "p_win": _r(pw, 3)})
    rank_of = {b["id"]: b["rank"] for b in board}
    for t in {b["id"] for b in board}:
        tm = season.teams[t]
        _write(out / "teams" / f"{t}.json", {
            "id": t, "number": tm.number, "name": tm.name, "region": tm.region, "country": tm.country,
            "rating": _r(current.get(t)), "rank": rank_of.get(t), "skills": best_skills.get(t),
            "history": history.get(t, []), "matches": team_matches.get(t, []),
            "events": sorted({x["event"] for x in team_matches.get(t, [])},
                             key=lambda e: season.events[e].start)})
    names = {str(t): season.teams[t].number for t in season.teams}
    _write(out / "team_numbers.json", names)

    acc = {}
    for name in ("metrics.json", "simcheck.json"):
        for src in (slug, tune_from):
            p = REPORTS_DIR / src / name if src else None
            if p and p.exists():
                acc[name.split(".")[0]] = json.loads(p.read_text())
                acc.setdefault("from_season", {})[name.split(".")[0]] = src
                break
    _write(out / "accuracy.json", acc)

    meta = {"season": season.name, "slug": slug, "synthetic": season.synthetic,
            "generated": dt.datetime.now(dt.timezone.utc).isoformat(timespec="minutes"),
            "model": {"name": model.name, **model_info, "score_noise": [noise.c0, noise.c1], "u0": u0,
                      "score_std": model.scale.std, "prob_k": model.prob_k},
            "teams_rated": len(board), "events": sorted(index, key=lambda e: e["date"], reverse=True)}
    _write(out / "meta.json", meta)
    seasons_path = (out.parent / "seasons.json")
    seasons = json.loads(seasons_path.read_text()) if seasons_path.exists() else []
    seasons = [s for s in seasons if s["slug"] != slug] + [{"slug": slug, "name": season.name,
                                                             "synthetic": season.synthetic}]
    _write(seasons_path, seasons)
    return out


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--season", default="Push Back")
    ap.add_argument("--tune-from", default=None,
                    help="reuse another season's backtest settings, e.g. --tune-from 'Push Back'")
    args = ap.parse_args(argv)
    slug = slugify(args.season)
    out = publish(load_season(slug), slug, tune_from=slugify(args.tune_from) if args.tune_from else None)
    print("Published to", out)


if __name__ == "__main__":
    main()
