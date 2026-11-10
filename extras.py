"""
Extra data for the wallboard: playoffs, injuries, lineups, transactions,
prospects, "on this day" history and offseason countdowns.

Sources (all public, none official, all fail quietly):
  - NHL:  api-web.nhle.com (playoff series, prospects, game rosters, schedules)
  - ESPN: site.api.espn.com (NHL injuries and transactions)
  - ECHL: echl.com/transactions (the league's transactions page)
  - AHL:  HockeyTech's stats feed, best effort
"""
import json
import logging
import os
import re
import threading
import time
from datetime import date, datetime, timezone, timedelta

log = logging.getLogger("wallboard.extras")
NHL = "https://api-web.nhle.com/v1"
ESPN = "https://site.api.espn.com/apis/site/v2/sports/hockey/nhl"
HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")


def text(v):
    if isinstance(v, dict):
        return v.get("default", "")
    return v or ""


def strip(s):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", str(s or ""))).strip()


def parse_time(s):
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except ValueError:
        return None


def full_name(p):
    return f"{text(p.get('firstName'))} {text(p.get('lastName'))}".strip() or text(p.get("name"))


# ---------------------------------------------------------------- playoffs
def series_text(team, top, top_w, bot, bot_w, need=4):
    """'PIT leads 2-1', 'Series tied 1-1', 'PIT wins 4-2', 'NYR wins 4-1'."""
    if top_w is None or bot_w is None:
        return ""
    if top_w >= need or bot_w >= need:
        w, l, winner = (top_w, bot_w, top) if top_w > bot_w else (bot_w, top_w, bot)
        return f"{winner} wins {w}-{l}"
    if top_w == bot_w:
        return f"Series tied {top_w}-{bot_w}"
    w, l, leader = (top_w, bot_w, top) if top_w > bot_w else (bot_w, top_w, bot)
    return f"{leader} leads {w}-{l}"


def slim_series(s):
    top, bot = s.get("topSeed") or {}, s.get("bottomSeed") or {}
    need = s.get("neededToWin") or 4
    return {
        "letter": s.get("seriesLetter"), "round": s.get("roundNumber"),
        "label": s.get("seriesLabel") or "",
        "top": {"abbrev": top.get("abbrev"), "wins": top.get("wins"), "logo": top.get("darkLogo") or top.get("logo")},
        "bottom": {"abbrev": bot.get("abbrev"), "wins": bot.get("wins"), "logo": bot.get("darkLogo") or bot.get("logo")},
        "need": need,
        "text": series_text(None, top.get("abbrev"), top.get("wins"), bot.get("abbrev"), bot.get("wins"), need),
    }


# ---------------------------------------------------------------- history
# Hand-picked moments (month-day: list of "year: text"). Add your own in data/history_events.json
# using the same shape, e.g. {"03-15": ["1995: Something happened"]}.
EVENTS = {
    "10-11": ["1967: The Penguins play their first NHL game, against Montreal at the Civic Arena",
              "1984: Mario Lemieux scores on his first shift and first shot in his NHL debut, at Boston"],
    "12-31": ["1988: Mario Lemieux scores five goals five different ways against New Jersey"],
    "12-27": ["2000: Mario Lemieux returns from retirement with a goal and two assists against Toronto"],
    "06-09": ["1984: The Penguins draft Mario Lemieux first overall"],
    "07-30": ["2005: The Penguins draft Sidney Crosby first overall"],
    "10-05": ["2005: Sidney Crosby makes his NHL debut, at New Jersey"],
    "10-18": ["2006: Evgeni Malkin scores in his NHL debut against New Jersey"],
    "02-16": ["2018: Sidney Crosby records his 1,000th NHL point, against Winnipeg"],
    "05-25": ["1991: The Penguins win their first Stanley Cup, 8-0 in Game 6 at Minnesota"],
    "06-01": ["1992: The Penguins sweep Chicago to win back-to-back Stanley Cups"],
    "06-12": ["2009: The Penguins win Game 7 at Detroit, 2-1, for their third Stanley Cup",
              "2016: The Penguins win the Stanley Cup in Game 6 at San Jose, 3-1"],
    "06-11": ["2017: The Penguins beat Nashville 2-0 in Game 6 to win back-to-back Cups again"],
}


