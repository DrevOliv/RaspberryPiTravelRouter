# RaspberryPiRouter

![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-API-009688?logo=fastapi&logoColor=white)
![Uvicorn](https://img.shields.io/badge/Uvicorn-ASGI-499848?logo=uvicorn&logoColor=white)
![License](https://img.shields.io/badge/License-CC0--1.0-lightgrey)

Turn a Raspberry Pi into a portable travel router with a web UI for Wi-Fi control, private access-point management, Tailscale exit-node selection, and admin login.

The private access point is managed by **hostapd** (not NetworkManager). The upstream Wi-Fi connection is managed by **nmcli**.

---

## Hardware

- Raspberry Pi (tested on Pi 4 / Pi Zero 2W)
- Two Wi-Fi interfaces:
  - `wlan0` — connects to the upstream internet (hotel/cafe Wi-Fi)
  - `wlan1` — broadcasts the private access point

A USB Wi-Fi adapter is needed for the second interface. See [`docs/Rtl8812au rpi install guide.md`](docs/Rtl8812au%20rpi%20install%20guide.md) for driver setup on RTL8812AU adapters.

---

## System Setup

Complete these steps once on the Pi before running the app.

### 1. Install packages

```bash
sudo apt update
sudo apt install -y hostapd dnsmasq network-manager
```

Install Tailscale using their official script:

```bash
curl -fsSL https://tailscale.com/install.sh | sh
```

Unmask and stop hostapd — it will be started by the app later:

```bash
sudo systemctl unmask hostapd
sudo systemctl stop hostapd
sudo systemctl disable hostapd
```

Stop dnsmasq for now too:

```bash
sudo systemctl stop dnsmasq
```

---

### 2. Enable NetworkManager and configure interfaces

Enable and start NetworkManager so it manages `wlan0` (upstream Wi-Fi):

```bash
sudo systemctl enable --now NetworkManager
```

Tell NetworkManager to ignore `wlan1` — hostapd and dnsmasq own that interface:

```bash
sudo mkdir -p /etc/NetworkManager/conf.d
sudo tee /etc/NetworkManager/conf.d/unmanaged.conf > /dev/null << 'EOF'
[keyfile]
unmanaged-devices=interface-name:wlan1
EOF

sudo systemctl restart NetworkManager
```

Verify `wlan0` shows as `managed` and `wlan1` as `unmanaged`:

```bash
nmcli device status
```

Expected output:

```
DEVICE   TYPE      STATE        CONNECTION
wlan0    wifi      disconnected --
wlan1    wifi      unmanaged    --
```

`wlan0` will show `disconnected` until you connect to an upstream network through the app.

---

### 3. Assign a static IP to the AP interface

Create a systemd oneshot service that assigns the IP at boot, before hostapd starts. This requires no extra packages and has no interaction with NetworkManager.

```bash
sudo tee /etc/systemd/system/wlan1-static-ip.service > /dev/null << 'EOF'
[Unit]
Description=Static IP for wlan1 (AP interface)
Before=hostapd.service
Wants=network.target

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/usr/sbin/ip addr add 192.168.50.1/24 dev wlan1
ExecStop=/usr/sbin/ip addr del 192.168.50.1/24 dev wlan1

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now wlan1-static-ip.service
```

Verify:

```bash
ip addr show wlan1
```

---

### 4. Configure dnsmasq (DHCP for connected devices)

```bash
sudo tee /etc/dnsmasq.d/travelrouter.conf > /dev/null << 'EOF'
interface=wlan1
dhcp-range=192.168.50.2,192.168.50.100,12h
dhcp-option=3,192.168.50.1
dhcp-option=6,8.8.8.8,1.1.1.1
EOF

sudo systemctl enable dnsmasq
sudo systemctl start dnsmasq
```

---

### 5. Write the initial hostapd config

The app will overwrite this file whenever you change SSID or password through the UI, but it needs an initial config to start from.

> **Change `country_code`** to your country before proceeding.
> Using the wrong country code may violate local radio regulations.

```bash
sudo mkdir -p /etc/hostapd

sudo tee /etc/hostapd/hostapd.conf > /dev/null << 'EOF'
interface=wlan1
driver=nl80211

ssid=RouterPi

country_code=SE

hw_mode=g
channel=6
ieee80211n=1
wmm_enabled=1

wpa=2
wpa_key_mgmt=WPA-PSK SAE
rsn_pairwise=CCMP
wpa_passphrase=Password123

ieee80211w=1
sae_require_mfp=1

auth_algs=1
ignore_broadcast_ssid=0
ctrl_interface=/var/run/hostapd
ctrl_interface_group=netdev
EOF
```

Enable and start hostapd:

```bash
sudo systemctl enable hostapd
sudo systemctl start hostapd
```

Verify the control socket exists:

```bash
ls /var/run/hostapd/wlan1
```

---

### 6. Enable IP forwarding and NAT

```bash
# Persist IP forwarding across reboots
sudo tee /etc/sysctl.d/99-travelrouter.conf > /dev/null << 'EOF'
net.ipv4.ip_forward=1
EOF

sudo sysctl -p /etc/sysctl.d/99-travelrouter.conf

# NAT rules — replace wlan0 with your upstream interface if different
sudo iptables -t nat -A POSTROUTING -o wlan0 -j MASQUERADE
sudo iptables -A FORWARD -i wlan1 -o wlan0 -j ACCEPT
sudo iptables -A FORWARD -i wlan0 -o wlan1 -m state --state RELATED,ESTABLISHED -j ACCEPT

# Save rules so they survive a reboot
sudo apt install -y iptables-persistent
sudo netfilter-persistent save
```

---

## App Setup

### 1. Clone the repository

```bash
git clone git@github.com:DrevOliv/RaspberryPiRouter.git
cd RaspberryPiRouter
```

### 2. Create a virtual environment and install dependencies

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 3. Create a dedicated service user

```bash
sudo useradd --system --no-create-home --shell /usr/sbin/nologin travelrouter

# Allow the service user to reach the hostapd control socket
sudo usermod -aG netdev travelrouter
```

### 4. Install sudoers rules

The app needs to run `nmcli`, `tailscale`, `systemctl` (for hostapd), and write the hostapd config file.

```bash
# Detect correct binary paths
NMCLI=$(which nmcli)
TAILSCALE=$(which tailscale)

sudo tee /etc/sudoers.d/travelrouter > /dev/null << EOF
travelrouter ALL=(ALL) NOPASSWD: $NMCLI
travelrouter ALL=(ALL) NOPASSWD: $TAILSCALE
travelrouter ALL=(ALL) NOPASSWD: /usr/bin/cp
travelrouter ALL=(ALL) NOPASSWD: /usr/bin/systemctl start hostapd
travelrouter ALL=(ALL) NOPASSWD: /usr/bin/systemctl stop hostapd
travelrouter ALL=(ALL) NOPASSWD: /usr/bin/systemctl restart hostapd
EOF

sudo chmod 440 /etc/sudoers.d/travelrouter

# Validate
sudo visudo -c
```

### 5. Copy the app to its install location

```bash
sudo cp -r . /opt/travelrouter
sudo chown -R travelrouter:travelrouter /opt/travelrouter

# Create the virtual environment as the service user
sudo -u travelrouter python3 -m venv /opt/travelrouter/.venv
sudo -u travelrouter /opt/travelrouter/.venv/bin/pip install -r /opt/travelrouter/requirements.txt
```

### 6. Create the systemd service

```bash
sudo tee /etc/systemd/system/travelrouter.service > /dev/null << 'EOF'
[Unit]
Description=TravelRouter Web Service
After=network-online.target hostapd.service
Wants=network-online.target

[Service]
Type=simple
User=travelrouter
Group=travelrouter
WorkingDirectory=/opt/travelrouter
ExecStart=/opt/travelrouter/.venv/bin/python app.py
Restart=on-failure
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now travelrouter
```

Check it started correctly:

```bash
sudo systemctl status travelrouter
journalctl -u travelrouter -f
```

---

## First Login

Open `http://<pi-ip>:8080/` in your browser. The default password is:

```
changeme
```

Change it immediately from the Settings page.

---

## Configuration

App behaviour can be overridden with environment variables. Add them to the `[Service]` block in the systemd unit as `Environment=KEY=value`.

| Variable | Description | Default |
| --- | --- | --- |
| `TRAVELROUTER_AUTH_COOKIE_NAME` | Session cookie name | `tr_session` |
| `TRAVELROUTER_AUTH_SESSION_TTL_SECONDS` | Session lifetime in seconds | `86400` |
| `TRAVELROUTER_AUTH_SECURE_COOKIE` | Set secure flag on cookies (use behind HTTPS) | `false` |
| `TRAVELROUTER_DATA_FILE_PATH` | Path to the JSON config file | `./data/data.json` |

---

## How It Works

```
          Internet
             │
           wlan0  ← nmcli connects this to upstream Wi-Fi
             │
        [Raspberry Pi]
             │
           wlan1  ← hostapd broadcasts the private AP
             │
       Connected devices  ← dnsmasq assigns IPs (192.168.50.x)
```

The Python app communicates with hostapd via its UNIX control socket (`/var/run/hostapd/wlan1`) to list clients, reload config, and manage the service. Config changes (SSID, password) are written to `/etc/hostapd/hostapd.conf` and applied with a `RELOAD` command over the socket.

---

## Project Structure

```
.
├── app.py
├── requirements.txt
├── TravelRouter/
│   ├── __init__.py
│   ├── static/
│   │   ├── index.html
│   │   ├── login.html
│   │   ├── settings.html
│   │   └── style.css
│   ├── helpers/
│   ├── config_file/
│   └── components/
│       ├── auth/
│       ├── settings/
│       ├── tailscale/
│       └── wifi/
│           ├── hostapd.py          # HostapdController — socket comms + service control
│           ├── hostapd_config.py   # Config file model
│           ├── system_api.py       # nmcli wrappers for upstream Wi-Fi
│           ├── functions.py        # Parsing helpers
│           └── api_routes.py
```

---

## API Surface

| Area | Endpoints |
| --- | --- |
| Auth | `/api/auth/login`, `/api/auth/logout`, `/api/auth/change-password`, `/api/auth/session` |
| Settings | `/settings/config`, `/settings/rsync/destination` |
| Wi-Fi | `/wifi/wifi-live`, `/wifi/connect`, `/wifi/disconnect`, `/wifi/ap-qr`, `/settings/wifi/ap-ssid`, `/settings/wifi/ap-password` |
| Tailscale | `/tailscale/status`, `/tailscale/selection`, `/tailscale/set-exit-node`, `/tailscale/disable-exit-node`, `/tailscale/up`, `/tailscale/down` |

Full interactive docs: `http://<pi-ip>:8080/docs`

---

## Troubleshooting

**hostapd socket not found** — hostapd is not running or `ctrl_interface` is not set in the config. Check `systemctl status hostapd` and verify `/var/run/hostapd/wlan1` exists.

**Devices connect but have no internet** — IP forwarding or NAT rules are missing. Re-run step 6 of system setup and verify with `sudo iptables -t nat -L`.

**wlan1 address not assigned** — Check `dhcpcd.conf` and restart dhcpcd: `sudo systemctl restart dhcpcd`. Verify with `ip addr show wlan1`.

**App cannot write hostapd config** — Verify the `travelrouter` user has `sudo /usr/bin/cp` in `/etc/sudoers.d/travelrouter`.

---

## Security Note

This project is designed for a trusted personal network. Review route-level authentication and sudoers permissions before exposing it beyond your local network.

---

## License

Released under [CC0 1.0 Universal](LICENSE).
