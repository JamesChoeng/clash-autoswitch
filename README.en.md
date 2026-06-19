# clashpilot

[简体中文](README.md) | English

A standalone Clash/Mihomo client that auto-selects the fastest proxy node, fails over when a node drops, and runs silently in the background. No Clash Verge, no GUI — the [mihomo](https://github.com/MetaCubeX/mihomo) core is downloaded and managed for you.

A free default node list is built in, so you're online right after install; add your own subscription for a faster, more stable connection.

## Install

Requires [Python 3.8+](https://www.python.org/downloads/) and [git](https://git-scm.com/downloads). `pipx` is recommended:

```bash
pipx install git+https://github.com/JamesChoeng/clashpilot.git
```

Upgrade: `pipx upgrade clashpilot`.

<details>
<summary>Install with uvx or pip</summary>

```bash
# run without installing (requires uv)
uvx --from git+https://github.com/JamesChoeng/clashpilot clashpilot status

# plain pip
pip install git+https://github.com/JamesChoeng/clashpilot.git
```

With `pip install --user`, the command may land in a directory that isn't on PATH. The first `clashpilot up` adds it automatically (and makes the short `clp` command work on Windows); you can also run `clashpilot setup-path`. Open a new terminal afterwards.

If GitHub downloads are slow, set a mirror via `CLASHPILOT_GH_PROXY` (see [Configuration](#configuration)).

</details>

## Quick start

Start (runs in foreground, `Ctrl-C` to stop):

```bash
clashpilot up
```

Use your own subscription:

```bash
clashpilot set-sub "your-subscription-link"
clashpilot update
```

> Every command also works with the short alias `clp`, e.g. `clp up`.

## Keep Cursor & other AI tools online

Add this to `~/.cursor/hooks.json` to ensure the proxy is ready at the start of every session:

```jsonc
{
  "version": 1,
  "hooks": {
    "sessionStart": [
      { "command": "clashpilot hook" }
    ]
  }
}
```

## Commands

| Command | Description |
|---|---|
| `clashpilot up` | Start: core + system proxy + autoswitch (foreground) |
| `clashpilot down` | Stop: shut down the core and undo the system proxy |
| `clashpilot status` | Show core / proxy / subscription status |
| `clashpilot set-sub URL` | Save your subscription link |
| `clashpilot update` | Re-fetch the subscription and rebuild the config |
| `clashpilot setup-path` | Add the command's directory to PATH |
| `clashpilot hook` | For the Cursor hook |

## Configuration

Everything has sensible defaults; override via environment variables:

| Env var | Default | Meaning |
|---|---|---|
| `CLASHPILOT_SUBSCRIPTION` | built-in default | subscription link (takes priority over `set-sub`) |
| `CLASHPILOT_GH_PROXY` | none | GitHub download mirror prefix, e.g. `https://ghproxy.com` |
| `CLASHPILOT_CORE_VERSION` | latest | pin a mihomo version, e.g. `v1.19.24` |
| `CLASHPILOT_MIXED_PORT` | `7890` | local proxy port (HTTP + SOCKS) |
| `CLASHPILOT_CONTROLLER_PORT` | `9090` | core controller port |
| `CLASHPILOT_TARGETS` | Cursor + Anthropic | probe target URLs (comma-separated) |
| `CLASHPILOT_STATE_DIR` | per-user state dir | where core / config / logs live |
| `CLASH_CONTROLLER` / `CLASH_SECRET` | auto | controller address / secret |

Data files live in: `%LOCALAPPDATA%\clashpilot` (Windows), `~/Library/Application Support/clashpilot` (macOS), `~/.local/state/clashpilot` (Linux).

## Notes & limits

- The system proxy uses mihomo's local port (HTTP + SOCKS); TUN mode is not enabled.
- On Linux, automatic system-proxy setup uses GNOME `gsettings`; on other desktops set `http_proxy` / `https_proxy` yourself.

## License

MIT