class History:
    """Every past Penguins result, cached on disk, plus hand-picked moments."""

    def __init__(self, get, team):
        self.get, self.team = get, team
        self.games = []
        self.path = os.path.join(DATA, "history_games.json")
        self.lock = threading.Lock()

    def load(self):
        try:
            with open(self.path) as f:
                self.games = json.load(f)
        except (OSError, ValueError):
            self.games = []

    def build(self, current_season):
        """One-time background job: download every season's results (about 60 small requests)."""
        if self.games:
            return
        os.makedirs(DATA, exist_ok=True)
        start = 1967 if self.team == "PIT" else 1990
        end = int(str(current_season)[:4]) if current_season else datetime.now().year
        out = []
        for y in range(start, end):
            if y == 2004:          # lockout
                continue
            try:
                games = self.get(f"/club-schedule-season/{self.team}/{y}{y + 1}").get("games", [])
            except Exception as e:
                log.info("history %s skipped: %s", y, e)
                continue
            for g in games:
                if g.get("gameType") not in (2, 3):
                    continue
                a, h = g.get("awayTeam") or {}, g.get("homeTeam") or {}
                if a.get("score") is None or h.get("score") is None:
                    continue
                us, them = (h, a) if h.get("abbrev") == self.team else (a, h)
                out.append({"d": g.get("gameDate"), "t": g.get("gameType"), "opp": them.get("abbrev"),
                            "us": us["score"], "them": them["score"], "home": us is h,
                            "ot": (g.get("gameOutcome") or {}).get("lastPeriodType")})
            time.sleep(0.4)
        if out:
            with open(self.path, "w") as f:
                json.dump(out, f)
            self.games = out
            log.info("history built: %d games", len(out))

    def today(self, day=None):
        day = day or date.today()
        key = day.strftime("%m-%d")
        items = list(EVENTS.get(key, []))
        try:
            with open(os.path.join(DATA, "history_events.json")) as f:
                items += json.load(f).get(key, [])
        except (OSError, ValueError):
            pass
        games = [g for g in self.games if (g.get("d") or "")[5:] == key and (g.get("d") or "")[:4] != str(day.year)]
        def line(g):
            res = "beat" if g["us"] > g["them"] else ("lost to" if g["ot"] not in ("OT", "SO") else "fell in OT to")
            where = "" if g["home"] else " on the road"
            kind = "playoff game" if g["t"] == 3 else ""
            score = f"{max(g['us'], g['them'])}-{min(g['us'], g['them'])}"
            return f"{g['d'][:4]}: Penguins {res} {g['opp']} {score}{where}" + (f" in a {kind}" if kind else "")
        playoff_wins = [g for g in games if g["t"] == 3 and g["us"] > g["them"]]
        big_wins = sorted([g for g in games if g["us"] - g["them"] >= 3], key=lambda g: g["them"] - g["us"])
        for g in playoff_wins[:2] + big_wins[:2]:
            s = line(g)
            if s not in items:
                items.append(s)
        return items[:4]


