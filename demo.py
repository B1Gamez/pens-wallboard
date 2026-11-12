"""Fake data for previewing the wallboard without a live game. Used when DEMO is set."""
import random
import time
from datetime import datetime, timezone, timedelta

LOGO = "https://assets.nhle.com/logos/nhl/svg/{}_dark.svg"
logo = lambda a: LOGO.format(a)
HEAD = "https://assets.nhle.com/mugs/nhl/20252026/{}/{}.png"


def standings():
    divs = {
        "Metropolitan": ["CAR", "NJD", "NYR", "WSH", "NYI", "CBJ", "PIT", "PHI"],
        "Atlantic": ["FLA", "TOR", "TBL", "BOS", "DET", "OTT", "MTL", "BUF"],
        "Central": ["WPG", "DAL", "COL", "MIN", "NSH", "STL", "UTA", "CHI"],
        "Pacific": ["VGK", "EDM", "LAK", "VAN", "SEA", "CGY", "ANA", "SJS"],
    }
    out = []
    for div, teams in divs.items():
        conf = "Eastern" if div in ("Metropolitan", "Atlantic") else "Western"
        for i, a in enumerate(teams):
            w = 13 - i; l = 3 + i; otl = i % 3
            out.append({"abbrev": a, "name": a, "logo": LOGO.format(a), "division": div, "conference": conf,
                        "divSeq": i + 1, "wcSeq": 0, "gp": w + l + otl, "w": w, "l": l, "otl": otl,
                        "pts": 2 * w + otl - (1 if div == "Atlantic" else 0),
                        "streak": random.choice(["W2", "L1", "OT1", "W4"]), "l10": "6-3-1"})
    for conf in ("Eastern", "Western"):
        rest = sorted([t for t in out if t["conference"] == conf and t["divSeq"] > 3], key=lambda t: -t["pts"])
        for i, t in enumerate(rest):
            t["wcSeq"] = i + 1
    return out


def game(a, h, sa, sh, st, per=None, clk=None, start=None):
    start = start or datetime.now(timezone.utc)
    return {"id": hash((a, h)), "gameType": 2, "state": st, "start": start.isoformat(),
            "away": {"abbrev": a, "name": a, "score": sa, "sog": 21, "logo": LOGO.format(a)},
            "home": {"abbrev": h, "name": h, "score": sh, "sog": 18, "logo": LOGO.format(h)},
            "period": per, "periodType": "REG", "clock": clk, "running": True, "intermission": False,
            "situation": None, "lastPeriodType": "REG",
            "tv": [{"network": "SN-PIT", "market": "A", "country": "US"}]}


def demo_lineup(names, seed=1):
    random.seed(seed)
    sk = []
    for i, (n, pos) in enumerate(names):
        g_, a_ = random.choice([0, 0, 0, 1]), random.choice([0, 0, 1, 1, 2])
        sk.append({"num": 10 + i * 3 % 80, "name": n, "pos": pos, "group": "D" if pos == "D" else "F", "g": g_, "a": a_,
                   "pts": g_ + a_, "sog": random.randint(0, 5), "pm": random.randint(-2, 2), "toi": f"{random.randint(9, 24)}:{random.randint(10, 59)}"})
    return {"skaters": sk, "goalies": [{"num": 35, "name": "T. Jarry" if seed == 1 else "S. Ersson", "sa": "27/29", "svp": 0.931,
                                        "toi": "40:00", "starter": True, "ga": 2}]}


PIT_NAMES = [(n, p) for n, p in [("S. Crosby", "C"), ("E. Malkin", "C"), ("B. Rust", "R"), ("R. Rakell", "R"), ("M. Acciari", "C"),
             ("A. Mantha", "L"), ("T. Novak", "C"), ("C. Dewar", "L"), ("B. Kindel", "C"), ("V. Koivunen", "L"),
             ("N. Grant", "C"), ("K. Brazeau", "R"), ("E. Karlsson", "D"), ("K. Letang", "D"), ("R. Shea", "D"),
             ("P. Kulak", "D"), ("H. Brunicke", "D"), ("O. Pickering", "D")]]
