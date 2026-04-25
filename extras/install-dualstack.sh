#!/usr/bin/env bash
# install-dualstack.sh: installs IPv6 dual-stack post-processors atop
# fscarmen's sing-box installation.
#
# Modes:
#   1) Hostname mode  (recommended if you own a dual-stack domain)
#       - Sets HOSTNAME_TARGET in /etc/sing-box/dualstack.env
#       - Each protocol becomes a single entry using the hostname
#       - Clients use Happy Eyeballs (RFC 8305) to pick v4 or v6
#
#   2) Dual-stack mirror mode
#       - Sets DUALSTACK_MIRROR=1 in /etc/sing-box/dualstack.env
#       - Each protocol gets one v4 entry + one v6 mirror entry
#
# Usage:
#   bash <(curl -fsSL <RAW_URL>/extras/install-dualstack.sh) hostname vps.example.com
#   bash <(curl -fsSL <RAW_URL>/extras/install-dualstack.sh) mirror
#   bash <(curl -fsSL <RAW_URL>/extras/install-dualstack.sh) off

set -e

RAW_BASE="${RAW_BASE:-https://raw.githubusercontent.com/CodeEagle/sing-box/main/extras}"
WORK_DIR="${WORK_DIR:-/etc/sing-box}"

if [ ! -d "$WORK_DIR" ]; then
    echo "[install-dualstack] $WORK_DIR not found. Install fscarmen sing-box first." >&2
    exit 1
fi

mode="${1:-}"
arg="${2:-}"

fetch() {
    local target="$1" url="$2"
    if command -v wget >/dev/null 2>&1; then
        wget --no-check-certificate -qO "$target" "$url"
    elif command -v curl >/dev/null 2>&1; then
        curl -fsSL -o "$target" "$url"
    else
        echo "[install-dualstack] need wget or curl" >&2
        exit 1
    fi
}

install_helpers() {
    fetch "$WORK_DIR/sb-hostnameify.py" "$RAW_BASE/sb-hostnameify.py"
    fetch "$WORK_DIR/sb-dualstack.py"   "$RAW_BASE/sb-dualstack.py"
    fetch "$WORK_DIR/sb-wrapper.sh"     "$RAW_BASE/sb-wrapper.sh"
    chmod +x "$WORK_DIR/sb-hostnameify.py" "$WORK_DIR/sb-dualstack.py" "$WORK_DIR/sb-wrapper.sh"
}

write_env() {
    local content="$1"
    printf '%s\n' "$content" > "$WORK_DIR/dualstack.env"
    chmod 600 "$WORK_DIR/dualstack.env"
}

activate_wrapper() {
    [ -f "$WORK_DIR/sb.sh" ] && [ ! -f "$WORK_DIR/sb.sh.original" ] \
        && cp -a "$WORK_DIR/sb.sh" "$WORK_DIR/sb.sh.original"
    cp "$WORK_DIR/sb-wrapper.sh" "$WORK_DIR/sb.sh"
    chmod +x "$WORK_DIR/sb.sh"
    ln -sf "$WORK_DIR/sb.sh" /usr/bin/sb
}

case "$mode" in
    hostname)
        if [ -z "$arg" ]; then
            echo "Usage: install-dualstack.sh hostname <fqdn>" >&2
            exit 1
        fi
        install_helpers
        write_env "HOSTNAME_TARGET=$arg"
        activate_wrapper
        echo "[install-dualstack] hostname mode active: $arg"
        echo "[install-dualstack] run 'sb -n' to apply."
        ;;
    mirror)
        install_helpers
        write_env "DUALSTACK_MIRROR=1"
        activate_wrapper
        echo "[install-dualstack] dual-stack mirror mode active."
        echo "[install-dualstack] run 'sb -n' to apply."
        ;;
    off)
        rm -f "$WORK_DIR/dualstack.env"
        if [ -f "$WORK_DIR/sb.sh.original" ]; then
            cp "$WORK_DIR/sb.sh.original" "$WORK_DIR/sb.sh"
        fi
        echo "[install-dualstack] disabled. Wrapper still installed but no-op."
        ;;
    *)
        cat <<EOF
install-dualstack.sh — IPv6 dual-stack post-processor for fscarmen sing-box

Usage:
  install-dualstack.sh hostname <fqdn>   Use hostname mode (preferred)
  install-dualstack.sh mirror            Use v6 mirror mode
  install-dualstack.sh off               Disable post-processing
EOF
        ;;
esac
