#!/usr/bin/env python3
"""Make oMLX's keyless-access rule depend on *which* address you bind to.

Stock oMLX allows "Skip API key verification" only when every bind host is
loopback, so the admin UI becomes unreachable without a key the moment you
bind to a LAN address for your phone.  Binding to a specific LAN address is
meaningfully lower risk than 0.0.0.0, because that address only exists on the
network you configured it for -- join a coffee shop network and the machine no
longer holds it.  This patch encodes that distinction.

Policy after patching:

  * Keyless allowed  -- every bind host is one you only hold on a network you
    chose: loopback, RFC1918 (10/8, 172.16/12, 192.168/16), link-local,
    CGNAT 100.64/10 (Tailscale), IPv6 ULA/link-local.
  * Key required     -- any host is 0.0.0.0 or :: (listens on every interface,
    including networks you did not choose), or is globally routable, or is a
    hostname we cannot classify without resolving it.
  * Starts anyway    -- a bind to an address this machine does not currently
    hold is skipped with a warning instead of aborting startup, so oMLX still
    runs local-only when you are away from home.

Three edits:

  omlx/utils/network.py   is_loopback_bind()  -- the predicate every backend
                          call site funnels through (startup validation,
                          settings validation, verify_api_key, require_admin,
                          admin login redirect, CLI host auto-reset), and the
                          early-out inside network_auth_error()
  omlx/cli.py             the bind loop -- tolerate unavailable addresses
  admin/static/js/dashboard.js  isLoopbackBindHost() -- mirror the predicate so
                          the toggle greys out at 0.0.0.0 and nowhere else

Usage:
  python3 omlx-netpolicy-patch.py --status
  python3 omlx-netpolicy-patch.py --apply
  python3 omlx-netpolicy-patch.py --revert
"""

from __future__ import annotations

import argparse
import re
import shutil
import sys
from pathlib import Path

APP = Path("/Applications/oMLX.app")
RES = APP / "Contents/Resources/omlx"
BAK_SUFFIX = ".omlx-netpolicy.bak"
MARK = "omlx-netpolicy-patch"

# --------------------------------------------------------------------------
# 1. Backend predicate
# --------------------------------------------------------------------------

NET_ANCHOR = re.compile(
    r'(def is_loopback_bind\(value: str\) -> bool:\n'
    r'    """[^"]*"""\n)'
)

NET_INSERT = f'''
    # --- {MARK} BEGIN ---
    # Keyless access is allowed only for addresses you hold on a network you
    # chose.  0.0.0.0 and :: are refused: they follow you onto every network
    # you join.  Globally routable addresses are refused: a public IP is the
    # coffee shop, permanently.  Bare hostnames are refused because resolving
    # them would vary by network.  CGNAT 100.64/10 is listed explicitly --
    # Python reports Tailscale addresses as neither private nor global.
    import ipaddress as _ip

    def _omlx_keyless_ok(host: str) -> bool:
        candidate = host.strip()
        if not candidate:
            return False
        if candidate.rstrip(".").lower() == "localhost":
            return True
        try:
            address = _ip.ip_address(candidate.strip("[]").split("%")[0])
        except ValueError:
            return False
        if address.is_unspecified:
            return False
        mapped = getattr(address, "ipv4_mapped", None)
        if mapped is not None:
            address = mapped
        if address.is_loopback or address.is_link_local:
            return True
        if isinstance(address, _ip.IPv4Address) and address in _ip.ip_network(
            "100.64.0.0/10"
        ):
            return True
        return bool(address.is_private and not address.is_global)

    if isinstance(value, str):
        _hosts = [part.strip() for part in value.split(",") if part.strip()]
        return bool(_hosts) and all(_omlx_keyless_ok(h) for h in _hosts)
    # --- {MARK} END ---
'''

# --------------------------------------------------------------------------
# 2. Tolerant bind
# --------------------------------------------------------------------------

CLI_OLD = (
    '    serve_sockets = [uvicorn_config.bind_socket()]\n'
    '    for h in bind_hosts[1:]:\n'
    '        extra_cfg = uvicorn.Config(\n'
    '            "omlx.server:app",\n'
    '            host=h,\n'
    '            port=settings.server.port,\n'
    '            log_level=uvicorn_level,\n'
    '            access_log=show_access_log,\n'
    '        )\n'
    '        serve_sockets.append(extra_cfg.bind_socket())'
)