PHI_NAMES = [(n, p) for n, p in [("T. Konecny", "R"), ("S. Couturier", "C"), ("M. Michkov", "R"), ("O. Tippett", "R"), ("T. Frost", "C"),
             ("N. Cates", "C"), ("J. Farabee", "L"), ("B. Brink", "L"), ("G. Hathaway", "R"), ("R. Poehling", "C"),
             ("N. Deslauriers", "L"), ("S. Laughton", "C"), ("T. Sanheim", "D"), ("C. York", "D"), ("J. Drysdale", "D"),
             ("R. Ristolainen", "D"), ("E. Juulsen", "D"), ("N. Seeler", "D")]]


def details(final=False):
    goals = [
        {"period": "1st", "num": 1, "time": "08:14", "team": "PIT", "scorer": "Rust", "full": "Bryan Rust", "total": 8,
         "headshot": HEAD.format("PIT", 8475810), "assists": [{"name": "Crosby", "num": 12}], "strength": "pp",
         "en": False, "away": 1, "home": 0},
        {"period": "2nd", "num": 2, "time": "03:51", "team": "PHI", "scorer": "Konecny", "full": "Travis Konecny",
         "total": 9, "headshot": "", "assists": [{"name": "Couturier", "num": 6}, {"name": "Sanheim", "num": 4}],
         "strength": "ev", "en": False, "away": 1, "home": 1},
        {"period": "2nd", "num": 2, "time": "11:30", "team": "PIT", "scorer": "Malkin", "full": "Evgeni Malkin",
         "total": 7, "headshot": HEAD.format("PIT", 8471215), "assists": [{"name": "Letang", "num": 5}],
         "strength": "ev", "en": False, "away": 2, "home": 1},
    ]
    if final:
        goals.append({"period": "3rd", "num": 3, "time": "19:02", "team": "PIT", "scorer": "Crosby",
                      "full": "Sidney Crosby", "total": 10, "headshot": "", "assists": [], "strength": "ev",
                      "en": True, "away": 3, "home": 1})
    periods = [{"label": "1st", "away": 1, "home": 0}, {"label": "2nd", "away": 1, "home": 1}]
    shots = [{"label": "1st", "away": 12, "home": 7}, {"label": "2nd", "away": 10, "home": 11}]
    if final:
        periods.append({"label": "3rd", "away": 1, "home": 0})
        shots.append({"label": "3rd", "away": 9, "home": 13})
    ta, th = sum(p["away"] for p in periods), sum(p["home"] for p in periods)
    return {
        "periods": periods, "totals": {"away": ta, "home": th}, "shots": shots,
        "stats": [{"key": "sog", "label": "Shots", "away": sum(s["away"] for s in shots), "home": sum(s["home"] for s in shots)},
                  {"key": "powerPlay", "label": "Power play", "away": "1/3", "home": "0/2"},
                  {"key": "faceoffWinningPctg", "label": "Faceoffs", "away": 0.547, "home": 0.453},
                  {"key": "hits", "label": "Hits", "away": 18, "home": 24},
                  {"key": "blockedShots", "label": "Blocked shots", "away": 11, "home": 9},
                  {"key": "pim", "label": "Penalty minutes", "away": 4, "home": 6}],
        "goals": goals,
        "stars": [{"star": 1, "name": "S. Crosby", "team": "PIT", "headshot": HEAD.format("PIT", 8471675), "pos": "C", "line": "1G 1A"},
                  {"star": 2, "name": "T. Jarry", "team": "PIT", "headshot": HEAD.format("PIT", 8477465), "pos": "G", "line": ".943 SV%"},
                  {"star": 3, "name": "T. Konecny", "team": "PHI", "headshot": "", "pos": "R", "line": "1G 0A"}] if final else [],
        "penalties": [] if final else [{"team": "PHI", "player": "Sanheim", "infraction": "Hooking", "left": "1:34"}],
        "lineups": {"away": demo_lineup(PIT_NAMES, 1), "home": demo_lineup(PHI_NAMES, 2)},
    }


