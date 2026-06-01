#!/usr/bin/env bash
# TravelRouter installer — run as root on a fresh Raspberry Pi OS:
#   curl -fsSL https://raw.githubusercontent.com/DrevOliv/RaspberryPiRouter/main/deploy/install.sh | sudo bash
#
# Sets up the whole travel-router networking stack (NetworkManager, static IP,
# dnsmasq, hostapd, IP forwarding, NAT) and installs the app + service. After
# this, configure everything else from the web UI.
#
# Tailscale is optional and NOT installed here — see docs/manual-setup.md.
# Override any default by exporting it first, e.g.:  AP_IFACE=wlan2 COUNTRY=SE sudo -E bash install.sh
#
# Note: this restarts NetworkManager, so run it from a console/ethernet rather
# than over upstream Wi-Fi if you can.
set -euo pipefail

# ── Settings (override via environment) ──────────────────────────────────────
APP_DIR=/opt/travelrouter
APP_USER=travelrouter
REPO_URL="${REPO_URL:-https://github.com/DrevOliv/RaspberryPiRouter.git}"

UPSTREAM_IFACE="${UPSTREAM_IFACE:-wlan0}"     # joins hotel/cafe Wi-Fi
AP_IFACE="${AP_IFACE:-wlan1}"                 # broadcasts the private AP
ETH_IFACE="${ETH_IFACE:-eth0}"                # wired upstream (optional)
AP_IP="${AP_IP:-192.168.50.1}"
DHCP_START="${DHCP_START:-192.168.50.2}"
DHCP_END="${DHCP_END:-192.168.50.100}"
COUNTRY="${COUNTRY:-00}"                       # wifi regulatory domain; set yours in the UI
AP_SSID="${AP_SSID:-RouterPi}"
AP_PASSPHRASE="${AP_PASSPHRASE:-Password123}"

[[ $EUID -eq 0 ]] || { echo "Run as root (e.g. pipe to 'sudo bash')." >&2; exit 1; }

# ── Packages ─────────────────────────────────────────────────────────────────
apt-get update -qq
apt-get install -y -qq \
  hostapd dnsmasq network-manager iw iptables-persistent \
  git python3-venv rsync openssh-client

# ── Service user ─────────────────────────────────────────────────────────────
id "$APP_USER" &>/dev/null || useradd -m -s /bin/bash "$APP_USER"
usermod -aG netdev "$APP_USER"   # reach the hostapd control socket

# ── NetworkManager: manage upstream, leave the AP interface to hostapd ───────
systemctl enable --now NetworkManager
mkdir -p /etc/NetworkManager/conf.d
cat > /etc/NetworkManager/conf.d/unmanaged.conf <<EOF
[keyfile]
unmanaged-devices=interface-name:${AP_IFACE}
EOF
systemctl restart NetworkManager

# ── Static IP on the AP interface (brought up before hostapd) ────────────────
cat > /etc/systemd/system/wlan-static-ip.service <<EOF
[Unit]
Description=Static IP for ${AP_IFACE} (AP interface)
Before=hostapd.service
Wants=network.target

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/usr/sbin/ip addr add ${AP_IP}/24 dev ${AP_IFACE}
ExecStart=-/usr/sbin/iw dev ${AP_IFACE} set power_save off
ExecStop=/usr/sbin/ip addr del ${AP_IP}/24 dev ${AP_IFACE}

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable --now wlan-static-ip.service

# ── DHCP for AP clients (dnsmasq) ────────────────────────────────────────────
cat > /etc/dnsmasq.d/travelrouter.conf <<EOF
interface=${AP_IFACE}
dhcp-range=${DHCP_START},${DHCP_END},12h
dhcp-option=3,${AP_IP}
dhcp-option=6,8.8.8.8,1.1.1.1
EOF
systemctl enable dnsmasq
systemctl restart dnsmasq

# ── hostapd (initial config only; the app owns it afterwards) ────────────────
mkdir -p /etc/hostapd
if [[ ! -f /etc/hostapd/hostapd.conf ]]; then
  cat > /etc/hostapd/hostapd.conf <<EOF
