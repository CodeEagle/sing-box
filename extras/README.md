# IPv6 Dual-Stack Post-Processors for fscarmen sing-box

This `extras/` directory provides idempotent post-processors that augment
fscarmen's `sing-box.sh` subscribe outputs with IPv6 dual-stack reachability,
without forking the upstream script logic.

## Why

fscarmen's `sing-box.sh` writes a single literal `SERVER_IP` (IPv4 by default
on dual-stack hosts) into every subscribe URL/YAML/JSON. Even when the VPS has
both `0.0.0.0` and `::` listeners and global IPv6, clients can only reach the
VPS over IPv4 because subscribe content advertises IPv4 only.

Two strategies are offered:

| Mode | What it does | When to use |
|------|--------------|-------------|
| **hostname** | Replaces literal IPv4 with a dual-stack hostname (one entry per protocol). OS Happy Eyeballs (RFC 8305) picks v4 or v6 per dial. | You own a domain (free Cloudflare subdomain works). DNS records: A → v4, AAAA → v6, **DNS only / unproxied**. |
| **mirror** | Appends a v6 mirror entry per protocol (two entries per protocol: v4 and v6). | No domain available. |

The hostname mode is preferred: smaller node lists, transparent failover, no
client-side selection logic needed.

## Files

| File | Purpose |
|------|---------|
| `sb-hostnameify.py` | Rewrites IPv4 literal → hostname in all subscribe files |
| `sb-dualstack.py` | Adds IPv6 mirror entries to all subscribe files |
| `sb-wrapper.sh` | Drop-in replacement for `/etc/sing-box/sb.sh` that runs upstream + post-processor |
| `install-dualstack.sh` | One-shot installer that wires it all up |

## Quick start

After installing fscarmen sing-box, run one of:

### Hostname mode (recommended)

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/CodeEagle/sing-box/main/extras/install-dualstack.sh) hostname vps.example.com
sb -n
```

`vps.example.com` must resolve to both A and AAAA records pointing at the VPS.
If using Cloudflare, **set Proxy status to DNS only (gray cloud)** — orange
cloud terminates TCP and breaks Reality/XTLS/Hysteria2/TUIC handshakes.

### Mirror mode

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/CodeEagle/sing-box/main/extras/install-dualstack.sh) mirror
sb -n
```

### Disable

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/CodeEagle/sing-box/main/extras/install-dualstack.sh) off
```

## Persisted config

`/etc/sing-box/dualstack.env` records the active mode:

```
HOSTNAME_TARGET=vps.example.com
# or
DUALSTACK_MIRROR=1
```

## What gets rewritten

The post-processors operate on these files in `/etc/sing-box/`:

- `subscribe/proxies` (Clash provider YAML)
- `subscribe/clash`, `subscribe/clash2` (top-level Clash)
- `subscribe/v2rayn`, `subscribe/shadowrocket`, `subscribe/neko` (base64 URL lists)
- `subscribe/sing-box` (sing-box JSON outbounds)
- `subscribe/qr` (QR display + URL examples)
- `list` (the `sb -n` display)

For URL forms with the host inside base64 (`ss://`, Shadowrocket-style
`vless://YXV0bz...?remarks=`), the base64 is decoded, rewritten, re-encoded.

## Caveats

- `vmess-ws` / `vless-ws-tls` entries pointing at a CDN (e.g. `skk.moe` via
  Cloudflare Argo) are **not** rewritten — those go through the CDN, not the
  VPS directly.
- ShadowTLS in NekoBox uses a `nekoray://custom#<b64-json>` form with the
  server inside JSON inside base64 in the fragment; this format is currently
  not rewritten.
- If you re-run fscarmen's full install/uninstall path, the `create_shortcut`
  function regenerates `/etc/sing-box/sb.sh`, removing the wrapper. Re-run
  `install-dualstack.sh` to restore.
- For VPS outbound traffic to also prefer IPv6 (so visited sites see your v6
  exit), set on the `direct` outbound in `/etc/sing-box/conf/01_outbounds.json`:
  ```json
  {
      "type": "direct",
      "tag": "direct",
      "domain_resolver": {"server": "local", "strategy": "prefer_ipv6"}
  }
  ```
  And add a tagged `local` DNS server in `05_dns.json`.

## Idempotency

Running the post-processor multiple times is safe — markers (`%20IPv6`,
`@[v6]:`, `### DUALSTACK_BEGIN/END ###`, ` IPv6` tag suffix) are detected and
stale additions stripped before re-applying.
