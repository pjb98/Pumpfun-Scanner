#!/usr/bin/env bash
# Install the Pumpfun Scanner as a systemd service that auto-starts on boot,
# auto-restarts on crash, and collects best-times history unattended.
#
#   sudo ./install_service.sh
#
# Re-run any time to pick up code/unit changes.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$HERE/.venv"

if [[ $EUID -ne 0 ]]; then
  echo "Run with sudo: sudo $0" >&2
  exit 1
fi

# 1. venv + deps
if [[ ! -x "$VENV/bin/python" ]]; then
  echo "Creating venv at $VENV"
  python3 -m venv "$VENV"
fi
"$VENV/bin/pip" install -q --upgrade pip
"$VENV/bin/pip" install -q -r "$HERE/requirements.txt"

# 2. render each unit with this repo's actual paths, then install it.
# Executable path is double-quoted so a space in $HERE doesn't break systemd's
# whitespace tokenization of ExecStart.
install_unit() {
  local name="$1" cmd="$2"
  echo "Installing /etc/systemd/system/$name.service"
  sed \
    -e "s#^WorkingDirectory=.*#WorkingDirectory=$HERE#" \
    -e "s#^ExecStart=.*#ExecStart=\"$VENV/bin/python\" $cmd#" \
    -e "s#^EnvironmentFile=.*#EnvironmentFile=-$HERE/.env#" \
    "$HERE/$name.service" > "/etc/systemd/system/$name.service"
}

install_unit "pumpfun-scanner"   "monitor.py --headless"
install_unit "pumpfun-dashboard" "dashboard.py"

# 3. enable + (re)start both
systemctl daemon-reload
for name in pumpfun-scanner pumpfun-dashboard; do
  systemctl enable "$name"
  systemctl restart "$name"
done

echo
echo "Done. Monitor collects heat; dashboard serves it (default http://127.0.0.1:8787)."
echo "Useful commands:"
echo "  systemctl status pumpfun-scanner pumpfun-dashboard"
echo "  journalctl -u pumpfun-scanner -f          # live status lines"
echo "  journalctl -u pumpfun-dashboard -f"
echo "  systemctl disable --now pumpfun-scanner pumpfun-dashboard   # stop both"
echo
echo "Dashboard is localhost-only by default. To reach it in a browser either:"
echo "  ssh -L 8787:localhost:8787 <this-vps>     # then open http://localhost:8787"
echo "  or set DASHBOARD_HOST=0.0.0.0 in $HERE/.env and re-run this script."
