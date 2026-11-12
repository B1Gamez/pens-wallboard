"""
Pens Wallboard - live Penguins scoreboard during games,
league scores, standings, leaders and news the rest of the time.

Run:   python app.py                       (real data)
       DEMO=live         python app.py     (fake live Pens game, goals happen randomly)
       DEMO=intermission python app.py     (fake intermission summary)
       DEMO=final        python app.py     (fake post-game with three stars)
       DEMO=off          python app.py     (fake off-day screen)
       DEMO=gameday      python app.py     (fake game-day screen)
       DEMO=affiliate    python app.py     (fake WBS and Everblades games live, no Pens game)
       DEMO=echl         python app.py     (fake Everblades game live on its own)
       DEMO=playoffs     python app.py     (fake playoff game and bracket)
       DEMO=offseason    python app.py     (fake summer: countdowns, prospects, history)
Then open http://localhost:8080
(On Windows Command Prompt: `set DEMO=live` then `python app.py`; `set DEMO=` to go back to real data.)
"""
import copy
import ipaddress
import json
import os
from collections import deque
import random
import subprocess
import threading
import time
import logging
import re
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from datetime import datetime, timezone, timedelta
from urllib.parse import quote_plus

import requests
from flask import Flask, jsonify, request, send_from_directory

from affiliates import Affiliate
from extras import Extras

# ---------- settings (override with environment variables) ----------
TEAM = os.environ.get("TEAM", "PIT")
PORT = int(os.environ.get("PORT", "8080"))
POSTGAME_MINUTES = int(os.environ.get("POSTGAME_MINUTES", "30"))   # keep the final up this long
PREGAME_MINUTES = int(os.environ.get("PREGAME_MINUTES", "90"))     # switch to scoreboard this early
RECAP_UNTIL_HOUR = int(os.environ.get("RECAP_UNTIL_HOUR", "12"))   # show "Last night" until this local hour
GOAL_HOOK_CMD = os.environ.get("GOAL_HOOK_CMD")    # shell command to run on a goal
GOAL_HOOK_URL = os.environ.get("GOAL_HOOK_URL")    # URL to POST to on a goal (e.g. Home Assistant webhook)
NEWS = os.environ.get("NEWS", "on").lower() != "off"
NEWS_QUERY = os.environ.get("NEWS_QUERY", "Pittsburgh Penguins")
NEWS_MAX_HOURS = int(os.environ.get("NEWS_MAX_HOURS", "48"))       # skip headlines older than this
NIGHT = os.environ.get("NIGHT", "on").lower() != "off"            # dim to a clock overnight
NIGHT_START = int(os.environ.get("NIGHT_START", "1"))              # local hour night mode begins
NIGHT_END = int(os.environ.get("NIGHT_END", "8"))                  # local hour night mode ends
GOAL_HORN = os.environ.get("GOAL_HORN", "on").lower() != "off"     # play a horn on goals
HORN_VOLUME = float(os.environ.get("HORN_VOLUME", "0.6"))          # 0.0 to 1.0
HORN_MAX_SECONDS = int(os.environ.get("HORN_MAX_SECONDS", "0"))   # cut a long horn/song short (0 = play it all)
# Minor-league affiliates as league:name pairs (name is matched against the league's team list).
AFFILIATES = os.environ.get("AFFILIATES", "ahl:Wilkes-Barre,echl:Florida Everblades")
AFFILIATE_TAKEOVER = os.environ.get("AFFILIATE_TAKEOVER", "on").lower() != "off"  # live affiliate game fills the screen when the Pens aren't playing
AFFILIATE_HORN = os.environ.get("AFFILIATE_HORN", "on").lower() != "off"
AFFILIATE_HORN_VOLUME = float(os.environ.get("AFFILIATE_HORN_VOLUME", str(HORN_VOLUME)))
AFFILIATE_HOOKS = os.environ.get("AFFILIATE_HOOKS", "off").lower() != "off"     # also fire goal hooks for affiliate goals
AFFILIATE_NEWS = os.environ.get("AFFILIATE_NEWS", "on").lower() != "off"
ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "")
STREAM_DELAY = int(os.environ.get("STREAM_DELAY", "0"))   # seconds to hold everything back, to match your TV/stream
MAX_DELAY = 300   # lets you trigger test goals from outside your home network
DEMO = os.environ.get("DEMO", "").lower()

API = "https://api-web.nhle.com/v1"
LIVE_STATES = {"LIVE", "CRIT"}
DONE_STATES = {"FINAL", "OFF"}

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("wallboard")

app = Flask(__name__, static_folder="static")
session = requests.Session()
session.headers["User-Agent"] = "pens-wallboard/1.2"

