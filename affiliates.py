"""
Minor-league affiliates (AHL and ECHL) from HockeyTech, the stats system behind
both leagues' websites. Like the NHL feed it's public but undocumented, so every
lookup here fails quietly: if HockeyTech changes something, the affiliate parts
of the board disappear and the Penguins side keeps working.
"""
import json
import logging
import re
import time
import unicodedata
from datetime import datetime, timezone, timedelta

HT = "https://lscluster.hockeytech.com/feed/index.php"
# Public keys embedded in each league's own website.
KEYS = {"ahl": "50c2cd9b5e18e390", "echl": "2c2b89ea7345cae8"}
LABELS = {"ahl": "AHL", "echl": "ECHL"}
SKIP_SEASONS = ("all-star", "all star", "exhibition", "pre-season", "preseason", "showcase")

log = logging.getLogger("wallboard.affiliates")


def num(v):
    try:
        return int(str(v).strip())
    except (TypeError, ValueError):
        return None


def parse_iso(s):
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except ValueError:
        return None


def ordinal(n):
    return f"{n}{'th' if 10 <= n % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"


def period_name(n):
    n = num(n) or 0
    return {4: "OT", 5: "SO"}.get(n, ordinal(n) if n else "")


def mmss(s):
    try:
        m, sec = str(s).strip().split(":")[:2]
        return int(m) * 60 + int(float(sec))
    except (ValueError, AttributeError):
        return 0


def person_last(p):
    if not isinstance(p, dict):
        return ""
    return p.get("last_name") or p.get("lastName") or ""


def norm(name):
    """Player names compared across feeds: no accents, punctuation or case."""
    s = unicodedata.normalize("NFKD", str(name or "")).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z ]", "", s).strip()


def pct(v):
    """'21.3' or '0.213' or 21.3 -> 21.3"""
    try:
        f = float(str(v).strip().rstrip("%"))
    except (TypeError, ValueError):
        return None
    return round(f * 100, 1) if f <= 1 else round(f, 1)


def strip_tags(s):
    return re.sub(r"<[^>]+>", "", str(s or "")).strip()


def power_play(game, pens):
    """Whichever team has fewer players in the box is on the power play."""
    away = [p for p in pens if p["team"] == game["away"]["abbrev"]]
    home = [p for p in pens if p["team"] == game["home"]["abbrev"]]
    if len(away) == len(home):
        return None
    short, adv = (away, game["home"]["abbrev"]) if len(away) > len(home) else (home, game["away"]["abbrev"])
    left = min(p["left_s"] for p in short)
    return {"pp": adv, "en": None, "time": f"{left // 60}:{left % 60:02d}"}


def parse_shootout(gs, game):
    """Shootout attempts in order, from whichever shootout section the feed provides."""
    cand = next((v for k, v in gs.items() if "shootout" in k.lower() and isinstance(v, (dict, list)) and v), None)
    if not cand:
        return []
    if isinstance(cand, dict):
        home = next((v for k, v in cand.items() if "home" in k.lower() and isinstance(v, list)), [])
        vis = next((v for k, v in cand.items() if ("visit" in k.lower() or "away" in k.lower()) and isinstance(v, list)), [])
    else:
        home = [s for s in cand if isinstance(s, dict) and str(s.get("home")) == "1"]
        vis = [s for s in cand if isinstance(s, dict) and str(s.get("home")) != "1"]

    def attempt(s, side):
        sh = s.get("shooter") or s.get("shooter_info") or s
        last, first = person_last(sh), sh.get("firstName") or sh.get("first_name") or ""
        g = s.get("isGoal")
        goal = g is True or str(g if g is not None else s.get("goal") or s.get("is_goal") or s.get("result") or "").lower() in ("1", "true", "goal", "yes")
        return {"team": game[side]["abbrev"], "name": last, "full": f"{first} {last}".strip(), "headshot": "",
                "shot": "", "goal": goal, "result": "goal" if goal else "no goal",
                "winner": bool(s.get("isGameWinningGoal")) or str(s.get("game_winner") or s.get("winning_goal") or "") == "1",
                "seq": num(s.get("sequence") or s.get("order") or s.get("shot_order"))}
    A = [attempt(s, "away") for s in vis if isinstance(s, dict)]
    H = [attempt(s, "home") for s in home if isinstance(s, dict)]
    if A + H and all(x["seq"] for x in A + H):
        return sorted(A + H, key=lambda x: x["seq"])
    out = []
    for i in range(max(len(A), len(H))):
        out += ([A[i]] if i < len(A) else []) + ([H[i]] if i < len(H) else [])
    return out