CLI_NEW = f'''    # --- {MARK} BEGIN --- tolerate addresses this machine does not hold
    # uvicorn's bind_socket() calls sys.exit() on a bind error, and stock oMLX
    # lets that kill startup.  That means a Host of "127.0.0.1,192.168.x.y"
    # refuses to run at all on any other network -- even local-only.  Skip the
    # hosts that cannot bind, warn loudly so a DHCP change at home does not
    # look like a silent failure, and give up only if none of them bind.
    serve_sockets = []
    _omlx_bound, _omlx_skipped = [], []
    for _host in bind_hosts:
        _cfg = uvicorn.Config(
            "omlx.server:app",
            host=_host,
            port=settings.server.port,
            log_level=uvicorn_level,
            access_log=show_access_log,
        )
        try:
            serve_sockets.append(_cfg.bind_socket())
        except SystemExit:
            _omlx_skipped.append(_host)
            print(
                f"WARNING: cannot bind {{_host}}:{{settings.server.port}} -- skipping it. "
                "No interface on this machine holds that address right now "
                "(different network? DHCP lease changed?), or the port is taken."
            )
    if not serve_sockets:
        print(
            "ERROR: none of the configured hosts could be bound ("
            + ", ".join(bind_hosts)
            + "). Set Host to 127.0.0.1 in Settings to run local-only."
        )
        raise SystemExit(3)
    if _omlx_skipped:
        _omlx_bound = [h for h in bind_hosts if h not in _omlx_skipped]
        print(
            "NOTE: serving on "
            + ", ".join(f"http://{{h}}:{{settings.server.port}}" for h in _omlx_bound)
            + " only; other devices cannot reach this server."
        )
    # --- {MARK} END ---'''

# --------------------------------------------------------------------------
# 3. UI mirror
# --------------------------------------------------------------------------

JS_ANCHOR = re.compile(r"(\n([ \t]*)isLoopbackBindHost\(value\) \{\n)")

JS_INSERT = """{i}// --- {m} BEGIN ---
{i}// Mirrors the patched backend policy in omlx/utils/network.py. The
{i}// backend is authoritative; this only decides whether the toggle is
{i}// offered, so it stays deliberately simple.
{i}const _omlxKeylessOk = (h) => {{
{i}    if (h.replace(/\\.+$/, '') === 'localhost') return true;
{i}    const bare = h.replace(/^\\[|\\]$/g, '').split('%')[0];
{i}    if (bare === '0.0.0.0' || bare === '::') return false;
{i}    const v4 = bare.match(/^(\\d{{1,3}})\\.(\\d{{1,3}})\\.(\\d{{1,3}})\\.(\\d{{1,3}})$/);
{i}    if (v4) {{
{i}        const o = v4.slice(1).map(Number);
{i}        if (o.some(n => n > 255)) return false;
{i}        if (o[0] === 127) return true;                       // loopback
{i}        if (o[0] === 10) return true;                        // RFC1918
{i}        if (o[0] === 192 && o[1] === 168) return true;       // RFC1918
{i}        if (o[0] === 172 && o[1] >= 16 && o[1] <= 31) return true;
{i}        if (o[0] === 169 && o[1] === 254) return true;       // link-local
{i}        if (o[0] === 100 && o[1] >= 64 && o[1] <= 127) return true;  // CGNAT
{i}        return false;
{i}    }}
{i}    if (!bare.includes(':')) return false;                   // hostname
{i}    if (/^::ffff:/i.test(bare)) return _omlxKeylessOk(bare.replace(/^::ffff:/i, ''));
{i}    if (bare === '::1') return true;                         // loopback
{i}    if (/^fe[89ab][0-9a-f]:/i.test(bare)) return true;       // fe80::/10
{i}    if (/^f[cd][0-9a-f]{{2}}:/i.test(bare)) return true;       // fc00::/7 ULA
{i}    return false;
{i}}};
{i}const _omlxHosts = String(value || '').split(',')
{i}    .map(h => h.trim().toLowerCase()).filter(Boolean);
{i}if (_omlxHosts.length) return _omlxHosts.every(_omlxKeylessOk);
{i}return false;
{i}// --- {m} END ---
"""


def targets() -> list[Path]:
    return [
        RES / "utils/network.py",
        RES / "cli.py",
        RES / "admin/static/js/dashboard.js",
    ]


def purge_pycache() -> None:
    for name in ("network", "cli"):
        for pyc in RES.rglob(f"__pycache__/{name}.*.pyc"):
            try:
                pyc.unlink()
            except OSError:
                pass


def _patch_text(path: Path, text: str) -> str:
    if path.name == "network.py":
        new, n = NET_ANCHOR.subn(lambda m: m.group(1) + NET_INSERT, text, count=1)
    elif path.name == "cli.py":
        if CLI_OLD not in text:
            n, new = 0, text
        else:
            new, n = text.replace(CLI_OLD, CLI_NEW, 1), 1
    else:
        new, n = JS_ANCHOR.subn(
            lambda m: m.group(1) + JS_INSERT.format(i=m.group(2) + "    ", m=MARK),
            text,
            count=1,
        )
    if n != 1:
        sys.exit(
            f"anchor not found in {path}\n"
            "oMLX changed upstream; the patch needs updating."
        )
    return new


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
        new = _patch_text(path, text)
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
            print(f"MISSING    {path}")
        else:
            mark = "PATCHED  " if MARK in path.read_text(encoding="utf-8") else "original "
            print(f"{mark}  {path}")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--apply", action="store_true")
    g.add_argument("--revert", action="store_true")
    g.add_argument("--status", action="store_true")
    a = ap.parse_args()
    sys.exit(apply() if a.apply else revert() if a.revert else status())