lock = threading.Lock()
state = {
    "team": TEAM, "mode": "off", "game": None, "details": None, "scores": [], "last_night": [],
    "standings": [], "leaders": None, "league_leaders": None, "form": [], "upcoming": [],
    "news": [], "opponent": None, "milestones": [], "affiliates": [],
    "aff_goal_seq": 0, "aff_goal": None,
    "playoffs": None, "injuries": [], "opp_injuries": [], "transactions": [], "prospects": [],
    "on_this_day": [], "offseason": None, "lineup": None, "goal_seq": 0, "goal_info": None, "updated": None, "error": None,
}


# ---------- helpers ----------
def get(path):
    r = session.get(f"{API}{path}", timeout=10)  # requests follows the API's 307 redirects
    r.raise_for_status()
    return r.json()


def text(v):
    """NHL names come as {"default": "Penguins"}; accept plain strings too."""
    if isinstance(v, dict):
        return v.get("default", "")
    return v or ""


def parse_time(s):
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except (AttributeError, ValueError):
        return None


def mmss(s):
    try:
        m, sec = str(s).split(":")
        return int(m) * 60 + int(sec)
    except ValueError:
        return 0


def ordinal(n):
    return f"{n}{'th' if 10 <= n % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"


def period_label(pd):
    pd = pd or {}
    n, kind = pd.get("number") or 0, pd.get("periodType")
    if kind == "SO":
        return "SO"
    if kind == "OT" or n > 3:
        k = max(1, n - 3)
        return "OT" if k == 1 else f"{k}OT"
    return ordinal(n)


def full_name(p):
    return f"{text(p.get('firstName'))} {text(p.get('lastName'))}".strip() or text(p.get("name"))


def last_name(p):
    return text(p.get("lastName")) or text(p.get("name"))


def slim_side(t):
    t = t or {}
    return {
        "abbrev": t.get("abbrev"),
        "name": text(t.get("commonName")) or text(t.get("name")) or t.get("abbrev"),
        "score": t.get("score"),
        "sog": t.get("sog"),
        "logo": t.get("darkLogo") or t.get("logo"),
    }


def situation(g):
    """Return e.g. {"pp": "PIT", "en": None, "time": "1:23"} or None."""
    s = g.get("situation") or {}
    if not s:
        return None
    out = {"pp": None, "en": None, "time": s.get("timeRemaining")}
    for key in ("homeTeam", "awayTeam"):
        side = s.get(key) or {}
        descs = side.get("situationDescriptions") or []
        if "PP" in descs:
            out["pp"] = side.get("abbrev")
        if "EN" in descs:
            out["en"] = side.get("abbrev")
    return out if (out["pp"] or out["en"]) else None


def slim_game(g):
    clock = g.get("clock") or {}
    pd = g.get("periodDescriptor") or {}
    return {
        "id": g.get("id"),
        "gameType": g.get("gameType"),
        "state": g.get("gameState"),
        "start": g.get("startTimeUTC"),
        "away": slim_side(g.get("awayTeam")),
        "home": slim_side(g.get("homeTeam")),
        "period": pd.get("number") or g.get("period"),
        "periodType": pd.get("periodType"),          # REG / OT / SO
        "clock": clock.get("timeRemaining"),
        "running": bool(clock.get("running")),
        "intermission": bool(clock.get("inIntermission")),
        "situation": situation(g),
        "lastPeriodType": (g.get("gameOutcome") or {}).get("lastPeriodType"),
        "series": slim_status(g.get("seriesStatus")),
        "tv": [{"network": b.get("network"), "market": b.get("market"), "country": b.get("countryCode")}
               for b in (g.get("tvBroadcasts") or [])],
    }


def slim_status(st):
    """Playoff series status on a game, e.g. {'text': 'PIT leads 2-1', 'game': 4, 'round': 1}."""
    if not st:
        return None
    top, bot = st.get("topSeedTeamAbbrev"), st.get("bottomSeedTeamAbbrev")
    tw, bw = st.get("topSeedWins"), st.get("bottomSeedWins")
    from extras import series_text
    return {"text": series_text(None, top, tw, bot, bw, st.get("neededToWin") or 4),
            "game": st.get("gameNumberOfSeries"), "round": st.get("round"),
            "title": st.get("seriesTitle") or ""}


def slim_team(t):
    return {
        "abbrev": text(t.get("teamAbbrev")),
        "name": text(t.get("teamCommonName")) or text(t.get("teamName")),
        "logo": t.get("teamLogo"),
        "division": t.get("divisionName"),
        "conference": t.get("conferenceName"),
        "divSeq": t.get("divisionSequence"),
        "wcSeq": t.get("wildcardSequence"),
        "gp": t.get("gamesPlayed"), "w": t.get("wins"), "l": t.get("losses"),
        "otl": t.get("otLosses"), "pts": t.get("points"),
        "streak": f"{t.get('streakCode', '')}{t.get('streakCount', '')}",
        "l10": f"{t.get('l10Wins', 0)}-{t.get('l10Losses', 0)}-{t.get('l10OtLosses', 0)}",
    }