class Affiliate:
    def __init__(self, session, league, needle, key=None):
        self.s = session
        self.league = league.lower()
        self.label = LABELS.get(self.league, self.league.upper())
        self.needle = needle.lower()
        self.key = key or KEYS.get(self.league, "")
        self.season = None
        self.season_name = ""
        self.season_start = ""
        self.team = None
        self.games = []
        self.standings = None
        self.leaders = []
        self.last_score = {}
        self.live_ids = set()        # games we watched live
        self.final_at = {}           # game id -> when we saw it go final
        self.detail_cache = {}       # game id -> details fetched after the final
        self.postgame_minutes = 30
        self.logos = {}
        self.players = {}           # normalized name -> {"name", "gp", "pos"} for this season, our team
        self.roster = set()         # normalized names currently on our roster
        self.team_stats = {}        # team code -> {"pp", "pk", "gf", "ga"} across the league          # team code -> logo URL, for every team in the league
        self.next = {"meta": 0, "scores": 0, "standings": 0, "leaders": 0, "players": 0}

    def logo_for(self, team_id, given=None):
        """Use the feed's logo, or HockeyTech's standard logo address for that team."""
        if given:
            return given
        return f"https://assets.leaguestat.com/{self.league}/logos/{team_id}.png" if team_id not in (None, "", "None") else None

    # ---------- HTTP ----------
    def get(self, **params):
        p = {"key": self.key, "client_code": self.league, "fmt": "json", "lang": "en", **params}
        r = self.s.get(HT, params=p, timeout=12)
        r.raise_for_status()
        text = r.text.strip()
        if text.startswith("(") and text.endswith(")"):   # some feeds wrap JSON in parentheses
            text = text[1:-1]
        return json.loads(text)

    # ---------- lookups ----------
    def find_season(self):
        seasons = (self.get(feed="modulekit", view="seasons").get("SiteKit") or {}).get("Seasons") or []
        today = datetime.now().date().isoformat()
        best = None
        for s in seasons:
            name = (s.get("season_name") or "").lower()
            start = (s.get("start_date") or "")[:10]
            if any(w in name for w in SKIP_SEASONS) or not start or start > today:
                continue
            if best is None or start > (best.get("start_date") or "")[:10]:
                best = s
        if best:
            self.season = str(best.get("season_id"))
            self.season_name = best.get("season_name") or ""
            self.season_start = (best.get("start_date") or "")[:10]

    def find_team(self):
        teams = (self.get(feed="modulekit", view="teamsbyseason", season_id=self.season)
                 .get("SiteKit") or {}).get("Teamsbyseason") or []
        for t in teams:
            code = t.get("code") or t.get("team_code")
            if code:
                self.logos[code] = self.logo_for(t.get("id"), t.get("team_logo_url") or t.get("logo"))
        for t in teams:
            hay = " ".join(str(t.get(k, "")) for k in ("name", "city", "nickname", "code")).lower()
            if self.needle in hay:
                self.team = {"id": str(t.get("id")), "code": t.get("code") or t.get("team_code"),
                             "name": t.get("name"), "nickname": t.get("nickname"), "city": t.get("city"),
                             "logo": self.logo_for(t.get("id"), t.get("team_logo_url") or t.get("logo")),
                             "division": t.get("division_long_name") or t.get("division_name")}
                return

    # ---------- games ----------
    def slim(self, g):
        text = g.get("GameStatusString") or ""
        status = str(g.get("GameStatus") or "")
        final = status in ("3", "4") or text.lower().startswith("final")
        live = status == "2" and not final
        short = (g.get("PeriodNameShort") or "").upper()

        def side(p):
            return {"abbrev": g.get(p + "Code"), "id": str(g.get(p + "ID")),
                    "name": g.get(p + "Nickname") or g.get(p + "LongName"), "city": g.get(p + "City"),
                    "score": num(g.get(p + "Goals")) if (live or final) else None,
                    "sog": None, "logo": self.logo_for(g.get(p + "ID"), g.get(p + "Logo")), "league": self.label}
        return {
            "id": str(g.get("ID")), "league": self.label,
            "state": "LIVE" if live else ("FINAL" if final else "FUT"),
            "start": g.get("GameDateISO8601"),
            "away": side("Visitor"), "home": side("Home"),
            "period": num(g.get("Period")),
            "periodType": "SO" if short.startswith("SO") else ("OT" if "OT" in short else "REG"),
            "clock": g.get("GameClock"),
            "intermission": str(g.get("Intermission")) == "1",
            "situation": None,
            "lastPeriodType": "SO" if "SO" in text.upper() else ("OT" if "OT" in text.upper() else "REG"),
            "statusText": text,
            "goals": [],
        }

    def fetch_scores(self):
        back = 21 if "playoff" in self.season_name.lower() else 7
        rows = (self.get(feed="modulekit", view="scorebar", numberofdaysback=back, numberofdaysahead=14)
                .get("SiteKit") or {}).get("Scorebar") or []
        for g in rows:
            for p in ("Home", "Visitor"):
                if g.get(p + "Code"):
                    self.logos.setdefault(g[p + "Code"], self.logo_for(g.get(p + "ID"), g.get(p + "Logo")))
        if not self.team:   # fall back to matching the name in the score feed
            for g in rows:
                for p in ("Home", "Visitor"):
                    hay = " ".join(str(g.get(p + k, "")) for k in ("LongName", "City", "Nickname", "Code")).lower()
                    if self.needle in hay:
                        self.team = {"id": str(g.get(p + "ID")), "code": g.get(p + "Code"),
                                     "name": g.get(p + "LongName"), "nickname": g.get(p + "Nickname"),
                                     "city": g.get(p + "City"), "logo": self.logo_for(g.get(p + "ID"), g.get(p + "Logo")),
                                     "division": None}
                        break
                if self.team:
                    break
        if not self.team:
            self.games = []
            return
        tid = self.team["id"]
        games = [self.slim(g) for g in rows if tid in (str(g.get("HomeID")), str(g.get("VisitorID")))]
        now = time.time()
        for g in games:
            if g["state"] == "LIVE":
                self.live_ids.add(g["id"])
            elif g["state"] == "FINAL" and g["id"] in self.live_ids and g["id"] not in self.final_at:
                self.final_at[g["id"]] = now
        self.games = sorted(games, key=lambda g: g["start"] or "")

    def fetch_detail(self, game):
        """Shots and scoring for a live game. Best effort: the board works without it."""
        gs = (self.get(feed="gc", tab="gamesummary", game_id=game["id"]).get("GC") or {}).get("Gamesummary") or {}
        shots = gs.get("totalShots") or {}
        game["home"]["sog"], game["away"]["sog"] = num(shots.get("home")), num(shots.get("visitor"))
        hs = vs = 0
        goals = []
        for gl in gs.get("goals") or []:
            home = str(gl.get("team_id")) == game["home"]["id"]
            if home:
                hs += 1
            else:
                vs += 1
            scorer = gl.get("goal_scorer") or {}
            assists = [a for a in (gl.get("assist1_player"), gl.get("assist2_player")) if isinstance(a, dict) and a.get("last_name")]
            goals.append({
                "period": period_name(gl.get("period_id") or (gl.get("period") or {}).get("id")),
                "num": num(gl.get("period_id")) or 0, "time": gl.get("time"),
                "team": game["home"]["abbrev"] if home else game["away"]["abbrev"],
                "scorer": scorer.get("last_name") or "", "total": None,
                "assists": [{"name": a.get("last_name"), "num": None} for a in assists],
                "strength": "pp" if str(gl.get("power_play")) == "1" else ("sh" if str(gl.get("short_handed")) == "1" else "ev"),
                "en": str(gl.get("empty_net")) == "1", "away": vs, "home": hs,
            })
        game["goals"] = goals
        # Goals and shots by period, when the feed has them
        def by_period(obj):
            obj = obj or {}
            h, v = obj.get("home") or {}, obj.get("visitor") or {}
            keys = sorted({k for k in list(h) + list(v)}, key=lambda k: num(k) or 0)
            return [{"label": period_name(k), "away": num(v.get(k)), "home": num(h.get(k))} for k in keys]
        game["periods"] = by_period(gs.get("goalsByPeriod"))
        game["shots"] = by_period(gs.get("shotsByPeriod"))
        # Full lineups with game stats, when the feed lists them
        lineups = {}
        for side, key in (("home", "home_team_lineup"), ("away", "visitor_team_lineup")):
            lu = gs.get(key) or {}
            skaters = []
            for p in lu.get("players") or []:
                pos = str(p.get("position_str") or p.get("position") or "").upper()
                g_, a_ = num(p.get("goals")) or 0, num(p.get("assists")) or 0
                skaters.append({"num": p.get("jersey_number"), "name": f"{(p.get('first_name') or '')[:1]}. {p.get('last_name') or ''}".strip(". "),
                                "pos": pos, "group": "D" if pos.startswith("D") else "F", "g": g_, "a": a_, "pts": g_ + a_,
                                "sog": num(p.get("shots") or p.get("shots_on")), "pm": num(p.get("plusminus")), "toi": None})
            goalies = []
            for p in lu.get("goalies") or []:
                sa, ga = num(p.get("shots_against")), num(p.get("goals_against"))
                saves = num(p.get("saves")) if p.get("saves") is not None else (sa - ga if sa is not None and ga is not None else None)
                goalies.append({"num": p.get("jersey_number"), "name": f"{(p.get('first_name') or '')[:1]}. {p.get('last_name') or ''}".strip(". "),
                                "sa": f"{saves}/{sa}" if saves is not None and sa is not None else None,
                                "svp": (saves / sa) if saves is not None and sa else None, "ga": ga,
                                "toi": p.get("time") or p.get("toi"), "starter": str(p.get("start") or p.get("starting") or "") == "1"})
            if skaters or goalies:
                lineups[side] = {"skaters": skaters, "goalies": goalies}
        game["lineups"] = lineups or None
        # Penalty box, power play and shootout
        playoff = "playoff" in self.season_name.lower()
        try:
            game["penalties"] = self.active_penalties(gs.get("penalties") or [], game, goals, playoff)
        except Exception as e:
            log.info("%s penalties unavailable: %s", self.label, e)
            game["penalties"] = []
        game["situation"] = power_play(game, game["penalties"])
        try:
            game["shootout"] = parse_shootout(gs, game)
        except Exception as e:
            log.info("%s shootout unavailable: %s", self.label, e)
            game["shootout"] = []
        # Starting goalies, when the feed lists lineups
        for side, key in (("home", "home_team_lineup"), ("away", "visitor_team_lineup")):
            lineup = gs.get(key) or {}
            goalies = lineup.get("goalies") or []
            start = next((g for g in goalies if str(g.get("start") or g.get("starting") or "") == "1"), None)
            if start and start.get("last_name"):
                game[side]["goalie"] = f"{start.get('first_name', '')} {start['last_name']}".strip()

    def active_penalties(self, raw, game, goals, playoff):
        """Penalties still being served. Same rules as the NHL side: a double minor is two
        minors back to back, and a power-play goal ends only the minor being served."""
        if game["state"] != "LIVE" or game.get("intermission") or not game.get("clock") or not game.get("period"):
            return []
        plen = lambda n: 1200 if (n <= 3 or playoff) else 300
        before = lambda n: sum(plen(k) for k in range(1, n))
        now = before(game["period"]) + plen(game["period"]) - mmss(game["clock"])
        home_id, home, away = game["home"]["id"], game["home"]["abbrev"], game["away"]["abbrev"]
        groups = {}
        for p in raw:
            try:
                mins = float(p.get("minutes") or p.get("minutes_formatted") or 0)
            except ValueError:
                continue
            cls = str(p.get("penalty_class") or "").lower()
            if mins not in (2, 4, 5) or "misconduct" in cls:
                continue
            n = num(p.get("period_id") or (p.get("period") or {}).get("id")) or 0
            if not n:
                continue
            start = before(n) + mmss(p.get("time") or p.get("time_off_formatted"))
            is_home = str(p.get("home")) == "1" or str(p.get("team_id")) == home_id
            team = home if is_home else away
            who = (person_last(p.get("player_penalized_info")) or person_last(p.get("offender"))
                   or person_last(p.get("player_served_info")) or ("Bench" if "bench" in cls else "Penalty"))
            desc = strip_tags(p.get("lang_penalty_description") or p.get("description") or p.get("offence") or "")
            kind = "MAJ" if mins == 5 else "MIN"
            groups.setdefault((team, who, start), []).extend(
                {"kind": kind, "minutes": m, "desc": desc} for m in ([2, 2] if mins == 4 else [int(mins)]))
        goal_times = sorted((before(g["num"]) + mmss(g["time"]), g["team"], g["strength"]) for g in goals if g.get("num"))
        out = []
        for (team, who, start), parts in groups.items():
            parts.sort(key=lambda x: (x["kind"] == "MAJ", x["minutes"]))
            t = start
            for part in parts:
                end = t + part["minutes"] * 60
                if part["kind"] == "MIN" and part["minutes"] == 2:
                    for gt, gteam, strength in goal_times:
                        if t < gt <= end and gteam != team and strength == "pp":
                            end = gt
                            break
                t = end
            if not (start <= now < t):
                continue
            descs = [x["desc"] for x in parts]
            label = f"{descs[0]} (double minor)" if len(parts) == 2 and descs[0] == descs[1] and parts[0]["kind"] == "MIN" \
                else ", ".join(dict.fromkeys(d for d in descs if d)) or "Penalty"
            left = t - now
            out.append({"team": team, "player": who, "infraction": label, "left": f"{left // 60}:{left % 60:02d}",
                        "left_s": left})
        return out

    # ---------- standings and leaders ----------
    def fetch_standings(self):
        data = self.get(feed="statviewfeed", view="teams", groupTeamsBy="division", context="overall",
                        site_id=0, season=self.season, special="false")
        code = self.team.get("code")
        # League-wide numbers for the pregame comparison, from every division's rows
        stats = {}
        for block in (data if isinstance(data, list) else [data]):
            for sec in (block.get("sections") or []) if isinstance(block, dict) else []:
                for d in sec.get("data") or []:
                    r = d.get("row", d) if isinstance(d, dict) else {}
                    c, gp = r.get("team_code"), num(r.get("games_played")) or 0
                    if not c:
                        continue
                    gf, ga = num(r.get("goals_for")), num(r.get("goals_against"))
                    stats[c] = {"pp": pct(r.get("power_play_pct")), "pk": pct(r.get("penalty_kill_pct")),
                                "gf": round(gf / gp, 2) if gf is not None and gp else None,
                                "ga": round(ga / gp, 2) if ga is not None and gp else None}
        if stats:
            from extras import add_ranks
            self.team_stats = add_ranks(stats)
        for block in (data if isinstance(data, list) else [data]):
            for sec in (block.get("sections") or []) if isinstance(block, dict) else []:
                rows = [d.get("row", d) for d in sec.get("data") or [] if isinstance(d, dict)]
                if not any(r.get("team_code") == code for r in rows):
                    continue
                title = ""
                try:
                    title = sec["headers"]["name"]["properties"]["title"]
                except (KeyError, TypeError):
                    title = sec.get("title") or ""
                self.standings = {
                    "title": strip_tags(title) or self.team.get("division") or "Division",
                    "rows": [{"abbrev": r.get("team_code"), "name": strip_tags(r.get("name")),
                              "logo": self.logo_for(r.get("team_id"), None) if r.get("team_id") else self.logos.get(r.get("team_code")),
                              "gp": num(r.get("games_played")), "w": num(r.get("wins")), "l": num(r.get("losses")),
                              "otl": (num(r.get("ot_losses")) or 0) + (num(r.get("shootout_losses")) or 0),
                              "pts": num(r.get("points"))} for r in rows],
                }
                return

    def fetch_leaders(self):
        rows = (self.get(feed="modulekit", view="statviewtype", type="topscorers", season_id=self.season,
                         team_id=self.team["id"], first=0, limit=10, sort="points", stat="all")
                .get("SiteKit") or {}).get("Statviewtype") or []
        out = []
        for r in rows:
            team = str(r.get("team_id") or r.get("team_code") or "")
            if team and team not in (self.team["id"], self.team.get("code")):
                continue      # the feed ignored the team filter
            name = strip_tags(r.get("name")) or f"{r.get('first_name', '')} {r.get('last_name', '')}".strip()
            pts = num(r.get("points"))
            if name and pts is not None:
                out.append({"name": name, "g": num(r.get("goals")), "a": num(r.get("assists")), "pts": pts})
            if len(out) >= 3:
                break
        self.leaders = out

    def fetch_players(self):
        """Everyone who has played for our team this season, with games played, and the current roster."""
        players = {}
        for kind in ("topscorers", "topgoalies"):
            try:
                rows = (self.get(feed="modulekit", view="statviewtype", type=kind, season_id=self.season,
                                 team_id=self.team["id"], first=0, limit=100, sort="games_played", stat="all")
                        .get("SiteKit") or {}).get("Statviewtype") or []
            except Exception as e:
                log.info("%s %s unavailable: %s", self.label, kind, e)
                continue
            for r in rows:
                if not isinstance(r, dict):
                    continue
                team = str(r.get("team_id") or r.get("team_code") or "")
                if team and team not in (self.team["id"], self.team.get("code")):
                    continue
                name = strip_tags(r.get("name")) or f"{r.get('first_name', '')} {r.get('last_name', '')}".strip()
                gp = num(r.get("games_played")) or 0
                if name and gp:
                    players[norm(name)] = {"name": name, "gp": gp,
                                           "pos": "G" if kind == "topgoalies" else (r.get("position") or "")}
        if players:
            self.players = players
        try:
            rows = (self.get(feed="modulekit", view="roster", team_id=self.team["id"], season_id=self.season)
                    .get("SiteKit") or {}).get("Roster") or []
            names = {norm(f"{r.get('first_name', '')} {r.get('last_name', '')}") for r in rows
                     if isinstance(r, dict) and r.get("last_name")}
            if names:
                self.roster = names
        except Exception as e:
            log.info("%s roster unavailable: %s", self.label, e)

    # ---------- the update loop ----------
    def update(self, now_ts):
        """Refresh whatever is due. Returns a list of goal events for our team."""
        events = []
        if now_ts >= self.next["meta"] or not self.season:
            try:
                self.find_season()
                if self.season:
                    self.find_team()
                self.next["meta"] = now_ts + 12 * 3600
            except Exception as e:
                log.warning("%s season/team lookup failed: %s", self.label, e)
                self.next["meta"] = now_ts + 600

        if now_ts >= self.next["scores"]:
            try:
                self.fetch_scores()
                for g in self.games:
                    if g["state"] == "LIVE":
                        try:
                            self.fetch_detail(g)
                        except Exception as e:
                            log.info("%s game detail unavailable: %s", self.label, e)
                        events += self.check_goal(g)
                    elif g["id"] in self.final_at:
                        # One last detail fetch after the final, then reuse it for the post-game screen
                        if g["id"] not in self.detail_cache:
                            try:
                                self.fetch_detail(g)
                                self.detail_cache[g["id"]] = {k: g.get(k) for k in ("goals", "periods", "shots", "lineups", "shootout")} | \
                                    {"away_sog": g["away"]["sog"], "home_sog": g["home"]["sog"]}
                            except Exception as e:
                                log.info("%s final detail unavailable: %s", self.label, e)
                        c = self.detail_cache.get(g["id"])
                        if c:
                            g.update({k: c[k] for k in ("goals", "periods", "shots", "lineups", "shootout")})
                            g["away"]["sog"], g["home"]["sog"] = c["away_sog"], c["home_sog"]
            except Exception as e:
                log.warning("%s scores failed: %s", self.label, e)
            self.next["scores"] = now_ts + (20 if self.is_live() else 300)

        if self.team and self.season and now_ts >= self.next["standings"]:
            try:
                self.fetch_standings()
            except Exception as e:
                log.warning("%s standings failed: %s", self.label, e)
            self.next["standings"] = now_ts + 30 * 60

        if self.team and self.season and now_ts >= self.next["players"]:
            try:
                self.fetch_players()
            except Exception as e:
                log.info("%s players unavailable: %s", self.label, e)
            self.next["players"] = now_ts + 6 * 3600

        if self.team and self.season and now_ts >= self.next["leaders"]:
            try:
                self.fetch_leaders()
            except Exception as e:
                log.info("%s leaders unavailable: %s", self.label, e)
            self.next["leaders"] = now_ts + 60 * 60
        return events

    def is_live(self):
        return any(g["state"] == "LIVE" for g in self.games)

    def check_goal(self, g):
        us = g["home"] if g["home"]["id"] == self.team["id"] else g["away"]
        them = g["away"] if us is g["home"] else g["home"]
        prev = self.last_score.get(g["id"])
        self.last_score[g["id"]] = us["score"]
        if prev is not None and us["score"] is not None and us["score"] > prev:
            return [{"team": us["abbrev"], "league": self.label, "us": us["score"],
                     "them": them["score"], "opp": them["abbrev"]}]
        return []

    def summary(self):
        if not self.team:
            return None
        now = datetime.now(timezone.utc)
        today = datetime.now().date()

        def local_date(g):
            t = parse_iso(g["start"])
            return t.astimezone().date() if t else None
        done = [g for g in self.games if g["state"] == "FINAL"]
        upcoming = [g for g in self.games if g["state"] == "FUT" and (parse_iso(g["start"]) or now) > now]
        playoffs = "playoff" in self.season_name.lower()
        series = None
        if playoffs and done:
            ours = [g for g in done if (g["start"] or "")[:10] >= self.season_start]
            if ours:
                last = ours[-1]
                opp = last["away"]["abbrev"] if last["home"]["id"] == self.team["id"] else last["home"]["abbrev"]
                w = l = 0
                for g in ours:
                    us, them = (g["home"], g["away"]) if g["home"]["id"] == self.team["id"] else (g["away"], g["home"])
                    if them["abbrev"] != opp or us["score"] is None:
                        continue
                    w, l = (w + 1, l) if us["score"] > them["score"] else (w, l + 1)
                code = self.team["code"]
                text = f"Series tied {w}-{l}" if w == l else (f"{code} leads {w}-{l}" if w > l else f"{opp} leads {l}-{w}")
                series = {"opp": opp, "w": w, "l": l, "text": f"{text} vs {opp}" if w != l else f"{text} with {opp}"}
        return {
            "playoffs": playoffs, "series": series,
            "league": self.label, "code": self.team["code"], "name": self.team["name"],
            "nickname": self.team["nickname"], "logo": self.team["logo"],
            "live": next((g for g in self.games if g["state"] == "LIVE"), None),
            "recent_final": next((g for g in self.games if g["id"] in self.final_at
                                  and time.time() - self.final_at[g["id"]] < self.postgame_minutes * 60), None),
            "today": [g for g in self.games if local_date(g) == today],
            "yesterday": [g for g in self.games if local_date(g) == today - timedelta(days=1)],
            "last": done[-1] if done else None,
            "next": upcoming[0] if upcoming else None,
            "standings": self.standings, "leaders": self.leaders,
            "team_stats": self.team_stats,
        }
