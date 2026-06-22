"""Merge multiple Clash/Mihomo subscription YAML bodies into one config fragment.

Parsing is textual (no PyYAML) to match the rest of clashpilot. We merge proxy
entries from every source, dedupe by name, and expand the largest selector group
so autoswitch can pick any merged node.
"""

from __future__ import annotations

import json
import re

_TOP_KEY_RE = re.compile(r"^([A-Za-z0-9_.-]+):")
_INLINE_NAME_RE = re.compile(r"^\s+-\s+name:\s*(.+)$")
_NAME_LINE_RE = re.compile(r"^(\s+)name:\s*(.+)$")
_SELECTOR_TYPES = frozenset({"select", "selector", "url-test", "urltest", "fallback"})


def split_top_level_sections(text: str) -> dict[str, str]:
    """Split YAML text into top-level section blocks keyed by section name."""
    sections: dict[str, str] = {}
    current_key: str | None = None
    current_lines: list[str] = []
    for line in text.splitlines():
        m = _TOP_KEY_RE.match(line)
        if m and not line.startswith((" ", "\t")):
            if current_key is not None:
                sections[current_key] = "\n".join(current_lines)
            current_key = m.group(1)
            current_lines = [line]
        elif current_key is not None:
            current_lines.append(line)
    if current_key is not None:
        sections[current_key] = "\n".join(current_lines)
    return sections


def _split_list_items(section_body: str) -> list[str]:
    """Split a top-level list section (proxies / proxy-groups) into item blocks."""
    lines = section_body.splitlines()
    if not lines:
        return []
    items: list[str] = []
    current: list[str] = []
    for line in lines[1:]:
        if line.startswith("  - ") and current:
            items.append("\n".join(current))
            current = [line]
        elif line.startswith("  - "):
            current = [line]
        elif current and (line.startswith("    ") or line.startswith("\t") or line.strip() == ""):
            current.append(line)
    if current:
        items.append("\n".join(current))
    return items


def _parse_scalar(raw: str) -> str:
    raw = raw.strip()
    if not raw:
        return raw
    if raw[0] in "\"'":
        try:
            return json.loads(raw)
        except (ValueError, TypeError):
            return raw.strip("'\"")
    return raw


def proxy_item_name(item: str) -> str | None:
    for line in item.splitlines():
        inline = _INLINE_NAME_RE.match(line)
        if inline:
            return _parse_scalar(inline.group(1))
        m = _NAME_LINE_RE.match(line)
        if m:
            return _parse_scalar(m.group(2))
    return None


def _item_name_line(item: str) -> tuple[int, str] | None:
    for i, line in enumerate(item.splitlines()):
        if _INLINE_NAME_RE.match(line) or _NAME_LINE_RE.match(line):
            return i, line
    return None


def _rename_proxy_item(item: str, new_name: str) -> str:
    located = _item_name_line(item)
    if located is None:
        return item
    idx, line = located
    lines = item.splitlines()
    inline = _INLINE_NAME_RE.match(line)
    if inline:
        indent = re.match(r"^(\s+-)", line)
        prefix = indent.group(1) if indent else "  -"
        lines[idx] = f"{prefix} name: {json.dumps(new_name, ensure_ascii=False)}"
    else:
        m = _NAME_LINE_RE.match(line)
        if m:
            lines[idx] = f'{m.group(1)}name: {json.dumps(new_name, ensure_ascii=False)}'
    return "\n".join(lines)


def _group_meta(item: str) -> tuple[str | None, str | None]:
    name: str | None = None
    gtype: str | None = None
    for line in item.splitlines():
        inline = _INLINE_NAME_RE.match(line)
        if inline:
            name = _parse_scalar(inline.group(1))
            continue
        m = _NAME_LINE_RE.match(line)
        if m:
            name = _parse_scalar(m.group(2))
            continue
        tm = re.match(r"^\s+type:\s*(.+)$", line)
        if tm:
            gtype = _parse_scalar(tm.group(1)).lower()
    return name, gtype


def _proxy_refs_in_group(item: str) -> list[str]:
    refs: list[str] = []
    in_list = False
    for line in item.splitlines():
        if re.match(r"^\s+proxies:\s*$", line):
            in_list = True
            continue
        if in_list:
            m = re.match(r"^\s+-\s+(.+)$", line)
            if m:
                refs.append(_parse_scalar(m.group(1)))
                continue
            if line.strip() and not line.startswith(" "):
                break
            if line.strip() and not line.startswith("    ") and not line.startswith("\t"):
                in_list = False
    return refs


