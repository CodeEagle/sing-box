#!/usr/bin/env bash
# Minimal sb shortcut: routes every `sb` invocation through the
# CodeEagle/sing-box wrapper (which fetches upstream, patches it, runs
# it, and applies IPv6 dual-stack post-processing).
#
# This file is what install-dualstack.sh writes to /etc/sing-box/sb.sh.
# The fork's sing-box.sh patches fscarmen's create_shortcut so that when
# fscarmen regenerates this file, the URL still points back to the fork —
# preserving the post-processing loop.

bash <(wget --no-check-certificate -qO- https://raw.githubusercontent.com/CodeEagle/sing-box/main/sing-box.sh) "$@"
