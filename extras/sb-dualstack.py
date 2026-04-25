#!/usr/bin/env python3
"""sb-dualstack: augment fscarmen sing-box subscribe outputs with IPv6 dual-stack
mirror entries (one extra entry per protocol with the v6 server address).

Use this when you do NOT own a dual-stack hostname; otherwise prefer the
sb-hostnameify.py approach which yields a single entry per protocol with OS
Happy Eyeballs handling.

Idempotent. Designed to run after fscarmen's sing-box.sh.

Files processed under /etc/sing-box/:
    subscribe/proxies        (Clash provider yaml)
    subscribe/clash2         (full clash YAML)
    subscribe/v2rayn         (base64 URL list)
    subscribe/shadowrocket   (base64 URL list)
    subscribe/neko           (base64 URL list)
    subscribe/sing-box       (sing-box JSON)
    subscribe/qr             (display + URL examples)
    list                     (sb -n display)
"""
from __future__ import annotations

import base64
import ipaddress
import json
import os
import re
import subprocess
import sys
from pathlib import Path

WORK_DIR = Path(os.environ.get("SB_WORK_DIR", "/etc/sing-box"))
SUB_DIR = WORK_DIR / "subscribe"
LIST_FILE = WORK_DIR / "list"
NGINX_CONF = WORK_DIR / "nginx.conf"

V6_TAG = " IPv6"
MARK_BEGIN = "### DUALSTACK_BEGIN ###"
MARK_END = "### DUALSTACK_END ###"

_NAME_RE = re.compile(r'(?<![\w-])name:\s*"([^"]+)"')
_ANSI_RE = re.compile(r'\x1b\[[0-9;]*m')
_SCHEME_B64_RE = re.compile(r"^([a-z][a-z0-9+\-.]*)://([A-Za-z0-9+/_=\-]+)(.*)$")


def _detect_addr(family: int) -> str | None:
    flag = "-4" if family == 4 else "-6"
    out = subprocess.run(
        ["ip", flag, "-o", "addr", "show", "scope", "global"],
        capture_output=True, text=True, check=False,
    ).stdout
    for line in out.splitlines():
        m = re.search(r"inet6?\s+([0-9a-fA-F:.]+)/", line)
        if not m:
            continue
        try:
            ip = ipaddress.ip_address(m.group(1))
        except ValueError:
            continue
        if ip.is_link_local or ip.is_loopback or ip.is_private:
            continue
        return m.group(1)
    return None


def get_addrs() -> tuple[str | None, str | None]:
    return _detect_addr(4), _detect_addr(6)


def get_nginx_port() -> str | None:
    if not NGINX_CONF.is_file():
        return None
    for line in NGINX_CONF.read_text().splitlines():
        m = re.match(r"\s*listen\s+(\d+)\s*;.*ipv4", line)
        if m:
            return m.group(1)
    return None


def _strip_v6_block(text: str) -> str:
    return re.sub(
        rf"{re.escape(MARK_BEGIN)}.*?{re.escape(MARK_END)}\n?",
        "", text, flags=re.DOTALL,
    )


def _yaml_aug_line(ln: str, v4: str, v6: str) -> str | None:
    if not re.search(rf"(?<![\w-])server:\s*{re.escape(v4)}\b", ln):
        return None
    new = re.sub(
        rf"(?<![\w-])server:\s*{re.escape(v4)}\b",
        f'server: "{v6}"',
        ln,
        count=1,
    )
    new = _NAME_RE.sub(lambda m: f'name: "{m.group(1)}{V6_TAG}"', new, count=1)
    return new


def aug_proxies(path: Path, v4: str, v6: str) -> None:
    if not path.is_file():
        return
    lines = path.read_text().splitlines()
    cleaned = [ln for ln in lines if f'{V6_TAG}"' not in ln]
    additions = []
    for ln in cleaned:
        new = _yaml_aug_line(ln, v4, v6)
        if new:
            additions.append(new)
    path.write_text("\n".join(cleaned + additions) + "\n")


def aug_clash2(path: Path, v4: str, v6: str) -> None:
    if not path.is_file():
        return
    lines = path.read_text().splitlines()
    out = []
    in_proxies = False
    proxies_indent = 0
    proxy_lines: list[str] = []

    def flush():
        cleaned = [pl for pl in proxy_lines if f'{V6_TAG}"' not in pl]
        adds = []
        for pl in cleaned:
            new = _yaml_aug_line(pl, v4, v6)
            if new:
                adds.append(new)
        return cleaned + adds

    for ln in lines:
        stripped = ln.lstrip()
        indent = len(ln) - len(stripped)
        if not in_proxies:
            out.append(ln)
            if re.match(r"^proxies\s*:\s*$", ln):
                in_proxies = True
                proxies_indent = indent
            continue
        if stripped == "" or (stripped.startswith("- ") and indent > proxies_indent):
            proxy_lines.append(ln)
            continue
        out.extend(flush())
        proxy_lines = []
        in_proxies = False
        out.append(ln)
    if in_proxies:
        out.extend(flush())
    path.write_text("\n".join(out) + "\n")


def _suffix_frag(url: str) -> str:
    if "#" in url:
        head, frag = url.rsplit("#", 1)
        if "%20IPv6" in frag or frag.endswith(" IPv6"):
            return url
        return f"{head}#{frag}%20IPv6"
    m = re.search(r"(.*[?&]remarks=)([^&#]*)(.*)$", url)
    if m:
        name = m.group(2)
        if "%20IPv6" in name or "IPv6" in name:
            return url
        return f"{m.group(1)}{name}%20IPv6{m.group(3)}"
    return f"{url}#IPv6"


