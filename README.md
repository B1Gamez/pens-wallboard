# Pens Wallboard

A wall display that shows a full-screen Penguins scoreboard during games and
league scores plus rotating standings the rest of the time.

## What it shows

- **Pens game today, within 90 min of puck drop:** matchup, puck-drop time and TV channel
- **Pens game live:** score, period, clock, shots, power play / empty net, penalty box, recent goals, and a goal screen with the scorer when the Pens score
- **Intermissions:** line score (goals and shots by period), team stats, and the scoring summary
- **Pens game ended:** final with line score, team stats and the three stars, for 30 minutes
- **Otherwise:** today's scores (yesterday's before noon), a rotating panel (Metro, Pens leaders, wild card race, league leaders, other divisions), a Pens news ticker, the next five games, the record, playoff-race gap and last-10 form

## Try it on any computer first

    pip install -r requirements.txt
    DEMO=live python3 app.py     # fake Pens game, goals happen randomly
    DEMO=off  python3 app.py     # fake off-day screen
    DEMO=gameday python3 app.py  # fake game-day screen
    DEMO=intermission python3 app.py
    DEMO=final python3 app.py
    DEMO=affiliate python3 app.py   # WBS and Everblades live, no Pens game
    DEMO=echl python3 app.py        # Everblades live on their own
    DEMO=playoffs python3 app.py    # playoff game and bracket
    DEMO=offseason python3 app.py   # summer countdowns, prospects, history
    python3 app.py               # real NHL data

Open http://localhost:8080 and press F11.

## Raspberry Pi setup

Use Raspberry Pi OS with desktop (64-bit). Username `pi` is assumed; change paths if yours differs.

    # copy this folder to /home/pi/pens-wallboard, then:
    cd ~/pens-wallboard
    python3 -m venv venv && venv/bin/pip install -r requirements.txt
    sudo cp pens-wallboard.service /etc/systemd/system/
    sudo systemctl enable --now pens-wallboard

Open the browser full screen on boot by adding this line to `~/.config/labwc/autostart`
(create the file if needed; the binary may be `chromium` or `chromium-browser` depending on OS version):

    chromium --kiosk --noerrdialogs --disable-infobars --incognito http://localhost:8080 &

Turn off screen blanking: `sudo raspi-config` > Display Options > Screen Blanking > No.

## Settings (environment variables in the service file)

| Variable | Default | What it does |
|---|---|---|
| `TEAM` | `PIT` | Team to follow |
| `PREGAME_MINUTES` | `90` | How early the scoreboard takes over |
| `POSTGAME_MINUTES` | `30` | How long the final stays up |
| `GOAL_HOOK_URL` | none | URL that gets a POST when your team scores |
| `GOAL_HOOK_CMD` | none | Shell command run when your team scores |
| `RECAP_UNTIL_HOUR` | `12` | Show last night's results until this hour |
| `NEWS` | `on` | Set to `off` to hide the news ticker |
| `NEWS_QUERY` | `Pittsburgh Penguins` | What the news ticker searches for |
| `NEWS_MAX_HOURS` | `48` | Skip headlines older than this |
| `NIGHT` | `on` | Set to `off` to keep the full board up overnight |
| `NIGHT_START` / `NIGHT_END` | `1` / `8` | Local hours for the dimmed night clock |
| `GOAL_HORN` | `on` | Set to `off` to silence the goal horn |
| `HORN_VOLUME` | `0.6` | Horn volume, 0.0 to 1.0 |
| `HORN_MAX_SECONDS` | `0` | Fade out a custom horn after this many seconds (0 = full length) |
| `AFFILIATES` | `ahl:Wilkes-Barre,echl:Florida Everblades` | Minor-league teams to follow, as league:name |
| `AFFILIATE_TAKEOVER` | `on` | A live affiliate game fills the screen when the Pens aren't playing |
| `AFFILIATE_HORN` / `AFFILIATE_HORN_VOLUME` | `on` / same as `HORN_VOLUME` | Affiliate horns (`static/horn-ahl.mp3`, `static/horn-echl.mp3`); they only play when that team is the only one of ours playing |
| `AFFILIATE_HOOKS` | `off` | Also send goal hooks for affiliate goals (with the team code) |
| `AFFILIATE_NEWS` | `on` | Add affiliate headlines to the ticker |
| `DRAFT_DATE` | last Friday of June (estimated) | NHL Draft date for the offseason countdown, e.g. `2027-06-25` |
| `FREE_AGENCY_DATE` | July 1 | Free agency date for the offseason countdown |
| `PORT` | `8080` | Web port |

## Goal horn and test goals

- The board plays a built-in horn on goals. To use your own sound, put an MP3 at `static/horn.mp3`.
- The kiosk browser needs `--autoplay-policy=no-user-gesture-required` or it will block the sound.
- Trigger a test goal (screen, horn and goal hooks) from any computer:
  `curl -X POST http://<server-ip>:8080/api/test-goal` (add `?team=WBS` to test an affiliate goal)

## Playoffs, injuries, transactions, prospects, history

- **Playoff mode** turns on by itself when playoff games are being played: bracket view, series status on the scoreboard, tiles and bottom bar. AHL and ECHL series show in the affiliate views.
- **Injuries** and **NHL transactions** come from ESPN's public feed; **ECHL transactions** from echl.com; AHL transactions are best effort.
- **Goalies**: season numbers before a game, confirmed starters once it begins (NHL), starters for affiliate games when their feed lists lineups.
- **Prospect watch** refreshes twice a day from the NHL's prospect list.
- **On this day**: on first start the server downloads every past Penguins result once (a few minutes, saved in `data/history_games.json`). Add your own moments in `data/history_events.json`, e.g. `{"03-15": ["1995: Something happened"]}`.
- **Offseason mode** turns on when there's been no Penguins game for 10 days and none is coming within 10 days.

## Notes

- Keep `affiliates.py`, `extras.py` and `demo.py` next to `app.py`; it's only used when `DEMO` is set.
- News headlines come from Google News search results for `NEWS_QUERY`.

- Data comes from the NHL's public but undocumented API (api-web.nhle.com). It can change without notice; if something breaks, check https://github.com/Zmalski/NHL-API-Reference.
- The feed runs 10 to 30+ seconds behind the TV broadcast, so the goal screen will trail what you see on the TV.
- A goal that gets overturned just lowers the score on the next update; it won't trigger anything.

## Disclaimer

This is a personal fan project, not affiliated with the NHL, AHL, ECHL or any team.
Data comes from public but unofficial feeds (NHL, HockeyTech, ESPN, echl.com, Google News)
that can change without notice. Team names and logos belong to their owners; logos are
loaded from the leagues' own servers and are not included in this repository. Goal horn
audio isn't included either: add your own MP3s to `static/` (see "Goal horn and test goals").
