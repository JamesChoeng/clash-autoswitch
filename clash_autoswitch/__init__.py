"""clash-autoswitch: auto-pick the fastest Clash/Mihomo node and fail over.

Continuously probes every proxy node against your real targets (Cursor +
Anthropic by default), switches to the fastest, and instantly fails over when
the active node dies. Talks to Mihomo's external-controller -- the same one
Clash Verge Rev uses -- over TCP (all platforms) with a Windows named-pipe
fallback. Zero third-party dependencies.
"""

from __future__ import annotations

__version__ = "0.1.0"

__all__ = ["__version__"]
