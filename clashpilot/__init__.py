"""clashpilot: a standalone Clash/Mihomo client with fastest-node autoswitch.

Give it a subscription URL and it downloads the mihomo core, generates the
config, launches the core, sets the system proxy, then continuously probes every
proxy node against your real targets (Cursor + Anthropic by default), switches to
the fastest, and instantly fails over when the active node dies. It can also
attach to an existing Clash Verge Rev / Mihomo via its external-controller.
Zero third-party Python dependencies.
"""

from __future__ import annotations

__version__ = "0.2.0"

__all__ = ["__version__"]
