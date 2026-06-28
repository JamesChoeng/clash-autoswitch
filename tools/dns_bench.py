"""One-off DNS vs connection speed benchmark for clashpilot users."""

from __future__ import annotations

import json
import socket
import statistics
import subprocess
import sys
import time
import urllib.parse
import urllib.request

DOMAINS = [
    "api2.cursor.sh",
    "api.anthropic.com",
    "cfyes.lxy1015.top",
    "aws-link14.liangxin1.xyz",
    "jp-lx.777076.xyz",
]

DNS_SERVERS = {
    "AliDNS (223.5.5.5)": "223.5.5.5",
    "Tencent (119.29.29.29)": "119.29.29.29",
    "114DNS (114.114.114.114)": "114.114.114.114",
    "Cloudflare (1.1.1.1)": "1.1.1.1",
    "Google (8.8.8.8)": "8.8.8.8",
    "Baidu (180.76.76.76)": "180.76.76.76",
}

ROUNDS = 5
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def resolve_nslookup(domain: str, dns_ip: str) -> float | None:
    t0 = time.perf_counter()
    try:
        r = subprocess.run(
            ["nslookup", domain, dns_ip],
            capture_output=True,
            text=True,
            timeout=5,
            creationflags=_NO_WINDOW,
        )
        ok = r.returncode == 0 and "Address" in r.stdout
        ms = (time.perf_counter() - t0) * 1000
        return ms if ok else None
    except Exception:
        return None


def resolve_system(domain: str) -> float | None:
    t0 = time.perf_counter()
    try:
        socket.getaddrinfo(domain, 443, type=socket.SOCK_STREAM)
        return (time.perf_counter() - t0) * 1000
    except OSError:
        return None


def fmt_ms(v: float | None) -> str:
    return f"{v:>17.1f}ms" if v is not None else f"{'timeout':>18}"


def run_dns_benchmark() -> None:
    print("=" * 72)
    print(f"DNS resolution benchmark ({ROUNDS} rounds, median ms)")
    print("=" * 72)

    resolve_system("api.anthropic.com")

    results: dict[str, dict[str, float | None]] = {}
    for dns_name, dns_ip in DNS_SERVERS.items():
        results[dns_name] = {}
        for domain in DOMAINS:
            times = [resolve_nslookup(domain, dns_ip) for _ in range(ROUNDS)]
            times = [t for t in times if t is not None]
            results[dns_name][domain] = statistics.median(times) if times else None

    sys_results: dict[str, float | None] = {}
    for domain in DOMAINS:
        times = [resolve_system(domain) for _ in range(ROUNDS)]
        times = [t for t in times if t is not None]
        sys_results[domain] = statistics.median(times) if times else None

    header = f"{'DNS':<28}" + "".join(f" {d[:18]:>18}" for d in DOMAINS)
    print(header)
    print("-" * len(header))

    row = f"{'System (default)':<28}" + "".join(fmt_ms(sys_results[d]) for d in DOMAINS)
    print(row)
    for dns_name in DNS_SERVERS:
        row = f"{dns_name:<28}" + "".join(fmt_ms(results[dns_name][d]) for d in DOMAINS)
        print(row)

    print()
    print("Average resolution latency across all domains:")
    avgs: list[tuple[float, str]] = []
    for dns_name in DNS_SERVERS:
        vals = [v for v in results[dns_name].values() if v is not None]
        if vals:
            avgs.append((statistics.mean(vals), dns_name))
    sys_vals = [v for v in sys_results.values() if v is not None]
    if sys_vals:
        avgs.append((statistics.mean(sys_vals), "System (default)"))
    avgs.sort()
    for avg, name in avgs:
        print(f"  {name:<28} {avg:>6.1f} ms")


def run_proxy_benchmark() -> None:
    print()
    print("=" * 72)
    print("End-to-end latency via clashpilot proxy (mihomo delay API)")
    print("=" * 72)

    try:
        with urllib.request.urlopen("http://127.0.0.1:9090/proxies", timeout=3) as r:
            proxies = json.loads(r.read())["proxies"]
    except Exception as e:
        print(f"Controller unreachable: {e}")
        return

    selectors = [
        n for n, i in proxies.items()
        if i.get("type") == "Selector" and n != "GLOBAL"
    ]
    group = max(selectors, key=lambda n: len(proxies[n].get("all", [])), default="GLOBAL")
    node = proxies[group]["now"]
    print(f"Current node: {node}")
    print(f"Proxy group:  {group}")

    targets = [
        "https://api2.cursor.sh",
        "https://api.anthropic.com/v1/messages",
    ]
    for url in targets:
        q = urllib.parse.urlencode({"url": url, "timeout": 4000, "expected": "200-599"})
        path = f"http://127.0.0.1:9090/proxies/{urllib.parse.quote(node, safe='')}/delay?{q}"
        delays: list[int] = []
        for _ in range(3):
            try:
                with urllib.request.urlopen(path, timeout=10) as r:
                    d = json.loads(r.read()).get("delay")
                    if d:
                        delays.append(int(d))
            except Exception:
                pass
            time.sleep(0.3)
        med = statistics.median(delays) if delays else None
        if med is not None:
            print(f"  {url}: {med:.0f}ms (median of 3)")
        else:
            print(f"  {url}: timeout")


def run_proxy_server_dns() -> None:
    print()
    print("=" * 72)
    print("Proxy server hostname resolution (nameserver choice matters here)")
    print("=" * 72)
    proxy_domains = [
        "cfyes.lxy1015.top",
        "aws-link14.liangxin1.xyz",
        "aws-linkhy2.liangxin1.xyz",
    ]
    for domain in proxy_domains:
        cn = resolve_nslookup(domain, "223.5.5.5")
        intl = resolve_nslookup(domain, "1.1.1.1")
        cn_s = f"{cn:.1f}ms" if cn else "timeout"
        intl_s = f"{intl:.1f}ms" if intl else "timeout"
        note = ""
        if cn and intl:
            faster = "domestic DNS" if cn < intl else "intl DNS"
            note = f" (delta {abs(cn - intl):.1f}ms, {faster} faster)"
        print(f"  {domain}: AliDNS {cn_s} vs Cloudflare {intl_s}{note}")


def main() -> int:
    run_dns_benchmark()
    run_proxy_benchmark()
    run_proxy_server_dns()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
