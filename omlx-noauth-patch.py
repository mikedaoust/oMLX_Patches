#!/usr/bin/env python3
"""Disable oMLX's loopback-only restriction on "Skip API key verification".

oMLX refuses to run keyless unless every bind host is loopback. Two functions
enforce it everywhere:

  omlx/utils/network.py            is_loopback_bind()      (backend: startup
                                   validation, settings validation, admin auth,
                                   verify_api_key, CLI host auto-reset)
  omlx/admin/static/js/dashboard.js  isLoopbackBindHost()  (web UI: greyed-out
                                   toggle, warning text, pre-save guard)

This patches both to treat any non-empty host as loopback. Idempotent and
re-runnable after an oMLX update.

  python3 omlx-noauth-patch.py --status
  python3 omlx-noauth-patch.py --apply
  python3 omlx-noauth-patch.py --revert
"""

from __future__ import annotations

import argparse
import re
import shutil
import sys
from pathlib import Path

APP = Path("/Applications/oMLX.app")
RES = APP / "Contents/Resources/omlx"
BAK_SUFFIX = ".omlx-noauth.bak"
MARK = "omlx-noauth-patch"

PY_ANCHOR = re.compile(
    r'(def is_loopback_bind\(value: str\) -> bool:\n'
    r'    """[^"]*"""\n)'
)
PY_INSERT = (
    "\n"
    f"    # --- {MARK} BEGIN --- treat any non-empty bind host as loopback\n"
    "    if isinstance(value, str) and value.strip():\n"
    "        return True\n"
    f"    # --- {MARK} END ---\n"
)

JS_ANCHOR = re.compile(r"(\n([ \t]*)isLoopbackBindHost\(value\) \{\n)")
JS_INSERT = (
    "{i}// --- {m} BEGIN --- treat any non-empty bind host as loopback\n"
    "{i}if (String(value || '').trim()) return true;\n"
    "{i}// --- {m} END ---\n"
)


def targets() -> list[Path]:
    return [RES / "utils/network.py", RES / "admin/static/js/dashboard.js"]


def patched(path: Path) -> bool:
    return MARK in path.read_text(encoding="utf-8")


def purge_pycache() -> None:
    for pyc in RES.rglob("__pycache__/network.*.pyc"):
        try:
            pyc.unlink()
        except OSError:
            pass


def apply() -> int:
    if not RES.is_dir():
        sys.exit(f"oMLX resources not found at {RES}")
    changed = False
    for path in targets():
        if not path.is_file():
            sys.exit(f"missing: {path}")
        text = path.read_text(encoding="utf-8")
        if MARK in text:
            print(f"already patched: {path.name}")
            continue

        if path.suffix == ".py":
            new, n = PY_ANCHOR.subn(lambda m: m.group(1) + PY_INSERT, text, count=1)
        else:
            new, n = JS_ANCHOR.subn(
                lambda m: m.group(1) + JS_INSERT.format(i=m.group(2) + "    ", m=MARK),
                text,
                count=1,
            )
        if n != 1:
            sys.exit(
                f"anchor not found in {path} -- oMLX changed upstream; "
                "the patch needs updating."
            )

        bak = path.with_name(path.name + BAK_SUFFIX)
        if not bak.exists():
            shutil.copy2(path, bak)
        path.write_text(new, encoding="utf-8")
        print(f"patched: {path}  (backup: {bak.name})")
        changed = True

    if changed:
        purge_pycache()
        print("\nDone. Quit oMLX fully and relaunch, then hard-reload the")
        print("dashboard (Cmd-Shift-R) so the cached JS is replaced.")
    return 0


def revert() -> int:
    for path in targets():
        bak = path.with_name(path.name + BAK_SUFFIX)
        if bak.exists():
            shutil.copy2(bak, path)
            bak.unlink()
            print(f"reverted: {path}")
        elif path.is_file() and MARK in path.read_text(encoding="utf-8"):
            print(f"WARNING: no backup for {path}; still patched")
        else:
            print(f"not patched: {path.name}")
    purge_pycache()
    print("\nQuit and relaunch oMLX.")
    return 0


def status() -> int:
    for path in targets():
        if not path.is_file():
            print(f"MISSING   {path}")
        else:
            print(f"{'PATCHED  ' if patched(path) else 'original '} {path}")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--apply", action="store_true")
    g.add_argument("--revert", action="store_true")
    g.add_argument("--status", action="store_true")
    a = ap.parse_args()
    sys.exit(apply() if a.apply else revert() if a.revert else status())
