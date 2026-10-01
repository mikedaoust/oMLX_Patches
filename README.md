# oMLX Patches

Small, reversible patches for [oMLX](https://omlx.app) on macOS.

| Patch | What it does |
|---|---|
| `omlx-noauth-patch.py` | Lets you enable **Skip API key verification** while the server is bound to a non-loopback host (`0.0.0.0`, a LAN IP, a Tailscale IP), so the admin web UI and API are reachable from other machines without a key. |

---

## ⚠️ Read this before using the no-auth patch

**Do not expose a patched server to the internet.** No port forwarding, no
`0.0.0.0` on a VPS, no stuffing it through a tunnel with a public hostname. A
keyless oMLX on the open internet will be found by a scanner within hours, and
whoever finds it gets everything below. This patch is for a trusted private
network and nothing else.

That caveat aside, the annoyance it solves is real: when oMLX is a tool on your
own LAN, having to paste an API key into a phone browser to reach the
management UI is friction with no security payoff — the key is protecting your
living room from your living room.

So be clear-eyed about what "keyless" hands out. With the patch applied and the
toggle on, **anything that can reach the port has full access with no
credentials** — not just chat completions:

- the admin dashboard (model download, model **deletion**, settings)
- stored Responses and conversation history
- MCP tools, web search and web fetch, executed from your machine
- cluster/pairing endpoints if distributed inference is enabled

That is fine for a home LAN you control. It is *not* fine on coffee shop wifi,
a dorm or office network, a guest VLAN, or anywhere you would not hand a
stranger a terminal on the host.

### Choosing a Host value

The Host field in Settings has **Localhost**, **Open to all**, and a **Custom**
option with a free-text box. Custom accepts a comma-separated list. What you
put there decides how much this patch costs you:

| Host value | Who can reach the keyless UI | Phone on home wifi? | On an untrusted network |
|---|---|---|---|
| `127.0.0.1` | the Mac itself | ❌ | safe, but useless for a phone |
| `0.0.0.0` | **everything on whatever network you are joined to** | ✅ | ⚠️ exposed to strangers |
| `192.168.x.y` (your LAN IP) | everything on your home LAN | ✅ | ✅ **server refuses to start** |
| `127.0.0.1,192.168.x.y` | the Mac **and** your home LAN | ✅ | ✅ **server refuses to start** |
| `100.x.y.z` (Tailscale IP) | only your own signed-in devices | ✅ | ✅ not listening there at all |

#### Bind to your actual LAN IP — the zero-dependency option

Instead of `0.0.0.0`, put loopback plus your Mac's own LAN address in the
Custom box, e.g. `127.0.0.1,192.168.20.105`. On your home network this behaves exactly like `0.0.0.0`.
Join a coffee shop network, though, and your Mac no longer holds that address,
so the bind fails with `EADDRNOTAVAIL` — and oMLX **exits instead of
listening**. uvicorn's `bind_socket()` calls `sys.exit()` on a bind error and
oMLX does not fall back, so this fails closed by construction rather than by
obscurity.

Three things to know first:

- **Set a DHCP reservation for the Mac.** If your router hands it a different
  address later, oMLX stops starting at home with a confusing bind error.
- **Bind both, not just the LAN IP.** A bare `192.168.20.105` breaks local
  apps pointing at `localhost:8000`. `127.0.0.1,192.168.20.105` is the form
  you probably want: loopback for anything on the Mac, the LAN address for
  your phone, and still nothing listening on a foreign network. Be aware that
  oMLX binds one socket per host and *any* failed bind aborts startup, so
  off-network oMLX will not run **at all**, even for local-only use. There is
  no way to keep a localhost-only server while away.
- **It does nothing on your home LAN.** Anyone already on your wifi gets
  keyless access, same as `0.0.0.0`. The protection is only against networks
  you did not choose.

Pick a third octet that is not a common default (`192.168.20.x` is a far safer
bet than `192.168.1.x`) — a foreign network would have to use your exact subnet
*and* hand you that exact address for the bind to succeed.

#### Bind to a Tailscale IP — the better option if you will install it

A **Tailscale (or other VPN) IP in the Host field** gets you keyless access
from anywhere, not just at home, while the server never listens on your LAN or
on any untrusted interface and there is nothing public to scan. It costs you an
extra app on every device. If you only ever need the UI from your own wifi, the
LAN-IP option above is simpler and nearly as safe.

If you do use `0.0.0.0`, pair it with a macOS firewall rule limiting the port
to your subnet.

### Or just keep the key

Your browser's password manager will fill the dashboard login, and it is a
one-time thing per browser — including on a phone. If that is tolerable, you do
not need this patch at all.

---

## How the patch works

Every gate — the greyed-out toggle, the "Available only when every server host
is loopback" warning, the save rejection, the startup `ValueError`, and the CLI
auto-reset of a saved host back to `127.0.0.1` — funnels through two functions:

| Layer | File (inside `oMLX.app/Contents/Resources/`) | Function |
|---|---|---|
| Backend | `omlx/utils/network.py` | `is_loopback_bind()` |
| Web UI | `omlx/admin/static/js/dashboard.js` | `isLoopbackBindHost()` |

`network_auth_error()` calls `is_loopback_bind()` first and returns `None` as
soon as it's true, so patching that single function also clears the validator
used by `settings.validate()`, server startup, `verify_api_key()`,
`require_admin()`, the admin login redirect, and the settings-save endpoint.
The JS twin drives the disabled toggle, the warning text, and a pre-save guard
that silently forced `skip_api_key_verification` back to `false` on every save.

The patch makes both short-circuit to "loopback" for any non-empty host. It
inserts a marked block at the top of each function and leaves the original
logic in place below it, so the diff is three lines per file and easy to audit.

## Usage

```bash
python3 omlx-noauth-patch.py --status    # show whether each file is patched
python3 omlx-noauth-patch.py --apply     # patch
python3 omlx-noauth-patch.py --revert    # restore from backups
```

`--apply` is idempotent, so re-running it is safe. Each patched file gets a
`.omlx-noauth.bak` sibling inside the app bundle, and the stale `__pycache__`
entry for the patched module is removed.

### After applying

1. **Quit oMLX completely and relaunch.** The running server has the old code
   loaded in memory.
2. **Hard-reload the dashboard** (`Cmd-Shift-R`). The JS is mtime-cache-busted
   but your browser may still hold the old copy.
3. Turn on **Skip API key verification** in Settings and save. The toggle is no
   longer greyed out at `0.0.0.0`.

### After every oMLX update

Updates replace the app bundle and restore the original files. Just re-run:

```bash
python3 omlx-noauth-patch.py --apply
```

## Notes and caveats

- **macOS will prompt you.** Signed app bundles are write-protected
  (macOS 13+). The first `--apply` triggers a system dialog asking whether to
  allow modification of oMLX. Approve it or the patch fails with
  `PermissionError: Operation not permitted`.
- **Code signature.** Editing bundle resources invalidates oMLX's signature.
  The app still launches, because macOS does not re-verify resource hashes on
  every launch. If some future macOS release ever refuses to start it, run
  `--revert` to restore the signed originals, or ad-hoc re-sign with
  `codesign --force --deep --sign - /Applications/oMLX.app`.
- **If oMLX restructures those functions**, `--apply` exits with
  `anchor not found` instead of silently doing nothing. The anchors are the
  two regexes at the top of the script and are straightforward to update.
- **Non-default install path?** Edit the `APP` constant at the top of the
  script.

## Tested against

oMLX 0.7.0 (build 2987) on macOS 26 / Apple Silicon.