def slim_leaders(data):
    skaters = sorted(data.get("skaters") or [],
                     key=lambda p: (p.get("points", 0), p.get("goals", 0)), reverse=True)[:5]
    goalies = sorted(data.get("goalies") or [],
                     key=lambda p: p.get("gamesStarted", p.get("gamesPlayed", 0)), reverse=True)[:2]
    return {
        "skaters": [{"name": full_name(p), "pos": p.get("positionCode"), "headshot": p.get("headshot"),
                     "gp": p.get("gamesPlayed"), "g": p.get("goals"), "a": p.get("assists"),
                     "pts": p.get("points")} for p in skaters],
        "goalies": [{"name": full_name(p), "headshot": p.get("headshot"), "gp": p.get("gamesPlayed"),
                     "w": p.get("wins"), "l": p.get("losses"), "otl": p.get("overtimeLosses"),
                     "svp": p.get("savePercentage"), "gaa": p.get("goalsAgainstAverage")} for p in goalies],
    }


def slim_league_leaders(sk, gl):
    def rows(lst, n):
        return [{"name": full_name(p), "team": text(p.get("teamAbbrev")), "headshot": p.get("headshot"),
                 "value": p.get("value")} for p in (lst or [])[:n]]
    return {"points": rows(sk.get("points"), 4), "goals": rows(sk.get("goals"), 3),
            "wins": rows(gl.get("wins"), 3)}


def result_of(s):
    """A finished schedule game as {r: W/L/OTL, opp, us, them, start}, or None."""
    if s.get("gameType") not in (2, 3) or s.get("gameState") not in DONE_STATES:
        return None
    away, home = s.get("awayTeam") or {}, s.get("homeTeam") or {}
    us, them = (home, away) if home.get("abbrev") == TEAM else (away, home)
    if us.get("score") is None or them.get("score") is None:
        return None
    if us["score"] > them["score"]:
        r = "W"
    elif (s.get("gameOutcome") or {}).get("lastPeriodType") in ("OT", "SO"):
        r = "OTL"
    else:
        r = "L"
    return {"r": r, "opp": them.get("abbrev"), "us": us["score"], "them": them["score"],
            "start": s.get("startTimeUTC")}


def team_form(schedule, n=10):
    """Last n regular-season/playoff results, oldest first."""
    return [x for x in (result_of(s) for s in schedule) if x][-n:]


def scoring_goals(landing):
    out = []
    for per in (landing.get("summary") or {}).get("scoring") or []:
        label = period_label(per.get("periodDescriptor"))
        num = (per.get("periodDescriptor") or {}).get("number") or 0
        for gl in per.get("goals") or []:
            out.append({
                "period": label, "num": num, "time": gl.get("timeInPeriod"),
                "team": text(gl.get("teamAbbrev")),
                "scorer": last_name(gl), "full": full_name(gl), "total": gl.get("goalsToDate"),
                "headshot": gl.get("headshot"),
                "assists": [{"name": last_name(a), "num": a.get("assistsToDate")} for a in gl.get("assists") or []],
                "strength": (gl.get("strength") or "").lower(),
                "en": (gl.get("goalModifier") or "") == "empty-net",
                "away": gl.get("awayScore"), "home": gl.get("homeScore"),
            })
    return out


def latest_goal(goals):
    ours = [g for g in goals if g["team"] == TEAM]
    if not ours:
        return None
    g = ours[-1]
    return {"count": len(ours), "name": g["full"], "num": g["total"], "headshot": g["headshot"],
            "strength": g["strength"], "assists": g["assists"]}


def game_seconds(num, kind, game_type, remaining_in_period):
    """Seconds elapsed in the game at a point in period `num`."""
    def plen(n):
        return 300 if (n > 3 and game_type != 3) else 1200
    before = sum(plen(n) for n in range(1, num))
    return before + (plen(num) - remaining_in_period)