def _aug_b64_userinfo_url(url: str, v4: str, v6: str) -> str | None:
    m = _SCHEME_B64_RE.match(url)
    if not m:
        return None
    scheme, b64part, rest = m.group(1), m.group(2), m.group(3)
    try:
        pad = (-len(b64part)) % 4
        decoded = base64.b64decode(b64part + "=" * pad).decode("utf-8", "replace")
    except Exception:
        return None
    if f"@{v4}:" not in decoded:
        return None
    new_decoded = decoded.replace(f"@{v4}:", f"@[{v6}]:", 1)
    new_b64 = base64.b64encode(new_decoded.encode("utf-8")).decode("ascii").rstrip("=")
    return _suffix_frag(f"{scheme}://{new_b64}{rest}")


def _aug_url(url: str, v4: str, v6: str) -> str | None:
    if f"@{v4}:" in url:
        return _suffix_frag(url.replace(f"@{v4}:", f"@[{v6}]:", 1))
    return _aug_b64_userinfo_url(url, v4, v6)


def aug_v2rayn_style(path: Path, v4: str, v6: str) -> None:
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
    cleaned = [
        ln for ln in lines
        if f"@[{v6}]:" not in ln
        and "%20IPv6" not in ln
        and not ln.endswith("#IPv6")
    ]
    additions = []
    for ln in cleaned:
        new = _aug_url(ln, v4, v6)
        if new:
            additions.append(new)
    body = "\n".join(cleaned + additions)
    path.write_text(base64.b64encode(body.encode("utf-8")).decode("ascii"))


def aug_singbox(path: Path, v4: str, v6: str) -> None:
    if not path.is_file():
        return
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError:
        return
    outs = data.get("outbounds", [])
    outs = [o for o in outs if not str(o.get("tag", "")).endswith(V6_TAG)]
    seen = set()
    additions = []
    for o in outs:
        if o.get("server") == v4:
            new = json.loads(json.dumps(o))
            new["tag"] = f"{o['tag']}{V6_TAG}"
            new["server"] = v6
            if new["tag"] in seen:
                continue
            seen.add(new["tag"])
            additions.append(new)
    outs.extend(additions)
    data["outbounds"] = outs
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")


def aug_qr(path: Path, v4: str, v6: str, port: str | None) -> None:
    if not path.is_file() or not port:
        return
    text = _strip_v6_block(path.read_text())
    m = re.search(rf"http://{re.escape(v4)}:{port}/([^/]+)/auto", text)
    if not m:
        path.write_text(text)
        return
    uuid = m.group(1)
    block = (
        f"\n{MARK_BEGIN}\n"
        f"IPv6 dual-stack subscription URLs:\n"
        f"http://[{v6}]:{port}/{uuid}/auto\n"
        f"http://[{v6}]:{port}/{uuid}/auto2\n"
        f"{MARK_END}\n"
    )
    path.write_text(text + block)


def aug_list(path: Path, v4: str, v6: str, port: str | None) -> None:
    if not path.is_file():
        return
    text = _strip_v6_block(path.read_text())
    v6_urls = []
    url_re = re.compile(r'([a-z][a-z0-9+\-.]*://\S+?)(?:\x1b\[[0-9;]*m|\s|$)')
    for ln in text.splitlines():
        clean = _ANSI_RE.sub('', ln).strip()
        if f"@{v4}:" not in clean:
            continue
        m = url_re.search(ln + " ")
        if not m:
            continue
        url = _ANSI_RE.sub('', m.group(1))
        n = _aug_url(url, v4, v6)
        if n and n not in v6_urls:
            v6_urls.append(n)
    sub_block = ""
    if port:
        m = re.search(rf"http://{re.escape(v4)}:{port}/([^/]+)/auto", text)
        if m:
            uuid = m.group(1)
            sub_block = (
                f"\nIPv6 dual-stack subscription:\n"
                f"  http://[{v6}]:{port}/{uuid}/auto\n"
                f"  http://[{v6}]:{port}/{uuid}/auto2\n"
            )
    body = "\n".join(f"----------------------------\n{u}" for u in v6_urls)
    block = (
        f"\n\n{MARK_BEGIN}\n"
        f"*******************************************\n"
        f"|   IPv6 Dual-Stack Mirror Nodes   |\n"
        f"{sub_block}\n"
        f"{body}\n"
        f"{MARK_END}\n"
    )
    path.write_text(text + block)


def main() -> int:
    v4, v6 = get_addrs()
    if not v6:
        print("[sb-dualstack] no global IPv6 detected; skip.", file=sys.stderr)
        return 0
    if not v4:
        print("[sb-dualstack] no global IPv4 detected; skip.", file=sys.stderr)
        return 0
    port = get_nginx_port()
    aug_proxies(SUB_DIR / "proxies", v4, v6)
    aug_clash2(SUB_DIR / "clash2", v4, v6)
    aug_v2rayn_style(SUB_DIR / "v2rayn", v4, v6)
    aug_v2rayn_style(SUB_DIR / "shadowrocket", v4, v6)
    aug_v2rayn_style(SUB_DIR / "neko", v4, v6)
    aug_singbox(SUB_DIR / "sing-box", v4, v6)
    aug_qr(SUB_DIR / "qr", v4, v6, port)
    aug_list(LIST_FILE, v4, v6, port)
    print(f"[sb-dualstack] augmented v4={v4} v6={v6} port={port}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
