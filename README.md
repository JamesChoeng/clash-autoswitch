# clashpilot

English | [简体中文](README.zh-CN.md)

A **standalone** Clash/Mihomo client that auto-picks the **fastest** proxy node and **fails over** the instant the active one dies.

Give it a subscription link and it does everything: downloads the [mihomo](https://github.com/MetaCubeX/mihomo) core for your platform, generates the config, launches the core, sets your system proxy, then continuously probes every node against your real targets (Cursor + Anthropic by default), switches to the fastest, and instantly hops to the next best one when the node you're on goes down.

**No Clash Verge, no GUI, nothing else to install** — the mihomo core is fetched and managed for you. **Zero third-party Python dependencies** — pure standard library.

> It can still attach to an existing Clash Verge Rev / Mihomo instead (see [Legacy mode](#legacy-attach-to-an-existing-core)).

## Install

Installs straight from GitHub — no PyPI needed.

```bash
# run it without installing (requires uv + git)
uvx --from git+https://github.com/JamesChoeng/clashpilot clashpilot status

# or install as a global command (requires pipx + git)
pipx install git+https://github.com/JamesChoeng/clashpilot.git

# plain pip works too
pip install git+https://github.com/JamesChoeng/clashpilot.git
```

To update later: `pipx upgrade clashpilot` (or re-run the install command).

Requires Python 3.8+ and git. The mihomo core is downloaded automatically on first run.

## Quick start

```bash
clashpilot up   # core + config + system proxy + autoswitch (blocks)
```

That's it — **online out of the box**. With no subscription set, clashpilot uses a built-in default (a public, auto-updating free node list) so you're connected the moment you install. Traffic goes through the fastest live node, with automatic failover.

For your own (faster, more stable) nodes, point it at your subscription — it takes priority over the default:

```bash
clashpilot set-sub "https://your-provider.example/sub?token=..."   # your Clash/Mihomo subscription
clashpilot update                                                   # rebuild config from it
```

> The built-in default uses free, volunteer-run public nodes — fine for getting online, but they're unstable and see all your traffic. Use your own subscription for anything sensitive.

Stop it with Ctrl-C (which also removes the system proxy and stops the core), or run it in the background:

```bash
clashpilot ensure   # start the whole stack in the background
clashpilot down     # stop core + remove system proxy + stop background daemon
```

## Usage

```bash
clashpilot set-sub URL # save your Clash/Mihomo subscription URL
clashpilot up          # standalone: core + config + system proxy + loop (blocks)
clashpilot ensure      # start the standalone stack in the background
clashpilot down        # stop core + remove system proxy + stop daemon
clashpilot update      # re-fetch subscription + rebuild config + reload core
clashpilot core        # download/update the mihomo core binary
clashpilot status      # core / controller / current node / daemon status
clashpilot scan        # rank all nodes by latency (no switch)
clashpilot switch HK   # manually switch to a node (name or substring)
clashpilot log         # tail the daemon log
clashpilot stop        # stop the background daemon (leaves core running)
```

## Auto-start at login

One command, paths filled in automatically — no hand-editing service files:

```bash
clashpilot install-service     # macOS launchd / Linux systemd --user / Windows scheduled task
clashpilot uninstall-service
```

Each runs `clashpilot up` at login (core + system proxy + autoswitch).

- **macOS** — installs a `launchd` LaunchAgent (`~/Library/LaunchAgents`), starts at login, restarts on crash.
- **Linux** — installs a `systemd --user` unit, `enable --now`. On headless boxes you may need `loginctl enable-linger $USER`.
- **Windows** — registers a Scheduled Task that runs at logon (windowless via `pythonw`).

## How it works

- **Self-contained core** — `mihomo` is downloaded from GitHub Releases for your OS/arch (amd64 uses the `compatible` build for the widest CPU support), cached under your state dir, and launched as a child process pointed at a config we generate from your subscription with our own `external-controller`, `secret`, and `mixed-port` injected.
- **Scoring** — for each node, probe every target and average the latency; unreachable targets add a penalty so partially-working nodes rank below fully-working ones.
- **Failover** — a short liveness loop watches the current node; after a few consecutive failures it switches immediately (bypassing the optimization cooldown).
- **Anti-flap** — optimization switches respect a cooldown and a switch tolerance, and are deferred while a Cursor/Anthropic connection is in flight (up to a cap) so an active request isn't cut.
- **Subscription refresh** — in standalone mode the subscription is re-fetched periodically and the core hot-reloaded.

## Legacy: attach to an existing core

If you'd rather keep running Clash Verge Rev / Mihomo yourself, the original controller-only mode still works — it auto-discovers the controller endpoint and secret from Clash Verge's `config.yaml`:

```bash
clashpilot run     # loop only; talks to the core/Verge you already run
```

## Configuration

Everything has sensible defaults. Override via environment variables:

| Env var | Default | Meaning |
|---|---|---|
| `CLASHPILOT_SUBSCRIPTION` | built-in default | subscription URL (overrides `set-sub`; falls back to a built-in free default, then a bundled offline node list) |
| `CLASHPILOT_GH_PROXY` | none | prefix for GitHub downloads, e.g. `https://ghproxy.com` (useful in CN) |
| `CLASHPILOT_CORE_VERSION` | latest | pin a specific mihomo version (e.g. `v1.19.24`) |
| `CLASHPILOT_MIXED_PORT` | `7890` | local HTTP+SOCKS proxy port |
| `CLASHPILOT_CONTROLLER_PORT` | `9090` | external-controller port for the managed core |
| `CLASHPILOT_SUB_REFRESH_INTERVAL` | `21600` | seconds between subscription refreshes (`0` = off) |
| `CLASH_CONTROLLER` | auto | `host:port` of the external-controller (legacy/override) |
| `CLASH_SECRET` | auto | controller secret (legacy/override) |
| `CLASHPILOT_TARGETS` | Cursor + Anthropic | comma-separated probe URLs |
| `CLASHPILOT_STATE_DIR` | per-user state dir | where core/config/pid/log files live |
| `CLASHPILOT_FULL_SCAN_INTERVAL` | `180` | seconds between full re-rank scans |
| `CLASHPILOT_HEALTH_INTERVAL` | `15` | seconds between liveness checks |
| `CLASHPILOT_HEALTH_FAIL_THRESHOLD` | `3` | failures before failover |
| `CLASHPILOT_SWITCH_TOLERANCE_MS` | `150` | min latency gain to bother switching |
| `CLASHPILOT_SWITCH_COOLDOWN` | `60` | min seconds between optimization switches |
| `CLASHPILOT_DELAY_TIMEOUT_MS` | `4000` | per-probe timeout during scoring |

State (downloaded core, managed config, pid + rotating log) lives under a per-user directory:
`%LOCALAPPDATA%\clashpilot` (Windows), `~/Library/Application Support/clashpilot` (macOS), `~/.local/state/clashpilot` (Linux).

## Notes & limits

- The system proxy is set to mihomo's mixed-port (HTTP + SOCKS). TUN/global-capture mode is not configured (it needs elevated privileges / drivers).
- On Linux, automatic system-proxy setup uses GNOME `gsettings`; on other desktops export `http_proxy`/`https_proxy` yourself (the proxy still runs on the mixed-port).
- The proxy protocols themselves are handled by the mihomo binary; this project doesn't reimplement them.

## License

MIT
