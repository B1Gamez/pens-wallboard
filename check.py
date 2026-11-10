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

import app  # noqa: E402

client = app.app.test_client()
checks = [
    ("API responds", lambda: client.get("/api/state").status_code == 200),
    ("API has the expected fields", lambda: {"mode", "scores", "standings", "config"} <= set(client.get("/api/state").get_json())),
    ("Page loads", lambda: client.get("/").status_code == 200 and b"</html>" in client.get("/").data),
]
for name, test in checks:
    try:
        ok = test()
    except Exception as e:
        ok, name = False, f"{name} ({e})"
    print(("ok    " if ok else "FAIL  ") + name)
    failed |= not ok

sys.exit(1 if failed else 0)
