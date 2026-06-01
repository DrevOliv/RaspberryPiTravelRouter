# Manual Pi Setup

The [quick-install script](../deploy/install.sh) performs **all** of this
automatically, driven by the variables at the top of the script
(`AP_IFACE`, `UPSTREAM_IFACE`, `AP_IP`, `COUNTRY`, …). This document is the
reference for what it does — and the route to take if you'd rather configure the
networking by hand, or customize it beyond those variables.

## Hardware

- Raspberry Pi (tested on Pi 4 / Pi Zero 2W)
- Two Wi-Fi interfaces:
  - `wlan0` — connects to the upstream internet (hotel/cafe Wi-Fi)
  - `wlan1` — broadcasts the private access point

A USB Wi-Fi adapter is needed for the second interface. See
[`Rtl8812au rpi install guide.md`](Rtl8812au%20rpi%20install%20guide.md) for
driver setup on RTL8812AU adapters.

---

## Network interfaces

The setup below assumes two interfaces with fixed roles:

| Interface | Role | Typically |
| --- | --- | --- |
| `wlan0` | **Upstream** — joins hotel/cafe Wi-Fi (managed by NetworkManager) | the Pi's built-in Wi-Fi |
| `wlan1` | **Access point** — broadcasts your private network (hostapd) | the USB Wi-Fi adapter |

Identify which physical adapter is which before you start:

```bash
nmcli device status                          # type + state per interface
ls -l /sys/class/net/wlan*/device/driver     # which driver backs each (e.g. brcmfmac vs 8812au)
```

These names are **not auto-detected** — if your adapters enumerate the other way
around, or you want different names, you must use the same names consistently in
**every** place they appear:

- `/etc/NetworkManager/conf.d/unmanaged.conf` — the AP interface (step 2)
- `wlan1-static-ip.service` — the AP interface (step 3)
- `/etc/dnsmasq.d/travelrouter.conf` — the AP interface (step 4)
- `/etc/hostapd/hostapd.conf` — `interface=` (step 5)
- the `iptables` NAT / forward rules — both interfaces (step 7)
- the app's settings — `upstream_interface` / `ap_interface` (see below)

**The app's two interface names** live in its data file
(`/var/lib/travelrouter/data.json` → `wifi.upstream_interface` / `wifi.ap_interface`),
defaulting to `wlan0` / `wlan1` to match this guide. The upstream name is used by
`nmcli` immediately; the AP name is read when the service starts, so after
changing it run `sudo systemctl restart travelrouter` and make sure it matches the
OS config above. (You can also set them via `POST /settings/wifi` — see `/docs`.)

> **USB adapter names can drift between boots.** If yours does, pin it with a
> `systemd.link` rule that matches the adapter's MAC, e.g.
> `/etc/systemd/network/10-ap.link`:
>
> ```ini
> [Match]
> MACAddress=aa:bb:cc:dd:ee:ff
>
> [Link]
> Name=wlan1
> ```

---

## 1. Install packages

```bash
sudo apt update
sudo apt install -y hostapd dnsmasq network-manager git python3-venv rsync openssh-client
```

(`git`, `python3-venv`, `rsync`, and `openssh-client` are needed by the app and
installer; the quick-install script also installs them, so you can skip them
here if you use that path.)

### Tailscale (optional)

Tailscale is **optional** — it is only used for VPN exit-node routing. If you
don't install it, the app simply shows Tailscale as *Unavailable* in the UI and
everything else works normally. To enable it, install and authenticate it
yourself:

```bash
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up
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

## 2. Enable NetworkManager and configure interfaces

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

## 3. Assign a static IP to the AP interface

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

## 4. Configure dnsmasq (DHCP for connected devices)

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

## 5. Write the initial hostapd config

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

## 6. Set upstream interface priority (eth0 over wlan0)

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

## 7. Enable IP forwarding and NAT

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

Once this is done, return to the [README](../README.md) to install the app.

---

## How it works

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

The app talks to hostapd over its UNIX control socket (`/var/run/hostapd/wlan1`)
to list clients, reload config, and manage the service. SSID/password changes are
written to `/etc/hostapd/hostapd.conf` (via the `travelrouter-hostapd` helper) and
applied with a `RELOAD` command over the socket.

---

## Security note

This project is designed for a trusted personal network. The app runs
unprivileged and escalates only through the specific commands granted in
`/etc/sudoers.d/travelrouter`; the hostapd config write is locked to the
`travelrouter-hostapd` helper rather than a blanket `cp`. The `nmcli`,
`tailscale`, and `mount`/`umount` grants are still broad by nature, so review the
sudoers rules and the route-level authentication before exposing the app beyond
your local network. It serves plain HTTP — put it behind a TLS reverse proxy (and
set `TRAVELROUTER_AUTH_SECURE_COOKIE=1`) if it's reachable from anywhere
untrusted.

---

## Troubleshooting

**hostapd socket not found** — hostapd is not running or `ctrl_interface` is not set in the config. Check `systemctl status hostapd` and verify `/var/run/hostapd/wlan1` exists.

**Devices connect but have no internet** — IP forwarding or NAT rules are missing. Re-run step 7 and verify with `sudo iptables -t nat -L`.

**wlan1 address not assigned** — Check the `wlan1-static-ip` service (step 3): `systemctl status wlan1-static-ip`. Verify with `ip addr show wlan1`.

**App cannot write hostapd config** — Verify the helper is installed at `/usr/local/sbin/travelrouter-hostapd` and the `travelrouter` user has the matching `travelrouter-hostapd read`/`write` rules in `/etc/sudoers.d/travelrouter` (`visudo -c` to validate).

**App cannot reach the hostapd socket** — the `travelrouter` user must be in the `netdev` group (`sudo usermod -aG netdev travelrouter`, then restart the service).
```