# HockeyTech team ids, for real logos in the demo (from the leagues' own pages).
DEMO_IDS = {"ECHL": {"FLA": 8, "JAX": 79, "ORL": 61, "SAV": 102, "SC": 18, "ATL": 10},
            "AHL": {"SPR": 411}}   # real data uses the feed's own ids for every team


def demo_logo(league, code):
    tid = DEMO_IDS.get(league, {}).get(code)
    return f"https://assets.leaguestat.com/{league.lower()}/logos/{tid}.png" if tid else ""


def aff_game(league, a, h, sa, sh, st, per=None, clk=None, start=None, ours="WBS"):
    start = start or datetime.now(timezone.utc)
    side = lambda c, s, n: {"abbrev": c, "id": c, "name": n, "city": "", "score": s, "sog": None, "logo": demo_logo(league, c), "league": league}
    names = {"WBS": "Penguins", "HER": "Bears", "LV": "Phantoms", "FLA": "Everblades", "ORL": "Solar Bears", "JAX": "Icemen"}
    g = {"id": f"{a}{h}", "league": league, "state": st, "start": start.isoformat(),
         "away": side(a, sa, names.get(a, a)), "home": side(h, sh, names.get(h, h)),
         "period": per, "periodType": "REG", "clock": clk, "intermission": False, "situation": None,
         "lastPeriodType": "REG", "statusText": "", "goals": []}
    if st == "LIVE":
        g["away"]["sog"], g["home"]["sog"] = 19, 14
        g["goals"] = [{"period": "1st", "num": 1, "time": "06:12", "team": ours, "scorer": "Pickering", "total": None,
                       "assists": [], "strength": "pp", "en": False, "away": 1 if a == ours else 0, "home": 1 if h == ours else 0}]
    return g


def affiliates(kind, now):
    tonight = now.replace(hour=23, minute=0, second=0, microsecond=0)
    wbs_div = {"title": "Atlantic Division", "rows": [
        {"abbrev": c, "name": n, "logo": demo_logo("AHL", c), "gp": 14, "w": w, "l": 14 - w - o, "otl": o, "pts": 2 * w + o}
        for c, n, w, o in [("PRO", "Providence Bruins", 10, 1), ("WBS", "Wilkes-Barre/Scranton Penguins", 9, 2),
                           ("HER", "Hershey Bears", 8, 1), ("CLT", "Charlotte Checkers", 7, 2), ("LV", "Lehigh Valley Phantoms", 6, 2),
                           ("SPR", "Springfield Thunderbirds", 6, 1), ("BRI", "Bridgeport Islanders", 5, 2), ("HFD", "Hartford Wolf Pack", 4, 2)]]}
    fla_div = {"title": "South Division", "rows": [
        {"abbrev": c, "name": n, "logo": demo_logo("ECHL", c), "gp": 12, "w": w, "l": 12 - w - o, "otl": o, "pts": 2 * w + o}
        for c, n, w, o in [("FLA", "Florida Everblades", 9, 1), ("ORL", "Orlando Solar Bears", 7, 2), ("JAX", "Jacksonville Icemen", 6, 1),
                           ("SAV", "Savannah Ghost Pirates", 5, 2), ("SC", "South Carolina Stingrays", 5, 1), ("ATL", "Atlanta Gladiators", 4, 2)]]}
    live = kind in ("affiliate", "live")
    wbs_live = aff_game("AHL", "WBS", "HER", 2, 1, "LIVE", 2, "07:45") if live else None
    fla_live = aff_game("ECHL", "ORL", "FLA", 1, 3, "LIVE", 3, "12:02", ours="FLA") if kind in ("affiliate", "echl") else None
    wbs_final = aff_game("AHL", "LV", "WBS", 2, 4, "FINAL", start=now - timedelta(hours=3))
    fla_next = aff_game("ECHL", "FLA", "JAX", None, None, "FUT", start=tonight, ours="FLA")
    return [
        {"league": "AHL", "code": "WBS", "name": "Wilkes-Barre/Scranton Penguins", "nickname": "Penguins", "logo": demo_logo("AHL", "WBS"),
         "live": wbs_live, "today": [wbs_live] if wbs_live else [wbs_final], "yesterday": [wbs_final],
         "last": wbs_final, "next": aff_game("AHL", "WBS", "PRO", None, None, "FUT", start=now + timedelta(days=2)),
         "standings": wbs_div, "leaders": [{"name": "Ville Koivunen", "g": 7, "a": 10, "pts": 17},
                                           {"name": "Tristan Broz", "g": 6, "a": 7, "pts": 13}]},
        {"league": "ECHL", "code": "FLA", "name": "Florida Everblades", "nickname": "Everblades", "logo": demo_logo("ECHL", "FLA"),
         "live": fla_live, "today": [fla_live] if fla_live else [fla_next], "yesterday": [],
         "last": aff_game("ECHL", "SAV", "FLA", 2, 5, "FINAL", start=now - timedelta(days=2), ours="FLA"),
         "next": None if fla_live else fla_next, "standings": fla_div, "leaders": []},
    ]