# ---------------------------------------------------------------- the collector
class Extras:
    def __init__(self, session, get, team, affiliates):
        self.s, self.get, self.team, self.affiliates = session, get, team, affiliates
        self.next = {}
        self.history = History(get, team)
        self.history.load()
        self.history_started = False
        self.data = {"playoffs": None, "injuries": [], "opp_injuries": [], "transactions": [],
                     "prospects": [], "on_this_day": [], "offseason": None, "lineup": None}
        self.lineup_game = None

    def due(self, key, minutes):
        now = time.time()
        if now >= self.next.get(key, 0):
            self.next[key] = now + minutes * 60
            return True
        return False

    def safely(self, label, fn, *args):
        try:
            fn(*args)
        except Exception as e:
            log.warning("%s failed: %s", label, e)

    def json(self, url, **params):
        r = self.s.get(url, params=params or None, timeout=12)
        r.raise_for_status()
        return r.json()

    # ---- playoffs (NHL) ----
    def playoffs(self, season):
        data = self.get(f"/playoff-series/carousel/{season}/")
        rounds = data.get("rounds") or []
        if not rounds:
            return
        current = rounds[-1]
        series = [slim_series(s) for s in current.get("series") or []]
        ours = None
        for r in rounds:
            for s in r.get("series") or []:
                ss = slim_series(s)
                if self.team in (ss["top"]["abbrev"], ss["bottom"]["abbrev"]):
                    ours = ss
        self.data["playoffs"] = {"round": current.get("roundNumber"), "label": current.get("roundLabel") or "",
                                 "series": series, "ours": ours}

    # ---- injuries (ESPN) ----
    def injuries(self, opponent):
        data = self.json(f"{ESPN}/injuries")
        def team_list(match):
            for t in data.get("injuries") or []:
                name = (t.get("displayName") or "") + " " + str(t.get("abbreviation") or "")
                if match(t, name):
                    out = []
                    for i in t.get("injuries") or []:
                        a = i.get("athlete") or {}
                        d = i.get("details") or {}
                        out.append({"name": a.get("displayName") or a.get("shortName"),
                                    "pos": (a.get("position") or {}).get("abbreviation"),
                                    "status": i.get("status") or (i.get("type") or {}).get("description"),
                                    "injury": d.get("type") or d.get("detail") or "",
                                    "back": d.get("returnDate")})
                    return out
            return []
        ours = {"PIT": "penguins"}.get(self.team, self.team.lower())
        self.data["injuries"] = team_list(lambda t, n: ours in n.lower())
        self.data["opp_injuries"] = team_list(lambda t, n: opponent and (
            str(t.get("abbreviation") or "").upper() == opponent or opponent_name(opponent) in n.lower())) if opponent else []

    # ---- transactions ----
    def transactions(self):
        items = []
        # NHL (ESPN): covers call-ups, assignments to WBS, signings, trades
        try:
            data = self.json(f"{ESPN}/transactions", limit=200)
            for t in data.get("transactions") or []:
                team = t.get("team") or {}
                if str(team.get("abbreviation") or "").upper() == self.team or "penguins" in str(team.get("displayName") or "").lower():
                    items.append({"date": (t.get("date") or "")[:10], "tag": "NHL", "text": strip(t.get("description"))})
        except Exception as e:
            log.warning("NHL transactions failed: %s", e)
        # ECHL: the league's transactions page
        try:
            r = self.s.get("https://www.echl.com/transactions", timeout=12, headers={"User-Agent": "Mozilla/5.0"})
            r.raise_for_status()
            for row in re.findall(r"<tr[^>]*>(.*?)</tr>", r.text, re.S | re.I):
                cells = [c for c in re.findall(r"<td[^>]*>(.*?)</td>", row, re.S | re.I)]
                if len(cells) < 3:
                    continue
                raw = row.lower()
                if not ("everblades" in raw or "florida" in raw or "wilkes-barre" in raw or "pittsburgh" in raw):
                    continue
                name, detail = strip(cells[0]), strip(cells[2])
                m = re.search(r"\d{4}-\d{2}-\d{2}", strip(cells[-1]))
                if name and detail:
                    items.append({"date": m.group(0) if m else "", "tag": "ECHL", "text": f"{name}: {detail}"})
        except Exception as e:
            log.info("ECHL transactions unavailable: %s", e)
        # AHL: HockeyTech, best effort
        for a in self.affiliates:
            if a.league != "ahl" or not a.team or not a.season:
                continue
            try:
                data = a.get(feed="statviewfeed", view="transactions", season=a.season, team=a.team["id"], site_id=0)
                rows = []
                for block in (data if isinstance(data, list) else [data]):
                    for sec in (block.get("sections") or []) if isinstance(block, dict) else []:
                        rows += [d.get("row", d) for d in sec.get("data") or [] if isinstance(d, dict)]
                for row in rows[:15]:
                    who = strip(row.get("player_name") or row.get("name"))
                    what = strip(row.get("transaction") or row.get("description") or row.get("type"))
                    if who and what:
                        items.append({"date": str(row.get("date") or "")[:10], "tag": "AHL", "text": f"{who}: {what}"})
            except Exception as e:
                log.info("AHL transactions unavailable: %s", e)
        seen, out = set(), []
        for i in sorted(items, key=lambda x: x["date"], reverse=True):
            if i["text"] in seen:
                continue
            seen.add(i["text"])
            out.append(i)
        self.data["transactions"] = out[:12]

    # ---- prospects ----
    def prospects(self):
        data = self.get(f"/prospects/{self.team}")
        people = [(p, "G" if grp == "goalies" else None) for grp in ("forwards", "defensemen", "goalies")
                  for p in data.get(grp) or []]
        out = []
        for p, kind in people:
            pid = p.get("id") or p.get("playerId")
            if not pid:
                continue
            try:
                land = self.get(f"/player/{pid}/landing")
            except Exception:
                continue
            seasons = [s for s in land.get("seasonTotals") or [] if s.get("gameTypeId") in (2, None)]
            if not seasons:
                continue
            latest = max(s.get("season", 0) for s in seasons)
            cur = [s for s in seasons if s.get("season") == latest]
            s = max(cur, key=lambda x: x.get("gamesPlayed") or 0)
            if latest < (datetime.now().year - 1) * 10000:      # not playing this season
                continue
            row = {"name": full_name(land) or full_name(p), "pos": land.get("position") or p.get("positionCode"),
                   "headshot": land.get("headshot") or p.get("headshot"),
                   "league": s.get("leagueAbbrev"), "team": text(s.get("teamName")),
                   "gp": s.get("gamesPlayed") or 0}
            if (row["pos"] or kind) == "G":
                row.update(goalie=True, w=s.get("wins"), gaa=s.get("goalsAgainstAvg"), svp=s.get("savePctg"))
            else:
                row.update(g=s.get("goals") or 0, a=s.get("assists") or 0, pts=s.get("points") or 0)
            out.append(row)
            time.sleep(0.2)
        skaters = sorted([r for r in out if not r.get("goalie") and r["gp"]],
                         key=lambda r: (r["pts"] / max(1, r["gp"]), r["pts"]), reverse=True)
        goalies = sorted([r for r in out if r.get("goalie") and r["gp"]], key=lambda r: r["gp"], reverse=True)
        self.data["prospects"] = skaters[:7] + goalies[:2]

    # ---- lineups (NHL) ----
    def lineup(self, game):
        """Goalies: season numbers before a game, confirmed starters once it begins."""
        if not game:
            self.data["lineup"] = None
            return
        gid = game["id"]
        if game["state"] in ("LIVE", "CRIT", "FINAL", "OFF"):
            box = self.get(f"/gamecenter/{gid}/boxscore")
            pbs = box.get("playerByGameStats") or {}
            out = {}
            for side in ("awayTeam", "homeTeam"):
                goalies = (pbs.get(side) or {}).get("goalies") or []
                start = next((g for g in goalies if g.get("starter")), None)
                out[side[:4]] = {"confirmed": True, "goalies": [{"name": text(start.get("name"))}] if start else []}
            self.data["lineup"] = {"game": gid, **out}
            return
        land = self.get(f"/gamecenter/{gid}/landing")
        comp = ((land.get("matchup") or {}).get("goalieComparison")) or {}
        out = {}
        for side in ("awayTeam", "homeTeam"):
            leaders = (comp.get(side) or {}).get("leaders") or []
            out[side[:4]] = {"confirmed": False, "goalies": [
                {"name": text(g.get("name")) or full_name(g), "record": g.get("record"),
                 "gaa": g.get("gaa"), "svp": g.get("savePctg")} for g in leaders[:2]]}
        self.data["lineup"] = {"game": gid, **out}

    # ---- offseason ----
    def offseason(self, schedule, season):
        now = datetime.now(timezone.utc)
        played = [parse_time(s.get("startTimeUTC")) for s in schedule if s.get("gameState") in ("FINAL", "OFF")]
        upcoming = [s for s in schedule if s.get("gameState") in ("FUT", "PRE")
                    and (parse_time(s.get("startTimeUTC")) or now) > now]
        last = max([p for p in played if p], default=None)
        nxt = parse_time(upcoming[0].get("startTimeUTC")) if upcoming else None
        quiet = (not last or now - last > timedelta(days=10)) and (not nxt or nxt - now > timedelta(days=10))
        if not quiet:
            self.data["offseason"] = None
            return
        opening = next((s for s in upcoming if s.get("gameType") == 2), None)
        if not opening and season:
            y = int(str(season)[:4]) + 1
            try:
                nxt_games = self.get(f"/club-schedule-season/{self.team}/{y}{y + 1}").get("games", [])
                opening = next((s for s in nxt_games if s.get("gameType") == 2), None)
            except Exception:
                opening = None
        today = date.today()
        draft = os.environ.get("DRAFT_DATE")
        draft_est = False
        if not draft:
            d = date(today.year, 6, 30)
            while d.weekday() != 4:          # last Friday of June
                d -= timedelta(days=1)
            draft, draft_est = d.isoformat(), True
        fa = os.environ.get("FREE_AGENCY_DATE") or date(today.year, 7, 1).isoformat()
        events = []
        if draft >= today.isoformat():
            events.append({"label": "NHL Draft", "date": draft, "estimated": draft_est})
        if fa >= today.isoformat():
            events.append({"label": "Free agency opens", "date": fa})
        if opening:
            a, h = (opening.get("awayTeam") or {}).get("abbrev"), (opening.get("homeTeam") or {}).get("abbrev")
            events.append({"label": "Opening night", "date": opening.get("startTimeUTC"),
                           "opp": h if a == self.team else a, "home": h == self.team})
        self.data["offseason"] = {"events": events}

    # ---- the update ----
    def update(self, schedule, scores, game, season):
        opponent = None
        if game:
            opponent = game["home"]["abbrev"] if game["away"]["abbrev"] == self.team else game["away"]["abbrev"]
        if season and not self.history_started:
            self.history_started = True
            threading.Thread(target=self.history.build, args=(season,), daemon=True).start()
        # Playoff mode: on while playoff games are being played, kept for 3 days after the last one.
        if any(g.get("gameType") == 3 for g in scores) or any(
                s.get("gameType") == 3 and s.get("gameState") not in ("FINAL", "OFF") for s in schedule):
            self.last_playoff_seen = time.time()
        if season and time.time() - getattr(self, "last_playoff_seen", 0) < 3 * 86400:
            if self.due("playoffs", 10):
                self.safely("playoffs", self.playoffs, season)
        else:
            self.data["playoffs"] = None
        if self.due("injuries", 30) or (opponent and self.lineup_game != (game or {}).get("id")):
            self.safely("injuries", self.injuries, opponent)
        if game and (self.lineup_game != game["id"] or self.due("lineup", 10)):
            self.lineup_game = game["id"]
            self.safely("lineup", self.lineup, game)
        elif not game:
            self.data["lineup"] = None
        if self.due("transactions", 30):
            self.safely("transactions", self.transactions)
        if self.due("prospects", 12 * 60):
            threading.Thread(target=self.safely, args=("prospects", self.prospects), daemon=True).start()
        if self.due("history", 60):
            self.data["on_this_day"] = self.history.today()
        if self.due("offseason", 60):
            self.safely("offseason", self.offseason, schedule, season)
        return self.data


NAMES = {"ANA": "ducks", "BOS": "bruins", "BUF": "sabres", "CAR": "hurricanes", "CBJ": "blue jackets", "CGY": "flames",
         "CHI": "blackhawks", "COL": "avalanche", "DAL": "stars", "DET": "red wings", "EDM": "oilers", "FLA": "panthers",
         "LAK": "kings", "MIN": "wild", "MTL": "canadiens", "NJD": "devils", "NSH": "predators", "NYI": "islanders",
         "NYR": "rangers", "OTT": "senators", "PHI": "flyers", "PIT": "penguins", "SEA": "kraken", "SJS": "sharks",
         "STL": "blues", "TBL": "lightning", "TOR": "maple leafs", "UTA": "mammoth", "VAN": "canucks",
         "VGK": "golden knights", "WPG": "jets", "WSH": "capitals"}


def opponent_name(abbrev):
    return NAMES.get(abbrev, abbrev.lower())
