#!/usr/bin/env bash
# Minimal TravelRouter bootstrap installer. Run as root:
#   curl -fsSL https://raw.githubusercontent.com/DrevOliv/RaspberryPiRouter/main/deploy/install.sh | sudo bash
#
# Clones (or updates) the repo to /opt/travelrouter and sets up the service.
# Assumes system networking (NetworkManager, hostapd, dnsmasq, NAT) is already
# configured per the README, and that git + python3 are installed.
set -euo pipefail

APP_DIR=/opt/travelrouter
APP_USER=travelrouter
REPO_URL="${REPO_URL:-https://github.com/DrevOliv/RaspberryPiRouter.git}"

[[ $EUID -eq 0 ]] || { echo "Run as root (e.g. pipe to 'sudo bash')." >&2; exit 1; }

# Service user + hostapd socket access
id "$APP_USER" &>/dev/null || useradd -m -s /bin/bash "$APP_USER"
usermod -aG netdev "$APP_USER"

# Fetch the code
if [[ -d "$APP_DIR/.git" ]]; then
  sudo -u "$APP_USER" git -C "$APP_DIR" pull --ff-only
else
  mkdir -p "$APP_DIR"
  chown "$APP_USER:$APP_USER" "$APP_DIR"
  sudo -u "$APP_USER" git clone "$REPO_URL" "$APP_DIR"
fi
chown -R "$APP_USER:$APP_USER" "$APP_DIR"

# Virtualenv + dependencies
sudo -u "$APP_USER" python3 -m venv "$APP_DIR/.venv"
sudo -u "$APP_USER" "$APP_DIR/.venv/bin/pip" install -r "$APP_DIR/requirements.txt"

# Environment file (kept if it already exists)
[[ -f "$APP_DIR/travelrouter.env" ]] ||
  sudo -u "$APP_USER" cp "$APP_DIR/travelrouter.env.example" "$APP_DIR/travelrouter.env"

# Privileged hostapd helper + sudoers rules
install -m 755 "$APP_DIR/deploy/travelrouter-hostapd" /usr/local/sbin/travelrouter-hostapd
install -m 440 "$APP_DIR/deploy/sudoers.travelrouter" /etc/sudoers.d/travelrouter
visudo -c

# Service
ln -sf "$APP_DIR/travelrouter.service" /etc/systemd/system/travelrouter.service
systemctl daemon-reload
systemctl enable --now travelrouter

echo "Done. Check: systemctl status travelrouter"