def extras(kind, now):
    logo = lambda a: f"https://assets.nhle.com/logos/nhl/svg/{a}_dark.svg"
    out = {
        "injuries": [{"name": "Bryan Rust", "pos": "RW", "status": "Day-To-Day", "injury": "Upper body", "back": None},
                     {"name": "Kris Letang", "pos": "D", "status": "Injured Reserve", "injury": "Lower body",
                      "back": (now + timedelta(days=12)).date().isoformat()}],
        "opp_injuries": [{"name": "Logan Couture", "pos": "C", "status": "Out", "injury": "Groin", "back": None}],
        "transactions": [
            {"date": (now - timedelta(days=d)).date().isoformat(), "tag": t, "text": x} for d, t, x in [
                (0, "NHL", "Recalled F Ville Koivunen from Wilkes-Barre/Scranton (AHL)."),
                (1, "ECHL", "Gabriel D'Aigle (G): Assigned from Pittsburgh Penguins"),
                (2, "NHL", "Placed D Kris Letang on injured reserve."),
                (3, "AHL", "Tristan Broz: Reassigned by Pittsburgh to Wilkes-Barre/Scranton")]],
        "prospects": [
            {"name": n, "pos": p, "headshot": "", "league": lg, "team": tm, "gp": gp, "g": g_, "a": a_, "pts": g_ + a_}
            for n, p, lg, tm, gp, g_, a_ in [("Ben Kindel", "C", "WHL", "Calgary Hitmen", 18, 12, 19),
                                             ("Tanner Howe", "LW", "AHL", "Wilkes-Barre/Scranton", 14, 5, 6),
                                             ("Harrison Brunicke", "D", "WHL", "Kamloops Blazers", 17, 4, 15)]]
            + [{"name": "Sergei Murashov", "pos": "G", "headshot": "", "league": "AHL", "team": "Wilkes-Barre/Scranton",
                "gp": 9, "goalie": True, "w": 6, "gaa": 2.41, "svp": 0.918}],
        "on_this_day": ["1988: Mario Lemieux scores five goals five different ways against New Jersey",
                        "1995: Penguins beat NYR 7-2"],
        "lineup": None, "playoffs": None, "offseason": None,
    }
    if kind == "gameday":
        out["lineup"] = {"game": hash(("PIT", "SJS")),
                         "away": {"confirmed": False, "goalies": [{"name": "Tristan Jarry", "record": "5-5-1", "gaa": 3.01, "svp": 0.902}]},
                         "home": {"confirmed": False, "goalies": [{"name": "Yaroslav Askarov", "record": "4-7-1", "gaa": 3.20, "svp": 0.897}]}}
    if kind == "playoffs":
        ser = lambda t, tw, b, bw, txt: {"letter": "", "round": 1, "label": "1st-round", "need": 4, "text": txt,
                                         "top": {"abbrev": t, "wins": tw, "logo": logo(t)}, "bottom": {"abbrev": b, "wins": bw, "logo": logo(b)}}
        series = [ser("CAR", 3, "PIT", 2, "CAR leads 3-2"), ser("FLA", 2, "TBL", 2, "Series tied 2-2"),
                  ser("WSH", 4, "MTL", 1, "WSH wins 4-1"), ser("TOR", 3, "OTT", 1, "TOR leads 3-1"),
                  ser("WPG", 2, "STL", 3, "STL leads 3-2"), ser("DAL", 3, "COL", 3, "Series tied 3-3"),
                  ser("VGK", 4, "MIN", 0, "VGK wins 4-0"), ser("EDM", 2, "LAK", 1, "EDM leads 2-1")]
        br = lambda l, t, tw, b, bw: {"letter": l, "need": 4, "top": {"abbrev": t, "wins": tw, "logo": logo(t)},
                                      "bottom": {"abbrev": b, "wins": bw, "logo": logo(b)}, "text": ""}
        bracket = {
            "A": br("A", "FLA", 4, "TBL", 2), "B": br("B", "TOR", 4, "OTT", 3), "C": br("C", "WSH", 4, "MTL", 1),
            "D": br("D", "CAR", 4, "PIT", 3), "E": br("E", "WPG", 4, "STL", 3), "F": br("F", "DAL", 4, "COL", 2),
            "G": br("G", "VGK", 4, "MIN", 0), "H": br("H", "EDM", 4, "LAK", 2),
            "I": br("I", "FLA", 2, "TOR", 1), "J": br("J", "WSH", 1, "CAR", 2),
            "K": br("K", "WPG", 0, "DAL", 1), "L": br("L", "VGK", 1, "EDM", 1)}
        from extras import series_text
        for s in bracket.values():
            s["text"] = series_text(None, s["top"]["abbrev"], s["top"]["wins"], s["bottom"]["abbrev"], s["bottom"]["wins"])
        out["playoffs"] = {"round": 2, "label": "2nd-round", "series": series, "ours": series[0], "bracket": bracket}
    if kind == "offseason":
        y = now.year
        out["offseason"] = {"events": [
            {"label": "NHL Draft", "date": (now + timedelta(days=9)).date().isoformat(), "estimated": True},
            {"label": "Free agency opens", "date": (now + timedelta(days=16)).date().isoformat()},
            {"label": "Opening night", "date": (now + timedelta(days=118)).isoformat(), "opp": "NYR", "home": True}]}
    return out


