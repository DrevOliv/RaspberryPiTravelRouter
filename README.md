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
- Optionally route all AP traffic through a Tailscale exit node
- Mount USB drives and back them up to a remote server over rsync/SSH
- Change the admin password and configure app settings

The private AP is managed by **hostapd** (over its UNIX control socket), the upstream connection by **nmcli**, and backups by **rsync over SSH**. The backend is a FastAPI app served with Uvicorn. Tailscale is optional — if it isn't installed the UI just shows it as unavailable.

---

## Installation

### Quick install

On a fresh Raspberry Pi OS, plug in your USB Wi-Fi adapter (the AP interface) and run as root:

```bash
curl -fsSL https://raw.githubusercontent.com/DrevOliv/RaspberryPiRouter/main/deploy/install.sh | sudo bash
```

This is the only command you need: it sets up the **full networking stack** (NetworkManager, static IP, dnsmasq, hostapd, IP forwarding, NAT) **and** installs the app + service. Override the defaults — interfaces, Wi-Fi country, subnet — with env vars (see the top of [`deploy/install.sh`](deploy/install.sh)), e.g. `AP_IFACE=wlan2 COUNTRY=SE sudo -E bash install.sh`. Run it from a console or over ethernet if you can, since it restarts NetworkManager.

Tailscale is optional — [install it yourself](docs/manual-setup.md#1-install-packages) to use exit nodes.

Then open `http://<pi-ip>:8080/` and log in with the default password **`changeme`** (printed in the journal on first boot). **Change it immediately** from the Settings page. To pull updates as the `travelrouter` user later, add SSH access (manual step 2 below).

Prefer to set things up by hand or customize the networking beyond the script's variables? See [`docs/manual-setup.md`](docs/manual-setup.md).

### Manual install

The app runs as a dedicated `travelrouter` user, with code in `/opt/travelrouter` and mutable state (config + admin password hash) in `/var/lib/travelrouter` — kept out of the code tree so updates never touch it. These are the steps the quick-install script performs.

**1. Create the service user**

```bash
sudo useradd -m -s /bin/bash travelrouter
sudo usermod -aG netdev travelrouter   # reach the hostapd control socket
```

**2. Set up SSH access** (so you can log in to pull updates)

```bash
sudo mkdir -p /home/travelrouter/.ssh
sudo cp ~/.ssh/authorized_keys /home/travelrouter/.ssh/authorized_keys
sudo chown -R travelrouter:travelrouter /home/travelrouter/.ssh
sudo chmod 700 /home/travelrouter/.ssh
sudo chmod 600 /home/travelrouter/.ssh/authorized_keys
```

**3. Clone and install dependencies**

```bash
sudo mkdir -p /opt/travelrouter
sudo chown travelrouter:travelrouter /opt/travelrouter
sudo -u travelrouter git clone https://github.com/DrevOliv/RaspberryPiRouter.git /opt/travelrouter
sudo -u travelrouter python3 -m venv /opt/travelrouter/.venv
sudo -u travelrouter /opt/travelrouter/.venv/bin/pip install -r /opt/travelrouter/requirements.txt
```

**4. Create the environment file** (gitignored, so it survives `git pull`)

```bash
sudo -u travelrouter cp /opt/travelrouter/travelrouter.env.example /opt/travelrouter/travelrouter.env
```

**5. Install the privileged hostapd helper** (reads/writes `/etc/hostapd/hostapd.conf` without blanket root)

```bash
sudo install -m 755 /opt/travelrouter/deploy/travelrouter-hostapd /usr/local/sbin/travelrouter-hostapd
```

**6. Install sudoers rules** (passwordless `sudo` for `nmcli`, `tailscale`, `mount`/`umount`, the hostapd helper, and the service restart)

```bash
sudo install -m 440 /opt/travelrouter/deploy/sudoers.travelrouter /etc/sudoers.d/travelrouter
sudo visudo -f /etc/sudoers.d/travelrouter   # fix paths if `which nmcli`/`tailscale` differ from /usr/bin
sudo visudo -c                                # validate
```

**7. Install and enable the service** (auto-creates `/var/lib/travelrouter` and `/run/travelrouter`)

```bash
sudo ln -sf /opt/travelrouter/travelrouter.service /etc/systemd/system/travelrouter.service
sudo systemctl daemon-reload
sudo systemctl enable --now travelrouter
sudo systemctl status travelrouter
```

After installing, work through [`TESTING.md`](TESTING.md) to verify each feature on the Pi.

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

## Development

You can run the app on any machine for UI and API work — you don't need a Pi:

```bash
git clone https://github.com/DrevOliv/RaspberryPiRouter.git
cd RaspberryPiRouter
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python app.py            # serves on http://localhost:8080 (default password: changeme)
```

The app shells out to system tools (`nmcli`, `hostapd`, `tailscale`, `mount`, `rsync`). Off a Pi these degrade gracefully rather than crash — Tailscale shows *Unavailable*, Wi-Fi scans return errors, etc. — so the UI is fully browsable for front-end iteration, but full behavior needs the Pi.

- **Data file:** defaults to `./data/data.json` in dev; override with `TRAVELROUTER_DATA_FILE_PATH`.
- **Interactive API docs:** `http://localhost:8080/docs` (every endpoint, with schemas).
- **Auth:** all API routes except login/logout require a session cookie; the UI handles this, and `/api/health` is public.

### Configuration

Environment variables (set in `/opt/travelrouter/travelrouter.env` on the Pi, or your shell in dev; see `travelrouter.env.example`):

| Variable | Description | Default |
| --- | --- | --- |
| `TRAVELROUTER_AUTH_COOKIE_NAME` | Session cookie name | `tr_session` |
| `TRAVELROUTER_AUTH_SESSION_TTL_SECONDS` | Session lifetime in seconds | `86400` |
| `TRAVELROUTER_AUTH_SECURE_COOKIE` | Set the Secure flag on cookies (use behind HTTPS) | `false` |
| `TRAVELROUTER_DATA_FILE_PATH` | Path to the JSON data file | `/var/lib/travelrouter/data.json` (set by the systemd unit) |

---

## Project Structure

```
.
├── app.py                          # entrypoint (uvicorn)
├── requirements.txt
├── travelrouter.service            # systemd unit (symlinked into /etc/systemd/system)
├── travelrouter.env.example        # copy to travelrouter.env (gitignored)
├── deploy/
│   ├── install.sh                  # one-line bootstrap installer (clones + sets up)
│   ├── travelrouter-hostapd        # privileged helper → /usr/local/sbin
│   └── sudoers.travelrouter        # sudoers template → /etc/sudoers.d/travelrouter
├── docs/
│   └── manual-setup.md             # one-time OS & network configuration
├── TESTING.md                      # post-install manual test checklist
└── TravelRouter/
    ├── __init__.py                 # app factory, router wiring, router-level auth
    ├── static/                     # index / login / settings / drives html + style.css
    ├── helpers/                    # run_command, api_response
    ├── config_file/                # DataManager + data models
    └── components/                 # one package per feature, each with api_routes.py
        ├── auth/                   # session login + password hashing
        ├── settings/               # config, rsync destination, SSH key
        ├── system/                 # diagnostics + AP start/stop
        ├── tailscale/              # exit-node + up/down control (optional)
        ├── drive/                  # USB drive discovery + mount/unmount
        ├── rsync/                  # background rsync jobs + live SSE stream + remote ops
        └── wifi/                   # nmcli upstream + hostapd AP control
```

Each component owns its routes (`api_routes.py`), models (`data_models.py`), and system calls (`system_api.py`); `TravelRouter/__init__.py` mounts them and enforces auth. The full HTTP surface is browsable at `/docs`.

---

## License

Released under [CC0 1.0 Universal](LICENSE).
