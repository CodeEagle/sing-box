#!/usr/bin/env bash
# sb-wrapper: drop-in replacement for the `sb` shortcut installed by
# fscarmen's sing-box.sh. Calls upstream, then runs IPv6 dual-stack
# post-processing.
#
# Behavior is selected by env vars (or persisted in /etc/sing-box/dualstack.env):
#
#   HOSTNAME_TARGET="vps.example.com"
#       Use hostnameify mode — replaces literal IPv4 with the hostname in
#       all subscribe outputs. Recommended when you own a dual-stack domain.
#
#   DUALSTACK_MIRROR=1
#       Use dualstack-mirror mode — appends an IPv6 mirror entry per
#       protocol. Use when no domain is available but VPS has v6.
#
# If neither is set, behaves identically to upstream (no post-processing).

WORK_DIR="${WORK_DIR:-/etc/sing-box}"
ENV_FILE="$WORK_DIR/dualstack.env"

# Load persisted env if present
[ -f "$ENV_FILE" ] && set -a && . "$ENV_FILE" && set +a

# Run fscarmen upstream
bash <(wget --no-check-certificate -qO- https://raw.githubusercontent.com/fscarmen/sing-box/main/sing-box.sh) "$@"
RC=$?

# Post-process based on env
if [ -d "$WORK_DIR/subscribe" ]; then
    if [ -n "$HOSTNAME_TARGET" ] && [ -x "$WORK_DIR/sb-hostnameify.py" ]; then
        HOSTNAME_TARGET="$HOSTNAME_TARGET" \
        SERVER_IP_LITERAL="${SERVER_IP_LITERAL:-}" \
            "$WORK_DIR/sb-hostnameify.py" 2> >(sed 's/^/[hostnameify] /' >&2) || true
    elif [ "$DUALSTACK_MIRROR" = "1" ] && [ -x "$WORK_DIR/sb-dualstack.py" ]; then
        "$WORK_DIR/sb-dualstack.py" 2> >(sed 's/^/[dualstack] /' >&2) || true

        UPPER_ARGS=$(printf '%s ' "$@" | tr '[:lower:]' '[:upper:]')
        case " $UPPER_ARGS " in
            *" -N "*)
                if [ -s "$WORK_DIR/list" ]; then
                    awk '/### DUALSTACK_BEGIN ###/,/### DUALSTACK_END ###/' "$WORK_DIR/list"
                fi
                ;;
        esac
    fi
fi

exit "$RC"