def run(kind, state, lock):
    now = datetime.now(timezone.utc)
    tonight = now.replace(hour=23, minute=0, second=0, microsecond=0)
    others = [game("BOS", "TOR", 2, 3, "FINAL"), game("EDM", "VGK", 1, 1, "LIVE", 2, "08:41"),
              game("NYR", "NJD", None, None, "FUT", start=tonight), game("COL", "DAL", 4, 2, "FINAL"),
              game("SEA", "LAK", None, None, "FUT", start=tonight), game("CHI", "STL", 0, 2, "CRIT", 3, "01:12")]
    pens = game("PIT", "PHI", 2, 1, "LIVE", 2, "14:27")
    pens["away"]["name"], pens["home"]["name"] = "Penguins", "Flyers"
    pens["away"]["sog"], pens["home"]["sog"] = 22, 18
    pens["situation"] = {"pp": "PIT", "en": None, "time": "1:34"}
    upcoming = [{"start": (now + timedelta(days=d)).replace(hour=23, minute=0).isoformat(), "away": a, "home": h}
                for d, a, h in [(2, "PIT", "SJS"), (4, "PIT", "LAK"), (5, "PIT", "ANA"), (7, "WSH", "PIT"), (9, "PIT", "NYR")]]
    form = [{"r": r, "opp": "XXX", "us": 0, "them": 0} for r in ["L", "L", "W", "OTL", "L", "W", "L", "W", "L", "L"]]
    leaders = {
        "skaters": [{"name": n, "pos": p, "headshot": HEAD.format("PIT", i), "gp": 18, "g": g_, "a": a_, "pts": g_ + a_}
                    for n, p, i, g_, a_ in [("Sidney Crosby", "C", 8471675, 9, 12), ("Evgeni Malkin", "C", 8471215, 6, 11),
                                            ("Bryan Rust", "R", 8475810, 8, 6), ("Erik Karlsson", "D", 8474578, 2, 11),
                                            ("Rickard Rakell", "R", 8476483, 6, 5)]],
        "goalies": [{"name": "Tristan Jarry", "headshot": "", "gp": 11, "w": 5, "l": 5, "otl": 1, "svp": 0.902, "gaa": 3.01},
                    {"name": "Joel Blomqvist", "headshot": "", "gp": 8, "w": 3, "l": 4, "otl": 1, "svp": 0.895, "gaa": 3.22}],
    }
    league = {
        "points": [{"name": n, "team": t, "headshot": "", "value": v} for n, t, v in
                   [("Connor McDavid", "EDM", 31), ("Nikita Kucherov", "TBL", 29), ("Nathan MacKinnon", "COL", 28), ("Leon Draisaitl", "EDM", 26)]],
        "goals": [{"name": n, "team": t, "headshot": "", "value": v} for n, t, v in
                  [("Auston Matthews", "TOR", 15), ("Leon Draisaitl", "EDM", 14), ("Kyle Connor", "WPG", 13)]],
        "wins": [{"name": n, "team": t, "headshot": "", "value": v} for n, t, v in
                 [("Connor Hellebuyck", "WPG", 12), ("Igor Shesterkin", "NYR", 11), ("Ilya Sorokin", "NYI", 10)]],
    }
    news = [{"title": t, "source": s} for t, s in [
        ("Crosby moves into the top 10 all-time in assists", "NHL.com"),
        ("Penguins recall forward from Wilkes-Barre/Scranton", "Pittsburgh Post-Gazette"),
        ("Malkin's power-play goal lifts Pens past Flyers", "TribLIVE"),
        ("What the Penguins need to fix on the penalty kill", "The Athletic")]]

    opponent = {"abbrev": "SJS", "start": tonight.isoformat(),
                "h2h": [{"r": "W", "opp": "SJS", "us": 4, "them": 2, "start": (now - timedelta(days=20)).isoformat()}],
                "scorers": [{"name": n, "headshot": "", "g": g_, "a": a_, "pts": g_ + a_}
                            for n, g_, a_ in [("Macklin Celebrini", 8, 12), ("William Eklund", 6, 9), ("Will Smith", 5, 8)]]}
    milestones = [{"name": "Sidney Crosby", "headshot": HEAD.format("PIT", 8471675), "stat": "points", "value": 1696, "target": 1700, "left": 4},
                  {"name": "Evgeni Malkin", "headshot": HEAD.format("PIT", 8471215), "stat": "games", "value": 1294, "target": 1300, "left": 6},
                  {"name": "Kris Letang", "headshot": "", "stat": "assists", "value": 595, "target": 600, "left": 5}]

    with lock:
        state.update(extras(kind, now))
        state["affiliates"] = affiliates(kind, now) if kind != "offseason" else []
        table = standings()
        if kind == "midseason":            # past the halfway mark, so the projected bracket shows
            for t in table:
                t["gp"] *= 3; t["w"] *= 3; t["l"] *= 3; t["otl"] *= 3; t["pts"] *= 3
        state.update(standings=table, upcoming=upcoming, form=form, leaders=leaders,
                     league_leaders=league, news=news, milestones=milestones,
                     opponent=opponent if kind == "gameday" else None, updated=now.isoformat())
    while True:
        with lock:
            state["updated"] = datetime.now(timezone.utc).isoformat()
            if kind == "live":
                pens["away"]["sog"] += random.choice([0, 0, 1])
                if random.random() < 0.25:
                    pens["away"]["score"] += 1
                    state["goal_seq"] += 1
                state["goal_info"] = {"count": pens["away"]["score"], "name": "Evgeni Malkin", "num": 7,
                                      "headshot": HEAD.format("PIT", 8471215), "strength": "pp",
                                      "assists": [{"name": "Crosby", "num": 12}, {"name": "Letang", "num": 5}]}
                state.update(mode="live", game=dict(pens), details=details(), scores=others + [pens])
            elif kind in ("intermission", "final"):
                g = dict(pens)
                if kind == "intermission":
                    g.update(intermission=True, clock="14:22", situation=None)
                else:
                    g["away"] = dict(g["away"], score=3); g.update(state="FINAL", situation=None)
                state.update(mode="live" if kind == "intermission" else "final", game=g,
                             details=details(final=kind == "final"), scores=others + [g])
            elif kind == "shootout":
                so = state.get("_so", [])
                order = [("PIT", "Crosby"), ("PHI", "Konecny"), ("PIT", "Malkin"), ("PHI", "Michkov"),
                         ("PIT", "Rakell"), ("PHI", "Couturier")]
                if len(so) < len(order):
                    team, name = order[len(so)]
                    goal = random.random() < 0.4
                    so = so + [{"seq": len(so) + 1, "team": team, "name": name, "full": name, "headshot": "",
                                "shot": random.choice(["wrist", "snap", "backhand"]), "goal": goal,
                                "result": "goal" if goal else random.choice(["save", "miss"]), "winner": False}]
                state["_so"] = so
                g = dict(pens)
                g.update(period=5, periodType="SO", clock="00:00", situation=None)
                g["away"] = dict(g["away"], score=2); g["home"] = dict(g["home"], score=2)
                det = details(); det["shootout"] = so; det["penalties"] = []
                state.update(mode="live", game=g, details=det, scores=others + [g])
            elif kind == "playoffs":
                pg = dict(pens)
                pg["series"] = {"text": "CAR leads 3-2", "game": 6, "round": 1, "title": "1st Round"}
                pg["home"] = dict(pg["home"], abbrev="CAR", name="Hurricanes", logo=logo("CAR"))
                state.update(mode="live", game=pg, details=details(), scores=others + [pg])
            elif kind == "offseason":
                state.update(mode="off", game=None, scores=[], upcoming=[], last_night=[])
            elif kind == "echl":
                if random.random() < 0.2:
                    fla = state["affiliates"][1]["live"]
                    fla["home"]["score"] += 1
                    state["aff_goal_seq"] += 1
                    state["aff_goal"] = {"team": "FLA", "league": "ECHL", "us": fla["home"]["score"],
                                         "them": fla["away"]["score"], "opp": "ORL"}
                state.update(mode="off", game=None, scores=others)
            elif kind == "affiliate":
                if random.random() < 0.2:
                    wbs = state["affiliates"][0]["live"]
                    wbs["away"]["score"] += 1
                    state["aff_goal_seq"] += 1
                    state["aff_goal"] = {"team": "WBS", "league": "AHL", "us": wbs["away"]["score"],
                                         "them": wbs["home"]["score"], "opp": "HER"}
                state.update(mode="off", game=None, scores=others)
            elif kind == "gameday":
                today = game("PIT", "SJS", None, None, "FUT", start=tonight)
                today["away"]["name"], today["home"]["name"] = "Penguins", "Sharks"
                state.update(mode="off", game=today, scores=others + [today])
            else:                          # off, midseason
                state.update(mode="off", game=None, scores=others)
        time.sleep(10)
