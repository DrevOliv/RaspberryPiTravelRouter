# RaspberryPiRouter

![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-API-009688?logo=fastapi&logoColor=white)
![Uvicorn](https://img.shields.io/badge/Uvicorn-ASGI-499848?logo=uvicorn&logoColor=white)
![License](https://img.shields.io/badge/License-CC0--1.0-lightgrey)

## About

RaspberryPiRouter turns a Raspberry Pi into a portable travel router with a browser-based control panel. Plug it in at a hotel or cafe, connect it to the local Wi-Fi, and all your devices join your own private network — with a consistent IP range, optional Tailscale VPN routing, and no per-device configuration.

The web UI lets you:

- Scan for and connect to upstream Wi-Fi networks (or use ethernet)
- Manage your private access point — change the SSID, password, and view connected devices
- Select a Tailscale exit node to route all AP traffic through a VPN, or disable it
- Change the admin password and configure app settings

Internally, the private AP is managed by **hostapd** (communicating directly over its UNIX control socket), while the upstream connection is handled by **nmcli**. The backend is a FastAPI app served over Uvicorn.

---

## Installation

### Hardware

- Raspberry Pi (tested on Pi 4 / Pi Zero 2W)
- Two Wi-Fi interfaces:
  - `wlan0` — connects to the upstream internet (hotel/cafe Wi-Fi)
  - `wlan1` — broadcasts the private access point

A USB Wi-Fi adapter is needed for the second interface. See [`docs/Rtl8812au rpi install guide.md`](docs/Rtl8812au%20rpi%20install%20guide.md) for driver setup on RTL8812AU adapters.

---

### System Setup

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
ExecStart=/usr/sbin/iw dev wlan1 set power_save off
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

### 6. Set upstream interface priority (eth0 over wlan0)

When both ethernet and Wi-Fi are connected, eth0 should be preferred. Create a NetworkManager dispatcher script to set route metrics automatically whenever an interface comes up:

```bash
sudo tee /etc/NetworkManager/dispatcher.d/10-route-metric > /dev/null << 'EOF'
#!/bin/bash
if [ "$2" = "up" ]; then
    if [ "$DEVICE_IFACE" = "wlan0" ]; then
        nmcli connection modify "$CONNECTION_UUID" ipv4.route-metric 100
    fi
    if [ "$DEVICE_IFACE" = "eth0" ]; then
        nmcli connection modify "$CONNECTION_UUID" ipv4.route-metric 50
    fi
fi
EOF

sudo chmod +x /etc/NetworkManager/dispatcher.d/10-route-metric
```

Lower metric = higher priority, so eth0 (50) beats wlan0 (100).

---

### 7. Enable IP forwarding and NAT

```bash
# Persist IP forwarding across reboots
sudo tee /etc/sysctl.d/99-travelrouter.conf > /dev/null << 'EOF'
net.ipv4.ip_forward=1
EOF

sudo sysctl -p /etc/sysctl.d/99-travelrouter.conf

# wlan0 (upstream Wi-Fi)
sudo iptables -t nat -A POSTROUTING -o wlan0 -j MASQUERADE
sudo iptables -A FORWARD -i wlan1 -o wlan0 -j ACCEPT
sudo iptables -A FORWARD -i wlan0 -o wlan1 -m state --state RELATED,ESTABLISHED -j ACCEPT

# eth0 (ethernet — used when connected, preferred over wlan0)
sudo iptables -t nat -A POSTROUTING -o eth0 -j MASQUERADE
sudo iptables -A FORWARD -i wlan1 -o eth0 -j ACCEPT
sudo iptables -A FORWARD -i eth0 -o wlan1 -m state --state RELATED,ESTABLISHED -j ACCEPT

# tailscale0 (when Tailscale exit node is active)
# These rules are inactive when Tailscale is off — no impact on normal routing
sudo iptables -t nat -A POSTROUTING -o tailscale0 -j MASQUERADE
sudo iptables -A FORWARD -i wlan1 -o tailscale0 -j ACCEPT
sudo iptables -A FORWARD -i tailscale0 -o wlan1 -m state --state RELATED,ESTABLISHED -j ACCEPT

# Save rules so they survive a reboot
sudo apt install -y iptables-persistent
sudo netfilter-persistent save
```

---

### App Setup

The app runs as a dedicated `travelrouter` user, with code in `/opt/travelrouter` and mutable state (config + admin password hash) in `/var/lib/travelrouter` — kept out of the code tree so updates never touch it.

**Quick install:** on the Pi, run:

```bash
curl -fsSL https://raw.githubusercontent.com/DrevOliv/RaspberryPiRouter/main/deploy/install.sh | sudo bash
```

This clones the repo to `/opt/travelrouter` and does steps 1 and 3–7 below. Then add SSH access (step 2) if you want to pull updates as the `travelrouter` user. The manual steps below explain exactly what the script does.

#### 1. Create the service user

A regular user with a home directory and SSH access so you can log in to pull updates.

```bash
sudo useradd -m -s /bin/bash travelrouter

# Allow the service user to reach the hostapd control socket
sudo usermod -aG netdev travelrouter
```

#### 2. Set up SSH access

Copy your public key so you can log in as `travelrouter` later to pull updates:

```bash
sudo mkdir -p /home/travelrouter/.ssh
sudo cp ~/.ssh/authorized_keys /home/travelrouter/.ssh/authorized_keys
sudo chown -R travelrouter:travelrouter /home/travelrouter/.ssh
sudo chmod 700 /home/travelrouter/.ssh
sudo chmod 600 /home/travelrouter/.ssh/authorized_keys
```

#### 3. Clone the repository and install dependencies

```bash
sudo mkdir -p /opt/travelrouter
sudo chown travelrouter:travelrouter /opt/travelrouter
sudo -u travelrouter git clone git@github.com:DrevOliv/RaspberryPiRouter.git /opt/travelrouter
sudo -u travelrouter python3 -m venv /opt/travelrouter/.venv
sudo -u travelrouter /opt/travelrouter/.venv/bin/pip install -r /opt/travelrouter/requirements.txt
```

#### 4. Create the environment file

Lives next to the code and is gitignored, so it survives `git pull`:

```bash
sudo -u travelrouter cp /opt/travelrouter/travelrouter.env.example /opt/travelrouter/travelrouter.env
# edit /opt/travelrouter/travelrouter.env if you need to change any defaults
```

#### 5. Install the privileged hostapd helper

The app reads and writes `/etc/hostapd/hostapd.conf` through a small fixed-purpose helper rather than blanket root access:

```bash
sudo install -m 755 /opt/travelrouter/deploy/travelrouter-hostapd /usr/local/sbin/travelrouter-hostapd
```

#### 6. Install sudoers rules

The app needs passwordless `sudo` for `nmcli`, `tailscale`, `mount`/`umount`, `systemctl` (hostapd), the app restart, and the hostapd helper. A template is included:

```bash
sudo install -m 440 /opt/travelrouter/deploy/sudoers.travelrouter /etc/sudoers.d/travelrouter

# If `which nmcli` / `which tailscale` differ from /usr/bin, fix the paths:
sudo visudo -f /etc/sudoers.d/travelrouter

# Validate
sudo visudo -c
```

#### 7. Install and enable the service

The unit creates `/var/lib/travelrouter` (data) and `/run/travelrouter` (runtime staging) automatically.

```bash
sudo ln -sf /opt/travelrouter/travelrouter.service /etc/systemd/system/travelrouter.service
sudo systemctl daemon-reload
sudo systemctl enable --now travelrouter
```

Check it started correctly:

```bash
sudo systemctl status travelrouter
journalctl -u travelrouter -f
```

---

## Updating

SSH in as `travelrouter` and pull:

```bash
ssh travelrouter@<pi-ip>
cd /opt/travelrouter
git pull
sudo systemctl restart travelrouter
```

Your config, admin password, and `travelrouter.env` live outside the code tree (or are gitignored), so they're untouched. If `requirements.txt` changed, also run `.venv/bin/pip install -r requirements.txt`.

---

## First Login

Open `http://<pi-ip>:8080/` in your browser. The default password is:

```
changeme
```

Change it immediately from the Settings page.

---

## Configuration

App behaviour can be overridden with environment variables. Put them in `/opt/travelrouter/travelrouter.env` (loaded by the systemd unit); see `travelrouter.env.example`.

| Variable | Description | Default |
| --- | --- | --- |
| `TRAVELROUTER_AUTH_COOKIE_NAME` | Session cookie name | `tr_session` |
| `TRAVELROUTER_AUTH_SESSION_TTL_SECONDS` | Session lifetime in seconds | `86400` |
| `TRAVELROUTER_AUTH_SECURE_COOKIE` | Set secure flag on cookies (use behind HTTPS) | `false` |
| `TRAVELROUTER_DATA_FILE_PATH` | Path to the JSON data file | `/var/lib/travelrouter/data.json` (set by the unit) |

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
├── travelrouter.service            # systemd unit (symlinked into /etc/systemd/system)
├── travelrouter.env.example        # copy to travelrouter.env (gitignored)
├── deploy/
│   ├── install.sh                  # one-line bootstrap installer (clones + sets up)
│   ├── travelrouter-hostapd        # privileged helper → /usr/local/sbin
│   └── sudoers.travelrouter        # sudoers template → /etc/sudoers.d/travelrouter
├── TravelRouter/
│   ├── __init__.py                 # app factory, routers, router-level auth
│   ├── static/                     # index / login / settings / drives html + style.css
│   ├── helpers/                    # run_command, api_response
│   ├── config_file/                # DataManager + data models
│   └── components/
│       ├── auth/                   # session login + password hashing
│       ├── settings/               # /settings/config, rsync destination
│       ├── tailscale/              # exit-node + up/down control
│       ├── drive/                  # drive discovery + mount/unmount
│       ├── rsync/                  # background rsync jobs + SSE stream + remote ops
│       └── wifi/
│           ├── hostapd.py          # HostapdController — socket comms + service control
│           ├── hostapd_config.py   # Config file model
│           ├── system_api.py       # nmcli wrappers for upstream Wi-Fi
│           ├── functions.py        # Parsing helpers
│           └── api_routes.py
```

---

## API Surface

All endpoints except `/api/auth/login` and `/api/auth/logout` require an authenticated session.

| Area | Endpoints |
| --- | --- |
| Auth | `/api/auth/login`, `/api/auth/logout`, `/api/auth/change-password`, `/api/auth/session` |
| Settings | `/settings/config`, `/settings/rsync/destination` |
| Wi-Fi | `/wifi/wifi-live`, `/wifi/connect`, `/wifi/disconnect`, `/wifi/ap-qr`, `/settings/wifi`, `/settings/wifi/ap-ssid`, `/settings/wifi/ap-password` |
| Tailscale | `/tailscale/status`, `/tailscale/selection`, `/tailscale/set-exit-node`, `/tailscale/disable-exit-node`, `/tailscale/up`, `/tailscale/down` |
| Drive | `/drive/available_drives`, `/drive/mount`, `/drive/unmount`, `/drive/folders` |
| Rsync | `/rsync/jobs` (GET/POST), `/rsync/jobs/{id}` (DELETE), `/rsync/stream` (SSE), `/rsync/remote/test`, `/rsync/remote/folder` |

Full interactive docs: `http://<pi-ip>:8080/docs`

---

## Troubleshooting

**hostapd socket not found** — hostapd is not running or `ctrl_interface` is not set in the config. Check `systemctl status hostapd` and verify `/var/run/hostapd/wlan1` exists.

**Devices connect but have no internet** — IP forwarding or NAT rules are missing. Re-run step 6 of system setup and verify with `sudo iptables -t nat -L`.

**wlan1 address not assigned** — Check `dhcpcd.conf` and restart dhcpcd: `sudo systemctl restart dhcpcd`. Verify with `ip addr show wlan1`.

**App cannot write hostapd config** — Verify the helper is installed at `/usr/local/sbin/travelrouter-hostapd` and the `travelrouter` user has the matching `travelrouter-hostapd read`/`write` rules in `/etc/sudoers.d/travelrouter` (`visudo -c` to validate).

---

## Security Note

This project is designed for a trusted personal network. The app runs unprivileged and escalates only through the specific commands granted in `/etc/sudoers.d/travelrouter`; the hostapd config write is locked to the `travelrouter-hostapd` helper rather than a blanket `cp`. The `nmcli`, `tailscale`, and `mount`/`umount` grants are still broad by nature, so review the sudoers rules and the route-level authentication before exposing the app beyond your local network. It serves plain HTTP — put it behind a TLS reverse proxy (and set `TRAVELROUTER_AUTH_SECURE_COOKIE=1`) if it's reachable from anywhere untrusted.

---

## License

Released under [CC0 1.0 Universal](LICENSE).
