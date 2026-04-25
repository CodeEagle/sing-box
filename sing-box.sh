#!/usr/bin/env bash
# CodeEagle/sing-box: thin wrapper around fscarmen/sing-box main script.
#
# Why a wrapper:
#   - Auto-applies IPv6 dual-stack post-processor (hostnameify or v6 mirror)
#     after fscarmen finishes, based on /etc/sing-box/dualstack.env.
#   - Patches upstream's create_shortcut so the regenerated /etc/sing-box/sb.sh
#     points back to this fork. Any subsequent `sb` invocation (including
#     ones fscarmen itself triggers) keeps post-processing alive.
#
# Configure post-processor mode via /etc/sing-box/dualstack.env:
#   HOSTNAME_TARGET="vps.example.com"   # hostnameify mode (recommended)
#   # or
#   DUALSTACK_MIRROR=1                  # v6 mirror mode
#
# install-dualstack.sh writes that file for you.

set -o pipefail

WORK_DIR="${WORK_DIR:-/etc/sing-box}"
ENV_FILE="$WORK_DIR/dualstack.env"
FORK_RAW_BASE="https://raw.githubusercontent.com/CodeEagle/sing-box/main"
UPSTREAM_URL="https://raw.githubusercontent.com/fscarmen/sing-box/main/sing-box.sh"

fetch() {
    local target="$1" url="$2"
    if command -v wget >/dev/null 2>&1; then
        wget --no-check-certificate -qO "$target" "$url"
    elif command -v curl >/dev/null 2>&1; then
        curl -fsSL -o "$target" "$url"
    else
        echo "[CodeEagle/sing-box] need wget or curl" >&2
        return 1
    fi
}

ensure_helpers() {
    [ -d "$WORK_DIR" ] || mkdir -p "$WORK_DIR"
    for f in sb-hostnameify.py sb-dualstack.py; do
        if [ ! -x "$WORK_DIR/$f" ]; then
            fetch "$WORK_DIR/$f" "$FORK_RAW_BASE/extras/$f" || true
            [ -f "$WORK_DIR/$f" ] && chmod +x "$WORK_DIR/$f"
        fi
    done
}

# 1) Pull upstream
TMP=$(mktemp)
trap 'rm -f "$TMP"' EXIT
if ! fetch "$TMP" "$UPSTREAM_URL"; then
    echo "[CodeEagle/sing-box] failed to fetch upstream" >&2
    exit 1
fi

# 2) Patch upstream: redirect generated sb.sh URL to this fork so the
#    `sb` shortcut keeps routing through the wrapper after fscarmen
#    runs create_shortcut.
sed -i.bak 's|raw\.githubusercontent\.com/fscarmen/sing-box/main/sing-box\.sh|raw.githubusercontent.com/CodeEagle/sing-box/main/sing-box.sh|g' "$TMP"
rm -f "$TMP.bak"

# 3) Run upstream
bash "$TMP" "$@"
RC=$?

# 4) Post-process based on dualstack.env (idempotent)
ensure_helpers
if [ -f "$ENV_FILE" ]; then
    set -a
    . "$ENV_FILE"
    set +a
fi

if [ -d "$WORK_DIR/subscribe" ]; then
    if [ -n "${HOSTNAME_TARGET:-}" ] && [ -x "$WORK_DIR/sb-hostnameify.py" ]; then
        HOSTNAME_TARGET="$HOSTNAME_TARGET" \
        SERVER_IP_LITERAL="${SERVER_IP_LITERAL:-}" \
            "$WORK_DIR/sb-hostnameify.py" 2> >(sed 's/^/[hostnameify] /' >&2) || true
    elif [ "${DUALSTACK_MIRROR:-}" = "1" ] && [ -x "$WORK_DIR/sb-dualstack.py" ]; then
        "$WORK_DIR/sb-dualstack.py" 2> >(sed 's/^/[dualstack] /' >&2) || true

        UPPER_ARGS=$(printf '%s ' "$@" | tr '[:lower:]' '[:upper:]')
        case " $UPPER_ARGS " in
            *" -N "*)
                [ -s "$WORK_DIR/list" ] && \
                    awk '/### DUALSTACK_BEGIN ###/,/### DUALSTACK_END ###/' "$WORK_DIR/list"
                ;;
        esac
    fi
fi

exit "$RC"
