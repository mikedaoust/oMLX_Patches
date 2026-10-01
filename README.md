# oMLX Patches

A patch for [oMLX](https://omlx.app) on macOS that makes keyless access depend
on **which address you bind to**, instead of refusing it for anything but
loopback.

| Patch | What it does |
|---|---|
| `omlx-netpolicy-patch.py` | Allows **Skip API key verification** on private addresses (your LAN IP, Tailscale, loopback), keeps the key required on `0.0.0.0` and public IPs, and lets the server start even when a configured address is unavailable. |

## The problem

Stock oMLX allows keyless operation only when every bind host is loopback. The
moment you bind to a LAN address so your phone can reach the admin UI, you are
required to paste an API key into a phone browser to manage a server sitting in
your own house.

The blunt fix — disable the check — throws away a real distinction. `0.0.0.0`
means "listen on every interface of whatever network I am joined to," and that
follows you onto hotel wifi and guest VLANs. A specific LAN address does not:
your machine only holds `192.168.20.105` on the network you configured it for.
Join a different network and that address is simply gone.

## The policy after patching

| Bind host | Keyless allowed | Why |
|---|---|---|
| `127.0.0.1`, `localhost`, `::1` | ✅ | nothing else can reach it |
| `192.168.x.y`, `10.x.y.z`, `172.16–31.x.y` | ✅ | you only hold it on a network you chose |
| `100.64–127.x.y` (Tailscale) | ✅ | reachable only by your own signed-in devices |
| `169.254.x.y`, `fe80::/10`, `fc00::/7` | ✅ | link-local / unique-local |
| `0.0.0.0` or `::` | ❌ **key required** | listens on every network you ever join |
| any globally routable IP | ❌ **key required** | a public IP is the coffee shop, permanently |
| any other hostname | ❌ **key required** | cannot be classified without resolving, which varies by network |

A comma-separated list is keyless only if **every** host in it qualifies, so
`0.0.0.0,192.168.20.105` still demands a key.

The patch also makes startup **tolerant**: a host this machine cannot currently
bind is skipped with a warning rather than aborting the process. oMLX gives up
only when no configured host binds at all.

## What to put in the Host field

Settings → Host → **Custom** takes a comma-separated list.

| Host value | Keyless | Phone on home wifi | On a network you did not choose |
|---|---|---|---|
| `127.0.0.1` | ✅ | ❌ | runs, local only |
| **`127.0.0.1,192.168.x.y`** | ✅ | ✅ | **runs local-only, LAN socket skipped** |
| `192.168.x.y` alone | ✅ | ✅ | will not start — nothing left to bind |
| `100.x.y.z` (Tailscale) | ✅ | ✅ anywhere | runs if Tailscale is up |
| `0.0.0.0` | ❌ key required | ✅ with key | listens to strangers |

**`127.0.0.1,192.168.x.y` is the one most people want.** Loopback for anything
running on the Mac, the LAN address for your phone, and when you take the
laptop out of the house the LAN socket silently drops off while local AI keeps
working.

Two things to do before switching:

- **Reserve the address in your router's DHCP.** Without a reservation, a new
  lease means your phone quietly stops reaching the server. The patch logs a
  loud `WARNING: cannot bind ...` line when this happens — that log is your
  only clue, since the server still starts.
- **Prefer an unusual subnet.** `192.168.20.x` is a far better bet than
  `192.168.1.x`, which a coffee shop might plausibly hand you.

## This is lower risk, not safe

On your own LAN, binding to `192.168.20.105` exposes exactly as much as
`0.0.0.0` does: every device on that wifi — guests, IoT gear, a compromised
laptop — reaches the admin UI with no credentials. That means model download
and **deletion**, settings, stored Responses, and MCP/web-fetch tools running
on your machine.

What the patch buys you is that the exposure **does not travel**. It is scoped
to a network you chose, and it disappears on its own when you leave. That is a
meaningful reduction in risk, not a guarantee of safety, and it is worth being
clear-eyed about which one you are getting.

Never port-forward a keyless oMLX, put it on a VPS, or expose it through a
public tunnel hostname. The patch refuses keyless on globally routable
addresses for exactly this reason, but a tunnel in front of a LAN bind would
route around that.

## Usage

```bash
python3 omlx-netpolicy-patch.py --status    # show whether each file is patched
python3 omlx-netpolicy-patch.py --apply     # patch
python3 omlx-netpolicy-patch.py --revert    # restore from backups
```

`--apply` is idempotent. Each patched file gets a `.omlx-netpolicy.bak`
sibling, and stale `__pycache__` entries are cleared.

### After applying

1. **Quit oMLX completely and relaunch.** The running server holds the old
   code in memory.
2. **Hard-reload the dashboard** (`Cmd-Shift-R`). The JS is mtime-cache-busted,
   but your browser may still have the old copy.
3. Set Host, turn on **Skip API key verification**, save, and restart the
   server — the Host field carries an amber "Restart" badge.

### After every oMLX update

Updates restore the originals. Re-run:

```bash
python3 omlx-netpolicy-patch.py --apply
```

## How it works

Three edits, all inside `oMLX.app/Contents/Resources/`:

| File | Function | Change |
|---|---|---|
| `omlx/utils/network.py` | `is_loopback_bind()` | reimplemented as the policy table above |
| `omlx/cli.py` | the bind loop | skip unbindable hosts, warn, exit only if all fail |
| `omlx/admin/static/js/dashboard.js` | `isLoopbackBindHost()` | mirror of the predicate |

Every backend gate funnels through `is_loopback_bind()` — startup validation,
`settings.validate()`, `verify_api_key()`, `require_admin()`, the admin login
redirect, the settings-save endpoint, and the CLI's auto-reset of a saved host
back to `127.0.0.1`. `network_auth_error()` returns `None` as soon as that
predicate is true, so one function carries the whole policy.

The JS mirror is what un-greys the toggle. It is a UI affordance only — the
backend is authoritative — but mirroring rather than always returning true
means the toggle still correctly greys out at `0.0.0.0`.

Python's own address classification needed two corrections, both handled:
`100.64/10` (Tailscale) reports as *neither* private nor global, and `0.0.0.0`
and `::` report as private, so they are excluded by `is_unspecified` first.

## Verified behavior

- 21 host values checked against the patched backend predicate, including
  comma lists, IPv4-mapped IPv6, zone IDs, and `172.32.0.1` (outside RFC1918)
- the JS mirror agrees with the backend on all 21
- tolerant bind exercised against an address the machine does not hold: one
  socket bound, warning logged, process continues
- all-hosts-fail exercised: exits `3` with a message pointing at `127.0.0.1`

## Notes and caveats

- **macOS will prompt you.** Signed app bundles are write-protected
  (macOS 13+). The first `--apply` triggers a system dialog asking whether to
  allow modification of oMLX. Approve it, or the patch fails with
  `PermissionError: Operation not permitted`.
- **Code signature.** Editing bundle resources invalidates oMLX's signature.
  The app still launches, because macOS does not re-verify resource hashes on
  every launch. If a future macOS release refuses it, `--revert` restores the
  signed originals, or ad-hoc re-sign with
  `codesign --force --deep --sign - /Applications/oMLX.app`.
- **If oMLX restructures these functions**, `--apply` exits with
  `anchor not found` rather than silently doing nothing.
- **Non-default install path?** Edit the `APP` constant at the top of the
  script.

## Tested against

oMLX 0.7.0 (build 2987) on macOS 26 / Apple Silicon.
