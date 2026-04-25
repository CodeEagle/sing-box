#!/usr/bin/env python3
"""sb-hostnameify: rewrite literal IPv4 (and the optional v6 mirror form) to a
dual-stack hostname in fscarmen sing-box subscribe outputs.

Each protocol becomes one entry; clients perform Happy Eyeballs (RFC 8305) to
pick IPv4 or IPv6 automatically. This is the recommended approach when the
operator owns a domain with both A and AAAA records pointing at the VPS.

Idempotent. Designed to run after fscarmen's sing-box.sh.

Configuration (env vars):
    HOSTNAME_TARGET  - Target dual-stack hostname (e.g. vps.example.com)
    SERVER_IP_LITERAL - The IPv4 literal to replace (auto-detected if unset)

Files processed under /etc/sing-box/:
    subscribe/proxies        (Clash provider yaml)
    subscribe/clash          (top-level clash with provider URL)
    subscribe/clash2         (full clash YAML with proxies block)
    subscribe/v2rayn         (base64-encoded URL list)
    subscribe/shadowrocket   (base64-encoded URL list)
    subscribe/neko           (base64-encoded URL list)
    subscribe/sing-box       (sing-box JSON)
    subscribe/qr             (display + URL examples)
    list                     (sb -n display)
"""
from __future__ import annotations

import base64
import json
import os
import re
import subprocess
import sys
from pathlib import Path

WORK_DIR = Path(os.environ.get("SB_WORK_DIR", "/etc/sing-box"))
SUB_DIR = WORK_DIR / "subscribe"
LIST_FILE = WORK_DIR / "list"

HOSTNAME = os.environ.get("HOSTNAME_TARGET", "").strip()
SERVER_IP_LITERAL = os.environ.get("SERVER_IP_LITERAL", "").strip()

V6_TAG = " IPv6"
MARK_BEGIN = "### DUALSTACK_BEGIN ###"
MARK_END = "### DUALSTACK_END ###"


def _detect_ipv4() -> str:
    out = subprocess.run(
        ["ip", "-4", "-o", "addr", "show", "scope", "global"],
        capture_output=True, text=True, check=False,
    ).stdout
    for line in out.splitlines():
        m = re.search(r"inet\s+([0-9.]+)/", line)
        if m:
            return m.group(1)
    return ""


def _strip_v6_block(text: str) -> str:
    return re.sub(
        rf"{re.escape(MARK_BEGIN)}.*?{re.escape(MARK_END)}\n?",
        "", text, flags=re.DOTALL,
    )


def _has_legacy_v6_mirror(line: str) -> bool:
    return (
        f"{V6_TAG}\"" in line
        or "@[2602:" in line
        or "%20IPv6" in line
        or line.endswith("#IPv6")
    )


def _sub_b64_url_host(url: str, ip: str, host: str) -> str:
    m = re.match(r"^([a-z][a-z0-9+\-.]*)://([A-Za-z0-9+/_=\-]+)(.*)$", url)
    if not m:
        return url
    scheme, b64part, rest = m.group(1), m.group(2), m.group(3)
    try:
        pad = (-len(b64part)) % 4
        decoded = base64.b64decode(b64part + "=" * pad).decode("utf-8", "replace")
    except Exception:
        return url
    if f"@{ip}:" not in decoded:
        return url
    new_decoded = decoded.replace(f"@{ip}:", f"@{host}:")
    new_b64 = base64.b64encode(new_decoded.encode("utf-8")).decode("ascii").rstrip("=")
    return f"{scheme}://{new_b64}{rest}"


def _sub_url_line(line: str, ip: str, host: str) -> str:
    line = line.replace(f"@{ip}:", f"@{host}:")
    return _sub_b64_url_host(line, ip, host)


def aug_yaml_provider(path: Path, ip: str, host: str) -> None:
    if not path.is_file():
        return
    lines = path.read_text().splitlines()
    cleaned = [ln for ln in lines if not _has_legacy_v6_mirror(ln)]
    out = []
    for ln in cleaned:
        ln = re.sub(
            rf"(?<![\w-])server:\s*{re.escape(ip)}\b",
            f'server: "{host}"',
            ln,
        )
        out.append(ln)
    path.write_text("\n".join(out) + "\n")


def aug_b64_url_list(path: Path, ip: str, host: str) -> None:
    if not path.is_file():
        return
    raw = path.read_text().strip()
    if not raw:
        return
    try:
        pad = (-len(raw)) % 4
        decoded = base64.b64decode(raw + "=" * pad).decode("utf-8", "replace")
    except Exception:
        return
    lines = decoded.splitlines()
    cleaned = [ln for ln in lines if not _has_legacy_v6_mirror(ln)]
    cleaned = [_sub_url_line(ln, ip, host) for ln in cleaned]
    body = "\n".join(cleaned)
    path.write_text(base64.b64encode(body.encode("utf-8")).decode("ascii"))


def aug_singbox(path: Path, ip: str, host: str) -> None:
    if not path.is_file():
        return
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError:
        return
    outs = data.get("outbounds", [])
    outs = [o for o in outs if not str(o.get("tag", "")).endswith(V6_TAG)]
    for o in outs:
        if o.get("server") == ip:
            o["server"] = host
    data["outbounds"] = outs
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")


def aug_text_with_urls(path: Path, ip: str, host: str) -> None:
    if not path.is_file():
        return
    text = _strip_v6_block(path.read_text())
    text = text.replace(ip, host)
    out = [ln for ln in text.splitlines() if not _has_legacy_v6_mirror(ln)]
    path.write_text("\n".join(out) + ("\n" if text.endswith("\n") else ""))


def main() -> int:
    host = HOSTNAME
    ip = SERVER_IP_LITERAL or _detect_ipv4()
    if not host:
        print("[hostnameify] HOSTNAME_TARGET not set; skip.", file=sys.stderr)
        return 0
    if not ip:
        print("[hostnameify] no IPv4 detected; skip.", file=sys.stderr)
        return 0
    aug_yaml_provider(SUB_DIR / "proxies", ip, host)
    aug_yaml_provider(SUB_DIR / "clash2", ip, host)
    aug_b64_url_list(SUB_DIR / "v2rayn", ip, host)
    aug_b64_url_list(SUB_DIR / "shadowrocket", ip, host)
    aug_b64_url_list(SUB_DIR / "neko", ip, host)
    aug_singbox(SUB_DIR / "sing-box", ip, host)
    aug_text_with_urls(SUB_DIR / "qr", ip, host)
    aug_text_with_urls(SUB_DIR / "clash", ip, host)
    aug_text_with_urls(LIST_FILE, ip, host)
    print(f"[hostnameify] rewrote {ip} -> {host}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
