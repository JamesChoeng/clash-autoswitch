# clashpilot

[简体中文](README.md) | English

The best proxy tool for AI agents: it auto-selects the fastest proxy node, fails over when a node drops, and runs silently in the background. No GUI, works out of the box — keeping Cursor and other AI tools reliably online.

A free default node list is built in, so you're online right after install; add your own subscription for a faster, more stable connection.

## Install

### One-line install (auto-detects & installs Python / git)

No need to prepare the environment first: the script detects whether Python 3.8+ and git are present, installs them if missing, then installs clashpilot via `pipx`.

Windows (PowerShell):

```powershell
irm https://raw.githubusercontent.com/JamesChoeng/clashpilot/main/install.ps1 | iex
```

macOS / Linux:

```bash
curl -fsSL https://raw.githubusercontent.com/JamesChoeng/clashpilot/main/install.sh | sh
```

After installation, open a **new terminal** and run `clashpilot up` to start.

### If you already have Python

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

**Opus-region filtering is on by default.** The first `clp up` scans nodes and keeps only exits in Anthropic-supported countries. Re-scan manually anytime:

```bash
clashpilot whitelist --refresh
```

Nodes named or exiting from Hong Kong, mainland China, Russia, etc. are excluded even when the label says "US/Japan".

> Every command also works with the short alias `clp`, e.g. `clp up`.

## Run in the background (start at login)

Have clashpilot start at login and stay running in the background (restarts on crash):

```bash
clashpilot install-service
```

On **macOS** and **Windows**, the first `install-service` automatically enables TUN mode (better Cursor compatibility) unless you already saved a routing preference. Override explicitly:

```bash
clashpilot install-service --tun
clashpilot install-service --no-tun
```

Remove it: `clashpilot uninstall-service`.

> Uses launchd on macOS, a systemd --user unit on Linux, and a logon Scheduled Task on Windows. If Task Scheduler denies access, Windows automatically falls back to a windowless Startup launcher. It starts immediately, no logout/login needed.

## Keep Cursor & other AI tools online

Use `clashpilot install-service` to register a login-started background service, or run `clashpilot up` for a temporary foreground session.

### TUN mode (system-wide routing)

By default clashpilot sets the **system proxy** (HTTP + SOCKS on port 7890). Apps that ignore proxy settings can use **TUN mode** so mihomo captures traffic at the network layer:

```bash
# one-off TUN session
clashpilot up --tun

# persist TUN preference in settings
clashpilot up --tun --persist-tun

# or via environment variable
export CLASHPILOT_TUN=1
clashpilot up
```

In TUN mode the system proxy is **not** configured; stopping the core (`clashpilot down`) restores routing.

| Platform | Notes |
|---|---|
| macOS | May prompt for admin / network permission on first run; default stack is `gvisor` |
| Linux | Requires `/dev/net/tun`; set `CLASHPILOT_TUN_AUTO_REDIRECT=1` for TCP redirect |
| Windows | Uses Wintun; default stack is `system` |

| Env var | Default | Meaning |
|---|---|---|
| `CLASHPILOT_TUN` | `0` | set to `1` to enable TUN mode |
| `CLASHPILOT_TUN_STACK` | `gvisor` on macOS, `system` elsewhere | `system` / `gvisor` / `mixed` |
| `CLASHPILOT_TUN_MTU` | `9000` on macOS | TUN MTU |
| `CLASHPILOT_TUN_AUTO_REDIRECT` | `0` | Linux: enable `auto-redirect` |

## Commands

| Command | Description |
|---|---|
| `clashpilot up` | Start: core + routing + autoswitch (foreground, `Ctrl-C` to stop). Add `--tun` for TUN mode |
| `clashpilot down` | Stop: shut down the background daemon/core and undo the system proxy |
| `clashpilot status` | Show autoswitch / core / proxy / subscription / current node / latency status |
| `clashpilot scan` | Probe and rank node latency (no switch); `-n 20` for top 20, `--all` for every node |
| `clashpilot set-sub URL` | Save your subscription link |
| `clashpilot update` | Re-fetch the subscription and rebuild the config |
| `clashpilot whitelist` | Show the Opus-region node pool |
| `clashpilot whitelist --refresh` | Re-scan exit countries and Anthropic reachability |
| `clashpilot install-service` | Register a login-launched background service (restarts on crash) |
| `clashpilot uninstall-service` | Remove the login-launched background service |
| `clashpilot setup-path` | Add the command's directory to PATH |

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
| `CLASHPILOT_OPUS_WHITELIST` | on by default | set `0` to disable Opus-region filtering |
| `CLASHPILOT_ANTHROPIC_FAIL_THRESHOLD` | `1` | consecutive Anthropic probe failures before failover (each round retries probes) |
| `CLASHPILOT_HEALTH_FAIL_THRESHOLD` | `1` | consecutive confirmed-fail health rounds before failover; separate from faster-node optimization |
| `CLASHPILOT_STATE_DIR` | per-user state dir | where core / config / logs live |
| `CLASH_CONTROLLER` / `CLASH_SECRET` | auto | controller address / secret |

Data files live in: `%LOCALAPPDATA%\clashpilot` (Windows), `~/Library/Application Support/clashpilot` (macOS), `~/.local/state/clashpilot` (Linux).

## Notes & limits

- Default routing uses mihomo's local port as the **system proxy**; optional **TUN mode** captures all traffic (see above).
- On Linux, automatic system-proxy setup uses GNOME `gsettings`; on other desktops set `http_proxy` / `https_proxy` yourself, or use TUN mode.

## License

Source-available and free to use, but **not open source**: modification,
redistribution, and derivative works are not permitted without authorization.
See [LICENSE](LICENSE) (ClashPilot Source-Available License).
