# Testing Checklist

A manual test plan for after installing the app on the Raspberry Pi, ordered so
that foundations are verified first (easier debugging). Items marked 🔴 are
higher-risk (new features or privilege-dependent) — test those first.

> Main debugging window: `journalctl -u travelrouter -f`.
> For privilege issues (AP save, mount, tailscale), run the exact `sudo` command
> manually as the `travelrouter` user — a sudoers path mismatch (e.g. `tailscale`
> not at `/usr/bin/`) is the most common first-install failure.

## 1. Install & service bring-up 🔴

- [ ] Run the one-liner (`curl … | sudo bash`) on a fresh Pi; it creates the `travelrouter` user, installs `git/python3-venv/rsync/openssh-client`, clones to `/opt/travelrouter`, builds the venv, installs deps, drops the helper + sudoers, enables the service.
- [ ] `sudo systemctl status travelrouter` → **active (running)**.
- [ ] `journalctl -u travelrouter -b` → no tracebacks; shows `Default Password: changeme` on first boot.
- [ ] Paths exist: `/opt/travelrouter`, `/var/lib/travelrouter/data.json` (owned by `travelrouter`), `/opt/travelrouter/travelrouter.env`.
- [ ] `sudo visudo -c` valid; `/etc/sudoers.d/travelrouter` paths match `which nmcli` / `which tailscale`.
- [ ] Re-run the installer → updates, does **not** duplicate (idempotent).

## 2. Auth 🔴

- [ ] `http://<pi-ip>:8080/` serves the login page.
- [ ] `curl -i http://<pi-ip>:8080/wifi/wifi-live` (not logged in) → **401**.
- [ ] Log in with `changeme` → dashboard loads.
- [ ] Change the password (Settings) → forces re-login; old password rejected, new one works.
- [ ] `curl -i .../api/health` → **200 without auth** (only public endpoint besides login).

## 3. Access Point — hostapd helper path 🔴 (most likely to break)

- [ ] Settings → change **AP SSID**, save → success toast.
- [ ] `sudo cat /etc/hostapd/hostapd.conf` shows the new SSID; `/run/travelrouter/hostapd.conf` staging file exists.
- [ ] Change **AP password** → success; reconnect a phone to confirm the new password works.
- [ ] **Negative:** set a 3-char AP password → clean error ("Password must be 8–63 characters"), **not** a 500.
- [ ] If it fails: `sudo -u travelrouter sudo /usr/local/sbin/travelrouter-hostapd read` works.

## 4. Upstream Wi-Fi (nmcli)

- [ ] Dashboard shows nearby networks (scan) and connected devices.
- [ ] **Connect** to a network (with/without password) → success even if nmcli warns on stderr.
- [ ] **Disconnect** → success.
- [ ] Connect with a wrong password → sensible error, no crash.

## 5. Tailscale

- [ ] Settings → exit-node dropdown populates from `tailscale status`.
- [ ] Save an exit node, then set/disable it from the dashboard; `tailscale status` on the Pi reflects it.
- [ ] `tailscale up` / `down` toggles work and the UI status updates.

## 6. Drives 🔴 (`/drive/mounted_drives` is new)

- [ ] Plug in a USB drive → appears under **Available**.
- [ ] **Mount** it → shows under **Mounted** at `/mnt/drives/<label>` (`mount | grep /mnt/drives`).
- [ ] **Reload the page** → the mounted drive still appears.
- [ ] Browse folders into subdirectories; breadcrumb navigation works.
- [ ] **Unmount** → disappears and `/mnt/drives/<label>` is gone.

## 7. SSH key 🔴 (new)

- [ ] Settings → **Backup SSH Key**: with no key, the **Create SSH Key** button appears.
- [ ] Click it → public key + fingerprint show; **Copy** works.
- [ ] On the Pi: `~travelrouter/.ssh/` has `id_ed25519` (600) + `.pub`, dir 700.
- [ ] Reload the page → it **shows the existing key** (doesn't offer to recreate).
- [ ] If you created a key manually, the UI **displays that one**.

## 8. Backup destination + remote test/folder 🔴 (new)

- [ ] Put the Pi's public key (step 7) into the remote server's `~/.ssh/authorized_keys`.
- [ ] Settings → **Backup Destination**: enter `user@server` + path → **Verify & Save** succeeds.
- [ ] Drives page → **Test Connection** → success toast.
- [ ] **New Folder** → create `trip_test` → it appears on the server.
- [ ] **Negative:** Test/New Folder with no destination saved → "Set it in Settings first" (400). Folder name with a `/` → rejected.

## 9. rsync transfer 🔴 (async rewrite — the big one)

- [ ] Select a folder on a mounted drive → **Start Transfer** to the destination.
- [ ] Job card appears; **live progress bar + log lines stream** without lag.
- [ ] Files actually land on the server (`ls` / `du` to compare).
- [ ] **Stop** a running transfer → status *Stopped*; on the Pi `pgrep -af rsync` shows none lingering.
- [ ] Transfer to a **bad destination** → job ends *Failed* with the error in its log (no hang).
- [ ] Open the page in **two tabs** during a transfer → both show live progress.
- [ ] `sudo systemctl restart travelrouter` mid-transfer → service comes back cleanly (in-memory jobs are gone after restart — expected).

## 10. Updates & persistence 🔴

- [ ] `cd /opt/travelrouter && git pull && sudo systemctl restart travelrouter` → still runs; **config + password survive** (they live in `/var/lib/travelrouter`).
- [ ] **Reboot the Pi** → service auto-starts, AP comes up, dashboard reachable, saved settings intact.

## 11. Negative / edge sweep

- [ ] Wrong login password → 401, no odd behaviour.
- [ ] Use the app from a phone on the AP → responsive layout + bottom nav work.
- [ ] Leave the dashboard open a few minutes → SSE heartbeats keep it alive (no console errors); health chip stays green.

## Known limitation (not a bug)

The transfer modal sends `retries`/`retry_delay`, but the backend ignores them —
there is **no auto-retry**, and the "attempt X/N" UI never appears. Transfers
themselves work fine.