def active_penalties(landing, game, goals):
    """Penalties still being served, with time left, from the scoring/penalty summary."""
    if not game.get("clock") or game.get("intermission") or game["state"] not in LIVE_STATES:
        return []
    gt = game.get("gameType") or 2
    now = game_seconds(game.get("period") or 1, game.get("periodType"), gt, mmss(game["clock"]))
    plen = lambda n: 300 if (n > 3 and gt != 3) else 1200
    goal_times = [(game_seconds(g["num"], None, gt, plen(g["num"]) - mmss(g["time"])), g)
                  for g in goals if g["num"]]
    out = []
    for per in (landing.get("summary") or {}).get("penalties") or []:
        num = (per.get("periodDescriptor") or {}).get("number") or 0
        for p in per.get("penalties") or []:
            kind = (p.get("type") or "").upper()
            if kind not in ("MIN", "MAJ", "BEN"):
                continue
            start = game_seconds(num, None, gt, plen(num) - mmss(p.get("timeInPeriod")))
            end = start + (p.get("duration") or 2) * 60
            team = text(p.get("teamAbbrev"))
            if kind in ("MIN", "BEN") and (p.get("duration") or 2) == 2:
                # A power-play goal against ends a minor early.
                for t, g in goal_times:
                    if start < t <= end and g["team"] != team and g["strength"] == "pp":
                        end = t
                        break
            if start <= now < end:
                who = p.get("committedByPlayer") or p.get("servedBy") or ""
                if isinstance(who, dict):
                    who = text(who.get("lastName")) or text(who)
                left = end - now
                out.append({"team": team, "player": who or "Bench",
                            "infraction": (p.get("descKey") or "").replace("-", " ").capitalize(),
                            "left": f"{left // 60}:{left % 60:02d}"})
    return out


def slim_lineups(box):
    """Everyone who dressed, with their numbers for this game (NHL boxscore)."""
    pbs = box.get("playerByGameStats") or {}
    out = {}
    for side, key in (("away", "awayTeam"), ("home", "homeTeam")):
        t = pbs.get(key) or {}
        skaters = []
        for grp, pos in (("forwards", "F"), ("defense", "D")):
            for p in t.get(grp) or []:
                g, a = p.get("goals") or 0, p.get("assists") or 0
                skaters.append({"num": p.get("sweaterNumber"), "name": text(p.get("name")), "pos": p.get("position") or pos,
                                "group": pos, "g": g, "a": a, "pts": p.get("points", g + a), "sog": p.get("sog"),
                                "pm": p.get("plusMinus"), "toi": p.get("toi")})
        goalies = [{"num": p.get("sweaterNumber"), "name": text(p.get("name")), "sa": p.get("saveShotsAgainst"),
                    "svp": p.get("savePctg"), "toi": p.get("toi"), "starter": p.get("starter"),
                    "ga": p.get("goalsAgainst")} for p in t.get("goalies") or []]
        if skaters or goalies:
            out[side] = {"skaters": skaters, "goalies": goalies}
    return out or None


def build_details(landing, rr, game):
    def rows(items):
        return [{"label": period_label(x.get("periodDescriptor")), "away": x.get("away"), "home": x.get("home")}
                for x in items or []]
    ls = rr.get("linescore") or {}
    stats = {s.get("category"): (s.get("awayValue"), s.get("homeValue")) for s in rr.get("teamGameStats") or []}
    order = [("sog", "Shots"), ("powerPlay", "Power play"), ("faceoffWinningPctg", "Faceoffs"),
             ("hits", "Hits"), ("blockedShots", "Blocked shots"), ("pim", "Penalty minutes")]
    goals = scoring_goals(landing)
    stars = []
    for s in (landing.get("summary") or {}).get("threeStars") or []:
        line = []
        if s.get("goals") is not None or s.get("assists") is not None:
            line = [f"{s.get('goals', 0)}G {s.get('assists', 0)}A"]
        if s.get("savePctg") is not None:
            line = [f"{s['savePctg']:.3f} SV%".lstrip("0")]
        stars.append({"star": s.get("star"), "name": text(s.get("name")) or full_name(s),
                      "team": text(s.get("teamAbbrev")), "headshot": s.get("headshot"),
                      "pos": s.get("position"), "line": " ".join(line)})
    return {
        "periods": rows(ls.get("byPeriod")),
        "totals": ls.get("totals"),
        "shots": rows(rr.get("shotsByPeriod")),
        "stats": [{"key": k, "label": lbl, "away": stats[k][0], "home": stats[k][1]} for k, lbl in order if k in stats],
        "goals": goals,
        "stars": sorted(stars, key=lambda s: s["star"] or 9),
        "penalties": active_penalties(landing, game, goals),
    }, goals


PREVIEW_WORDS = re.compile(r"\b(preview|how to watch|predictions?|odds|betting|picks?|projected lines|lineup|game ?day|keys to)\b", re.I)
STOP = {"the", "a", "an", "and", "of", "to", "in", "on", "for", "vs", "at", "with", "penguins", "pittsburgh", "pens", "nhl"}


def words(title):
    return {w for w in re.findall(r"[a-z0-9]+", title.lower()) if w not in STOP}


