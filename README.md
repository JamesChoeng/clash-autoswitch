# clash-autoswitch

Auto-pick the **fastest** Clash/Mihomo proxy node and **fail over** the instant the active one dies.

It continuously probes every node in your subscription against your real targets (Cursor + Anthropic by default), switches to the fastest, and — when the node you're on goes down — instantly hops to the next best one. Talks to Mihomo's external-controller (the same one [Clash Verge Rev](https://github.com/clash-verge-rev/clash-verge-rev) uses) over TCP on every platform, with a Windows named-pipe fallback.

**Zero third-party dependencies** — pure Python standard library.

## Install

```bash
# run it without installing
uvx clash-autoswitch status

# or install as a global command
pipx install clash-autoswitch
# (or) pip install clash-autoswitch
```

Requires Python 3.8+ and a running Clash Verge Rev / Mihomo with its external-controller enabled (Verge enables it by default).

## Usage

```bash
clash-autoswitch run        # run the daemon in the foreground (blocks)
clash-autoswitch once       # one scan + switch, then exit
clash-autoswitch ensure     # start the daemon in the background if not running
clash-autoswitch stop       # stop the background daemon
clash-autoswitch status     # controller / current node / daemon status
clash-autoswitch scan       # rank all nodes by latency (no switch)
clash-autoswitch switch HK  # manually switch to a node (name or substring)
clash-autoswitch log        # tail the daemon log
```

## Auto-start at login

One command, paths filled in automatically — no hand-editing service files:

```bash
clash-autoswitch install-service     # macOS launchd / Linux systemd --user / Windows scheduled task
clash-autoswitch uninstall-service
```

- **macOS** — installs a `launchd` LaunchAgent (`~/Library/LaunchAgents`), starts at login, restarts on crash.
- **Linux** — installs a `systemd --user` unit, `enable --now`. On headless boxes you may need `loginctl enable-linger $USER`.
- **Windows** — registers a Scheduled Task that runs at logon (windowless via `pythonw`).

## How it works

- **Scoring** — for each node, probe every target and average the latency; unreachable targets add a penalty so partially-working nodes rank below fully-working ones.
- **Failover** — a short liveness loop watches the current node; after a few consecutive failures it switches immediately (bypassing the optimization cooldown).
- **Anti-flap** — optimization switches respect a cooldown and a switch tolerance, and are deferred while a Cursor/Anthropic connection is in flight (up to a cap) so an active request isn't cut.

## Configuration

The controller endpoint and secret are auto-discovered from Clash Verge's `config.yaml`. Override anything via environment variables:

| Env var | Default | Meaning |
|---|---|---|
| `CLASH_CONTROLLER` | auto | `host:port` of the external-controller |
| `CLASH_SECRET` | auto | controller secret |
| `AUTOSWITCH_TARGETS` | Cursor + Anthropic | comma-separated probe URLs |
| `AUTOSWITCH_STATE_DIR` | per-user state dir | where the pid + log files live |
| `AUTOSWITCH_FULL_SCAN_INTERVAL` | `180` | seconds between full re-rank scans |
| `AUTOSWITCH_HEALTH_INTERVAL` | `15` | seconds between liveness checks |
| `AUTOSWITCH_HEALTH_FAIL_THRESHOLD` | `3` | failures before failover |
| `AUTOSWITCH_SWITCH_TOLERANCE_MS` | `150` | min latency gain to bother switching |
| `AUTOSWITCH_SWITCH_COOLDOWN` | `60` | min seconds between optimization switches |
| `AUTOSWITCH_DELAY_TIMEOUT_MS` | `4000` | per-probe timeout during scoring |

State (pid + rotating log) lives under a per-user directory:
`%LOCALAPPDATA%\clash-autoswitch` (Windows), `~/Library/Application Support/clash-autoswitch` (macOS), `~/.local/state/clash-autoswitch` (Linux).

## License

MIT
