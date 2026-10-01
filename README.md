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

### The better pattern

Put a **Tailscale (or other VPN) IP in the Host field instead of `0.0.0.0`.**
Your phone still reaches the UI with no key from anywhere in the world, but the
server never listens on your LAN or on any untrusted interface, and there is
nothing public to scan. This is strictly better than `0.0.0.0` for the "my
phone can't get to my internal web tools" use case, and it is what I would
recommend to anyone landing here.

If you do bind to `0.0.0.0`, pair it with a macOS firewall rule limiting the
port to your subnet.

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