def fetch_news(last_game_start=None, query=NEWS_QUERY):
    """Recent headlines: newest first, no stale game previews, no near-duplicates."""
    url = f"https://news.google.com/rss/search?q={quote_plus(query)}&hl=en-US&gl=US&ceid=US:en"
    r = session.get(url, timeout=10)
    r.raise_for_status()
    now = datetime.now(timezone.utc)
    last_end = last_game_start + timedelta(hours=3) if last_game_start else None
    candidates = []
    for it in ET.fromstring(r.content).iter("item"):
        title = (it.findtext("title") or "").strip()
        headline, source = title.rsplit(" - ", 1) if " - " in title else (title, "")
        try:
            published = parsedate_to_datetime(it.findtext("pubDate") or "")
        except (TypeError, ValueError):
            published = None
        if not headline or not published:
            continue
        if now - published > timedelta(hours=NEWS_MAX_HOURS):
            continue
        # A preview written before the last game ended is about a game that's already been played.
        if PREVIEW_WORDS.search(headline) and last_end and published < last_end:
            continue
        candidates.append((published, headline, source))
    items, seen = [], []
    for published, headline, source in sorted(candidates, reverse=True):
        w = words(headline)
        if any(len(w & s) / max(1, len(w | s)) > 0.5 for s in seen):
            continue                     # same story from another outlet
        seen.append(w)
        items.append({"title": headline, "source": source})
        if len(items) >= 12:
            break
    return items


MILESTONE_RULES = {  # stat: (round number step, how close counts as "watch")
    "points": (100, 10), "goals": (50, 5), "assists": (100, 10), "gamesPlayed": (100, 10), "wins": (50, 5),
}
MILESTONE_LABELS = {"points": "points", "goals": "goals", "assists": "assists", "gamesPlayed": "games", "wins": "wins"}