interface=${AP_IFACE}
driver=nl80211
ssid=${AP_SSID}
country_code=${COUNTRY}
hw_mode=g
channel=6
ieee80211n=1
wmm_enabled=1
wpa=2
wpa_key_mgmt=WPA-PSK SAE
rsn_pairwise=CCMP
wpa_passphrase=${AP_PASSPHRASE}
ieee80211w=1
sae_require_mfp=1
auth_algs=1
ignore_broadcast_ssid=0
ctrl_interface=/var/run/hostapd
ctrl_interface_group=netdev
EOF
fi
systemctl unmask hostapd
systemctl enable --now hostapd

# ── Prefer ethernet over Wi-Fi for upstream ──────────────────────────────────
cat > /etc/NetworkManager/dispatcher.d/10-route-metric <<EOF
#!/bin/bash
if [ "\$2" = "up" ]; then
    [ "\$DEVICE_IFACE" = "${UPSTREAM_IFACE}" ] && nmcli connection modify "\$CONNECTION_UUID" ipv4.route-metric 100
    [ "\$DEVICE_IFACE" = "${ETH_IFACE}" ] && nmcli connection modify "\$CONNECTION_UUID" ipv4.route-metric 50
fi
EOF
chmod +x /etc/NetworkManager/dispatcher.d/10-route-metric

# ── IP forwarding + NAT ──────────────────────────────────────────────────────
echo 'net.ipv4.ip_forward=1' > /etc/sysctl.d/99-travelrouter.conf
sysctl -q -p /etc/sysctl.d/99-travelrouter.conf

ensure_rule() {  # ensure_rule <table> <rule...> — append only if not already present
  local table="$1"; shift
  iptables -t "$table" -C "$@" 2>/dev/null || iptables -t "$table" -A "$@"
}
for up in "$UPSTREAM_IFACE" "$ETH_IFACE" tailscale0; do
  ensure_rule nat    POSTROUTING -o "$up" -j MASQUERADE
  ensure_rule filter FORWARD -i "$AP_IFACE" -o "$up" -j ACCEPT
  ensure_rule filter FORWARD -i "$up" -o "$AP_IFACE" -m state --state RELATED,ESTABLISHED -j ACCEPT
done
netfilter-persistent save

# ── App: code, venv, dependencies ────────────────────────────────────────────
if [[ -d "$APP_DIR/.git" ]]; then
  sudo -u "$APP_USER" git -C "$APP_DIR" pull --ff-only
else
  mkdir -p "$APP_DIR"
  chown "$APP_USER:$APP_USER" "$APP_DIR"
  sudo -u "$APP_USER" git clone "$REPO_URL" "$APP_DIR"
fi
chown -R "$APP_USER:$APP_USER" "$APP_DIR"
sudo -u "$APP_USER" python3 -m venv "$APP_DIR/.venv"
sudo -u "$APP_USER" "$APP_DIR/.venv/bin/pip" install -r "$APP_DIR/requirements.txt"

# ── App: env file, privileged helper, sudoers ───────────────────────────────
[[ -f "$APP_DIR/travelrouter.env" ]] ||
  sudo -u "$APP_USER" cp "$APP_DIR/travelrouter.env.example" "$APP_DIR/travelrouter.env"
install -m 755 "$APP_DIR/deploy/travelrouter-hostapd" /usr/local/sbin/travelrouter-hostapd
install -m 440 "$APP_DIR/deploy/sudoers.travelrouter" /etc/sudoers.d/travelrouter
visudo -c

# ── App: service ─────────────────────────────────────────────────────────────
ln -sf "$APP_DIR/travelrouter.service" /etc/systemd/system/travelrouter.service
systemctl daemon-reload
systemctl enable --now travelrouter

echo "Done. Open http://<pi-ip>:8080 (default password: changeme)."
echo "Check: systemctl status travelrouter"
