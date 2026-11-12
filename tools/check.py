"""
Quick checks before a release: every Python file compiles, the server starts,
and the page and API respond. Run with: python tools/check.py
"""
import os
import py_compile
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)
os.environ.pop("DEMO", None)

failed = False
for f in ("app.py", "affiliates.py", "extras.py", "demo.py"):
    try:
        py_compile.compile(f, doraise=True)
    except py_compile.PyCompileError as e:
        print(f"FAIL  {f} has a syntax error:\n{e.msg}")
        failed = True
if failed:
    sys.exit(1)

import tempfile  # noqa: E402

import app  # noqa: E402

app.SETTINGS_FILE = os.path.join(tempfile.gettempdir(), "pens-wallboard-check.json")   # don't touch your real setting

client = app.app.test_client()
checks = [
    ("API responds", lambda: client.get("/api/state").status_code == 200),
    ("API has the expected fields", lambda: {"mode", "scores", "standings", "config"} <= set(client.get("/api/state").get_json())),
    ("Page loads", lambda: client.get("/").status_code == 200 and b"</html>" in client.get("/").data),
    ("Test goals blocked from the internet",
     lambda: client.post("/api/test-goal", headers={"Cf-Connecting-Ip": "203.0.113.5"}).status_code == 403),
    ("Delay can be changed at home",
     lambda: client.post("/api/delay?seconds=0", environ_base={"REMOTE_ADDR": "192.168.1.20"}).get_json()["delay"] == 0),
    ("Delay can't be changed from the internet",
     lambda: client.post("/api/delay?seconds=30", headers={"Cf-Connecting-Ip": "203.0.113.5"}).status_code == 403),
    ("Updates can't be triggered from the internet",
     lambda: client.post("/api/update", headers={"Cf-Connecting-Ip": "203.0.113.5"}).status_code == 403),
    ("Remote blocked from the internet",
     lambda: client.get("/remote", headers={"Cf-Connecting-Ip": "203.0.113.5"}).status_code == 403),
    ("Remote controls blocked from the internet",
     lambda: client.post("/api/control", json={"horn_muted": True}, headers={"Cf-Connecting-Ip": "203.0.113.5"}).status_code == 403),
    ("Remote page loads at home", lambda: client.get("/remote", environ_base={"REMOTE_ADDR": "192.168.1.20"}).status_code == 200),
    ("Test goals allowed at home",
     lambda: client.post("/api/test-goal", environ_base={"REMOTE_ADDR": "192.168.1.20"}).status_code == 200),
]
for name, test in checks:
    try:
        ok = test()
    except Exception as e:
        ok, name = False, f"{name} ({e})"
    print(("ok    " if ok else "FAIL  ") + name)
    failed |= not ok

sys.exit(1 if failed else 0)
