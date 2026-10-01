# oMLX Patches

Small, reversible patches for [oMLX](https://omlx.app) on macOS.

| Patch | What it does |
|---|---|
| `omlx-noauth-patch.py` | Lets you enable **Skip API key verification** while the server is bound to a non-loopback host (`0.0.0.0`, a LAN IP, a Tailscale IP), so the admin web UI and API are reachable from other machines without a key. |

---

## ⚠️ Read this before using the no-auth patch

oMLX restricts keyless operation to loopback for a good reason. With this patch
applied and the toggle on, **anyone who can reach your server's port gets full
access with no credentials** — not just chat completions, but:

- the admin dashboard (model download, model **deletion**, settings)
- stored Responses and conversation history
- MCP tools, web search and web fetch, executed from your machine
- cluster/pairing endpoints if distributed inference is enabled

Only do this on a network you control. The safer middle ground is to put a
**Tailscale IP** in the Host field instead of `0.0.0.0` — you still get keyless
access from your own devices, but the server is not listening on your LAN or
on any untrusted interface. A macOS firewall rule limiting the port is a good
second layer.

If you don't want these consequences, keep the API key instead. You can store
it in your browser's password manager and the dashboard login is a one-time
thing per browser.

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