def _replace_group_proxy_refs(item: str, refs: list[str]) -> str:
    out: list[str] = []
    in_list = False
    replaced = False
    for line in item.splitlines():
        if re.match(r"^\s+proxies:\s*$", line):
            in_list = True
            out.append(line)
            if not replaced:
                for ref in refs:
                    out.append(f"        - {json.dumps(ref, ensure_ascii=False)}")
                replaced = True
            continue
        if in_list:
            if re.match(r"^\s+-\s+", line):
                continue
            if line.strip() and not line.startswith("    ") and not line.startswith("\t"):
                in_list = False
            elif line.strip() == "":
                continue
            else:
                in_list = False
        out.append(line)
    return "\n".join(out)


def merge_subscription_texts(texts: list[str]) -> str:
    """Merge multiple subscription YAML bodies into one fragment."""
    if not texts:
        return ""
    if len(texts) == 1:
        return texts[0].strip() + "\n"

    merged_items: list[str] = []
    seen_names: set[str] = set()
    for source_idx, text in enumerate(texts, start=1):
        sections = split_top_level_sections(text)
        proxy_section = sections.get("proxies")
        if not proxy_section:
            continue
        for item in _split_list_items(proxy_section):
            name = proxy_item_name(item)
            if not name:
                merged_items.append(item)
                continue
            final_name = name
            if final_name in seen_names:
                suffix = f" [#{source_idx}]"
                base = name
                n = 2
                while final_name in seen_names:
                    final_name = f"{base}{suffix}" if n == 2 else f"{base}{suffix}-{n}"
                    n += 1
            seen_names.add(final_name)
            merged_items.append(
                _rename_proxy_item(item, final_name) if final_name != name else item
            )

    if not merged_items:
        return texts[0].strip() + "\n"

    base_sections = split_top_level_sections(texts[0])
    group_names: set[str] = set()
    groups_section = base_sections.get("proxy-groups")
    group_items: list[str] = []
    if groups_section:
        group_items = _split_list_items(groups_section)
        for item in group_items:
            gname, _ = _group_meta(item)
            if gname:
                group_names.add(gname)

    keep_refs: list[str] = []
    best_idx = -1
    best_count = -1
    for idx, item in enumerate(group_items):
        _gname, gtype = _group_meta(item)
        if gtype not in _SELECTOR_TYPES:
            continue
        refs = _proxy_refs_in_group(item)
        if len(refs) > best_count:
            best_idx = idx
            best_count = len(refs)
            keep_refs = [r for r in refs if r in group_names]

    all_proxy_names = [proxy_item_name(item) for item in merged_items]
    all_proxy_names = [n for n in all_proxy_names if n]
    new_refs = keep_refs + [n for n in all_proxy_names if n not in keep_refs]

    if best_idx >= 0:
        group_items[best_idx] = _replace_group_proxy_refs(group_items[best_idx], new_refs)
        base_sections["proxy-groups"] = "proxy-groups:\n" + "\n".join(group_items)
    else:
        base_sections["proxy-groups"] = (
            "proxy-groups:\n"
            + "\n".join(
                [
                    "  - name: clashpilot",
                    "    type: select",
                    "    proxies:",
                    *[f"        - {json.dumps(n, ensure_ascii=False)}" for n in all_proxy_names],
                ]
            )
        )
        rules = base_sections.get("rules", "rules:\n    - MATCH,clashpilot")
        rule_lines = rules.splitlines()
        if rule_lines:
            rule_lines[-1] = "    - MATCH,clashpilot"
            base_sections["rules"] = "\n".join(rule_lines)

    base_sections["proxies"] = "proxies:\n" + "\n".join(merged_items)

    order = list(split_top_level_sections(texts[0]).keys())
    for text in texts[1:]:
        for key in split_top_level_sections(text):
            if key not in order:
                order.append(key)
    if "proxies" in order:
        order.remove("proxies")
        order.insert(0, "proxies")

    parts = [base_sections[k] for k in order if k in base_sections]
    return "\n".join(parts).strip() + "\n"
