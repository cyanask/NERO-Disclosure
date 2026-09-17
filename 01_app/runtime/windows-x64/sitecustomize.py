from pathlib import Path
import json
import re
import site
base = Path(__file__).resolve().parent.parent
name = "packages"
active = base / "active-packages.json"
if active.exists():
    name = json.loads(active.read_text("utf-8"))["directory"]
    if not re.fullmatch(r"packages-[0-9a-f]{12}-[0-9a-f]{8}", name):
        raise ValueError("Invalid project package directory")
site.addsitedir(str(base / name))