def find_milestones(players):
    """players: list of (club-stats entry, is_goalie). Looks up career totals for each."""
    out = []
    for p, is_goalie in players:
        pid = p.get("playerId")
        if not pid:
            continue
        try:
            land = get(f"/player/{pid}/landing")
        except Exception as e:
            log.warning("player %s lookup failed: %s", pid, e)
            continue
        totals = (land.get("careerTotals") or {}).get("regularSeason") or {}
        keys = ["wins", "gamesPlayed"] if is_goalie else ["points", "goals", "assists", "gamesPlayed"]
        for key in keys:
            v = totals.get(key)
            if not isinstance(v, int) or v <= 0:
                continue
            step, near = MILESTONE_RULES[key]
            target = (v // step + 1) * step
            left = target - v
            if left <= near:
                out.append({"name": full_name(land) or full_name(p), "headshot": land.get("headshot") or p.get("headshot"),
                            "stat": MILESTONE_LABELS[key], "value": v, "target": target, "left": left,
                            "score": left / near})
        time.sleep(0.2)   # be gentle with the API
    return sorted(out, key=lambda m: m["score"])[:4]


def has_team(g):
    return TEAM in (g["away"]["abbrev"], g["home"]["abbrev"])


# ---------- stream delay ----------
SETTINGS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "settings.json")
history = deque(maxlen=MAX_DELAY // 2 + 10)      # (time, snapshot of state) every 2 seconds


def load_delay():
    try:
        with open(SETTINGS_FILE) as f:
            return max(0, min(MAX_DELAY, int(json.load(f).get("delay", STREAM_DELAY))))
    except (OSError, ValueError, TypeError):
        return STREAM_DELAY


current_delay = load_delay()


def save_delay(seconds):
    global current_delay
    current_delay = max(0, min(MAX_DELAY, int(seconds)))
    os.makedirs(os.path.dirname(SETTINGS_FILE), exist_ok=True)
    with open(SETTINGS_FILE, "w") as f:
        json.dump({"delay": current_delay}, f)


def record_history():
    """Keep the last few minutes of state so the page can be shown on a delay."""
    while True:
        with lock:
            snap = copy.deepcopy(state)
        history.append((time.time(), snap))
        time.sleep(2)


def snapshot(delay):
    if delay <= 0 or not history:
        return None
    cutoff = time.time() - delay
    older = [s for t, s in history if t <= cutoff]
    return older[-1] if older else history[0][1]


def fire_goal_hooks_later(team=None):
    """Goal lights etc. wait out the stream delay too, so they go off when you see the goal."""
    args = (team,) if team else ()
    threading.Timer(current_delay, fire_goal_hooks, args=args).start()


# ---------- goal hook ----------
def fire_goal_hooks(team=TEAM):
    if GOAL_HOOK_CMD:
        subprocess.Popen(GOAL_HOOK_CMD, shell=True, env={**os.environ, "GOAL_TEAM": str(team)})
    if GOAL_HOOK_URL:
        try:
            session.post(GOAL_HOOK_URL, json={"team": team}, timeout=5)
        except requests.RequestException as e:
            log.warning("goal webhook failed: %s", e)


# ---------- the poller ----------
class Poller:
    def __init__(self):
        self.last_score = {}        # game id -> our team's score
        self.final_seen = {}        # game id -> when the game ended
        self.saw_live = set()       # game ids we watched while live
        self.next = {k: 0 for k in ("schedule", "standings", "leaders", "league", "recap", "news",
                                    "opponent", "milestones")}
        self.schedule = []
        self.affiliates = []
        self.extras = None
        for pair in filter(None, (p.strip() for p in AFFILIATES.split(","))):
            league, _, needle = pair.partition(":")
            if league and needle:
                key = os.environ.get(f"HT_KEY_{league.strip().upper()}")
                self.affiliates.append(Affiliate(session, league.strip(), needle.strip(), key))
                self.affiliates[-1].postgame_minutes = POSTGAME_MINUTES

    def update_affiliates(self):
        summaries = []
        for a in self.affiliates:
            try:
                for ev in a.update(time.time()):
                    log.info("%s goal: %s", a.label, ev)
                    with lock:
                        state["aff_goal_seq"] += 1
                        state["aff_goal"] = ev
                    if AFFILIATE_HOOKS:
                        fire_goal_hooks_later(ev["team"])
                s = a.summary()
                if s:
                    summaries.append(s)
            except Exception as e:
                log.warning("%s update failed: %s", a.label, e)
        with lock:
            state["affiliates"] = summaries
        return any(s["live"] for s in summaries)

    def due(self, key, every_minutes):
        now = time.time()
        if now >= self.next[key]:
            self.next[key] = now + every_minutes * 60
            return True
        return False

    def safely(self, label, fn):
        """Side data shouldn't take the whole board down if one endpoint fails."""
        try:
            fn()
        except Exception as e:
            log.warning("%s update failed: %s", label, e)

    def team_score(self, g):
        side = g["home"] if g["home"]["abbrev"] == TEAM else g["away"]
        return side["score"]

    def check_goal(self, g):
        score = self.team_score(g)
        if score is None:
            return
        prev = self.last_score.get(g["id"])
        self.last_score[g["id"]] = score
        # Only celebrate rises seen while live; ignore the first reading after startup.
        if prev is not None and score > prev and g["state"] in LIVE_STATES:
            log.info("GOAL %s! %s -> %s", TEAM, prev, score)
            with lock:
                state["goal_seq"] += 1
            fire_goal_hooks_later()

    def pick_mode(self, g):
        if not g:
            return "off"
        now = datetime.now(timezone.utc)
        if g["state"] in LIVE_STATES:
            self.saw_live.add(g["id"])
            return "live"
        if g["state"] in DONE_STATES:
            if g["id"] not in self.final_seen:
                start = parse_time(g["start"])
                if g["id"] in self.saw_live or not start:
                    ended = now                      # we watched it end
                else:
                    # App started after the game was over: estimate the end
                    # as ~3 hours after puck drop instead of "right now".
                    ended = min(now, start + timedelta(hours=3))
                self.final_seen[g["id"]] = ended
            if now - self.final_seen[g["id"]] < timedelta(minutes=POSTGAME_MINUTES):
                return "final"
            return "off"
        start = parse_time(g["start"])
        if start and start - now < timedelta(minutes=PREGAME_MINUTES):
            return "pregame"
        return "off"

    def side_data(self):
        def schedule():
            self.schedule = get(f"/club-schedule-season/{TEAM}/now").get("games", [])
            now_utc = datetime.now(timezone.utc)
            upcoming = [{"start": s.get("startTimeUTC"),
                         "away": (s.get("awayTeam") or {}).get("abbrev"),
                         "home": (s.get("homeTeam") or {}).get("abbrev")}
                        for s in self.schedule
                        if s.get("gameState") in ("FUT", "PRE")
                        and (parse_time(s.get("startTimeUTC")) or now_utc) > now_utc][:5]
            with lock:
                state["form"] = team_form(self.schedule)
                state["upcoming"] = upcoming

        def standings():
            teams = [slim_team(t) for t in get("/standings/now").get("standings", [])]
            with lock:
                state["standings"] = teams

        def leaders():
            data = slim_leaders(get(f"/club-stats/{TEAM}/now"))
            with lock:
                state["leaders"] = data

        def league():
            sk = get("/skater-stats-leaders/current?categories=points,goals&limit=5")
            gl = get("/goalie-stats-leaders/current?categories=wins&limit=3")
            with lock:
                state["league_leaders"] = slim_league_leaders(sk, gl)

        def news():
            done = [r for r in (result_of(s) for s in self.schedule) if r]
            last_start = parse_time(done[-1]["start"]) if done else None
            items = fetch_news(last_start)
            if AFFILIATE_NEWS:
                seen = [words(i["title"]) for i in items]
                for a in self.affiliates:
                    if not a.team:
                        continue
                    try:
                        extra = fetch_news(None, a.team.get("name") or a.needle)
                    except Exception as e:
                        log.warning("%s news failed: %s", a.label, e)
                        continue
                    added = 0
                    for i in extra:
                        w = words(i["title"])
                        if any(len(w & x) / max(1, len(w | x)) > 0.5 for x in seen):
                            continue
                        seen.append(w)
                        nick = a.team.get("nickname") or ""
                        tag = a.team.get("code") if nick.lower() in ("", "penguins") else nick
                        items.append({**i, "tag": tag})
                        added += 1
                        if added >= 3:
                            break
            with lock:
                state["news"] = items

        def recap():
            y = (datetime.now().date() - timedelta(days=1)).isoformat()
            games = [slim_game(g) for g in get(f"/score/{y}").get("games", [])]
            with lock:
                state["last_night"] = games

        if self.due("schedule", 30):
            self.safely("schedule", schedule)
        if self.due("standings", 10):
            self.safely("standings", standings)
        if self.due("leaders", 30):
            self.safely("team leaders", leaders)
        if self.due("league", 60):
            self.safely("league leaders", league)
        if NEWS and self.due("news", 20):
            self.safely("news", news)

        def opponent():
            today = datetime.now().date()
            game = None
            for s in self.schedule:
                t = parse_time(s.get("startTimeUTC"))
                if t and t.astimezone().date() == today and s.get("gameState") not in DONE_STATES:
                    game = s
                    break
            if not game:
                with lock:
                    state["opponent"] = None
                return
            away, home = (game.get("awayTeam") or {}).get("abbrev"), (game.get("homeTeam") or {}).get("abbrev")
            opp = home if away == TEAM else away
            h2h = [r for r in (result_of(s) for s in self.schedule) if r and r["opp"] == opp]
            data = get(f"/club-stats/{opp}/now")
            top = sorted(data.get("skaters") or [], key=lambda p: (p.get("points", 0), p.get("goals", 0)), reverse=True)[:3]
            with lock:
                state["opponent"] = {
                    "abbrev": opp, "start": game.get("startTimeUTC"), "h2h": h2h,
                    "scorers": [{"name": full_name(p), "headshot": p.get("headshot"), "g": p.get("goals"),
                                 "a": p.get("assists"), "pts": p.get("points")} for p in top]}

        def milestones():
            data = get(f"/club-stats/{TEAM}/now")
            players = [(p, False) for p in data.get("skaters") or []] + [(p, True) for p in data.get("goalies") or []]
            found = find_milestones(players)
            with lock:
                state["milestones"] = found

        if self.due("opponent", 30):
            self.safely("opponent preview", opponent)
        if self.due("milestones", 6 * 60):
            self.safely("milestones", milestones)

        # Morning recap: yesterday's results until RECAP_UNTIL_HOUR local time.
        if datetime.now().hour < RECAP_UNTIL_HOUR:
            if self.due("recap", 15):
                self.safely("recap", recap)
        else:
            self.next["recap"] = 0
            with lock:
                state["last_night"] = []

    def tick(self):
        self.affiliate_live = self.update_affiliates()
        self.side_data()

        scores = [slim_game(g) for g in get("/score/now").get("games", [])]
        game = next((g for g in scores if has_team(g)), None)
        landing = None

        # Late games can roll past the API's "today"; fall back to the schedule.
        if game is None:
            live = next((s for s in self.schedule if s.get("gameState") in LIVE_STATES), None)
            if live:
                landing = get(f"/gamecenter/{live['id']}/landing")
                game = slim_game(landing)

        mode = self.pick_mode(game)
        details, goal_info = None, None
        if game and mode in ("live", "final"):
            # The game feeds have shots, penalties, scoring and the line score.
            if landing is None:
                landing = get(f"/gamecenter/{game['id']}/landing")
            tv = game.get("tv") or []
            game = slim_game(landing)
            game["tv"] = game["tv"] or tv
            try:
                rr = get(f"/gamecenter/{game['id']}/right-rail")
            except Exception as e:
                log.warning("right-rail failed: %s", e)
                rr = {}
            details, goals = build_details(landing, rr, game)
            goal_info = latest_goal(goals)
            mode = self.pick_mode(game)
            # Full lineups with game stats, for intermissions and after the game
            if game["intermission"] or mode == "final":
                key = (game["id"], game.get("period"), mode)
                if key != getattr(self, "lineup_key", None) or not getattr(self, "lineups", None):
                    try:
                        self.lineups = slim_lineups(get(f"/gamecenter/{game['id']}/boxscore"))
                        self.lineup_key = key
                    except Exception as e:
                        log.warning("boxscore failed: %s", e)
                details["lineups"] = getattr(self, "lineups", None)

        if game:
            self.check_goal(game)

        # Playoffs, injuries, lineups, transactions, prospects, history, offseason
        if self.extras is None:
            self.extras = Extras(session, get, TEAM, self.affiliates)
        season = next((s.get("season") for s in self.schedule if s.get("season")), None)
        try:
            extra = self.extras.update(self.schedule, scores, game, season)
            with lock:
                state.update({k: v for k, v in extra.items()})
        except Exception as e:
            log.warning("extras failed: %s", e)

        with lock:
            state.update(mode=mode, game=game, details=details, scores=scores,
                         updated=datetime.now(timezone.utc).isoformat(), error=None)
            if goal_info:
                state["goal_info"] = goal_info
        return mode

    def run(self):
        while True:
            try:
                mode = self.tick()
                delay = 10 if mode in ("live", "pregame") else (20 if getattr(self, "affiliate_live", False) else 60)
            except Exception as e:   # keep the wall display alive no matter what
                log.warning("update failed: %s", e)
                with lock:
                    state["error"] = "Can't reach the NHL feed. Retrying."
                delay = 30
            time.sleep(delay)


# ---------- web ----------
STARTED = str(int(time.time()))


def build_id():
    """Changes when the server restarts or index.html is replaced, so open screens reload themselves."""
    try:
        mtime = int(os.path.getmtime(os.path.join(app.static_folder, "index.html")))
    except OSError:
        mtime = 0
    return f"{STARTED}-{mtime}"


def config():
    return {"night": NIGHT, "night_start": NIGHT_START, "night_end": NIGHT_END,
            "horn": GOAL_HORN, "horn_volume": HORN_VOLUME, "horn_max_seconds": HORN_MAX_SECONDS,
            "horn_file": os.path.exists(os.path.join(app.static_folder, "horn.mp3")),
            # Team horns: static/horn-ahl.mp3, static/horn-echl.mp3 (or horn-<team code>.mp3)
            "horn_files": sorted(f[5:-4].lower() for f in os.listdir(app.static_folder)
                                 if f.lower().startswith("horn-") and f.lower().endswith(".mp3")),
            "affiliate_takeover": AFFILIATE_TAKEOVER, "affiliate_horn": AFFILIATE_HORN,
            "affiliate_horn_volume": AFFILIATE_HORN_VOLUME}


@app.route("/api/state")
def api_state():
    # ?delay=N lets one screen use its own delay (e.g. ?delay=0 for friends watching live)
    try:
        delay = max(0, min(MAX_DELAY, int(request.args.get("delay", current_delay))))
    except ValueError:
        delay = current_delay
    snap = snapshot(delay)
    if snap is None:
        with lock:
            snap = copy.deepcopy(state)
    return jsonify({**snap, "build": build_id(), "config": config(), "delay": delay})


@app.route("/api/delay", methods=["GET", "POST"])
def api_delay():
    """GET shows the current delay; POST ?seconds=45 changes it (home network only). It's saved."""
    if request.method == "POST":
        if not allowed_to_control():
            return jsonify({"ok": False, "error": "Not allowed from outside the home network"}), 403
        try:
            save_delay(request.args.get("seconds", "0"))
        except ValueError:
            return jsonify({"ok": False, "error": "seconds must be a number"}), 400
    return jsonify({"ok": True, "delay": current_delay})


def from_home_network():
    """True for requests from this machine or your LAN. Anything that came through a
    Cloudflare Tunnel carries a Cf-Connecting-Ip header and counts as outside."""
    if request.headers.get("Cf-Connecting-Ip") or request.headers.get("X-Forwarded-For"):
        return False
    try:
        return ipaddress.ip_address(request.remote_addr or "").is_private
    except ValueError:
        return False


def allowed_to_control():
    token = request.headers.get("X-Admin-Token") or request.args.get("token") or ""
    return from_home_network() or (ADMIN_TOKEN and token == ADMIN_TOKEN)


@app.route("/api/test-goal", methods=["POST"])
def test_goal():
    """Trigger the goal screen, horn and goal hooks without waiting for a real goal.
    Add ?team=WBS (or any affiliate code) to test an affiliate goal instead.
    Only works from your home network, or with ADMIN_TOKEN from anywhere else."""
    if not allowed_to_control():
        return jsonify({"ok": False, "error": "Not allowed from outside the home network"}), 403
    team = (request.args.get("team") or TEAM).upper()
    if team == TEAM:
        with lock:
            state["goal_seq"] += 1
        fire_goal_hooks_later()
    else:
        with lock:
            aff = next((a for a in state["affiliates"] if (a.get("code") or "").upper() == team), None)
            state["aff_goal_seq"] += 1
            state["aff_goal"] = {"team": team, "league": aff["league"] if aff else "", "us": 1, "them": 0, "opp": "TST"}
        if AFFILIATE_HOOKS:
            fire_goal_hooks_later(team)
    return jsonify({"ok": True, "team": team})


@app.route("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


if __name__ == "__main__":
    threading.Thread(target=record_history, daemon=True).start()
    if DEMO:
        import demo
        threading.Thread(target=demo.run, args=(DEMO, state, lock), daemon=True).start()
    else:
        threading.Thread(target=Poller().run, daemon=True).start()
    app.run(host="0.0.0.0", port=PORT)
