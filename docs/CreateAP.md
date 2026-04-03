Setting up a Raspberry Pi as an Access Point (AP) while simultaneously using another interface (like a secondary USB Wi-Fi dongle or Ethernet) to connect to the internet is a classic "Wireless Client + AP" or "Bridge" setup. 

Using **NetworkManager** (`nmcli`) is actually the smartest way to do this in 2026, as it handles the handoffs and interface management much more gracefully than the old `hostapd` manual configurations.

### Prerequisites
* **Hardware:** Ensure your Pi's built-in Wi-Fi supports **AP Mode** (the Pi 3, 4, 5, and Zero W all do).
* **Interfaces:** I'll assume `wlan0` is your AP and `eth0` (or `wlan1`) is your internet source.

---

### Step 1: Create the AP Profile
We will create a new connection profile specifically for the hotspot. Replace `MyPiAP` and `Password123` with your preferred credentials.

```bash
sudo nmcli con add type wifi ifname wlan0 mode ap con-name MyHotspot ssid RouterPi
sudo nmcli con modify MyHotspot 802-11-wireless.band bg
sudo nmcli con modify MyHotspot 802-11-wireless-security.proto rsn 802-11-wireless-security.pairwise ccmp 802-11-wireless-security.group ccmp
sudo nmcli con modify MyHotspot 802-11-wireless-security.psk Password123
sudo nmcli con modify MyHotspot ipv4.method shared
```

**Why `ipv4.method shared`?** This is the "magic" setting in NetworkManager. It automatically starts a local DHCP server (dnsmasq) and sets up the NAT (Network Address Translation) rules so that devices connecting to your Pi can reach the internet via your other active interface.

---

### Step 2: Fine-Tuning for Stability
By default, NetworkManager might try to use `wlan0` to scan for other networks. We want it focused on being an AP.

1.  **Set a static IP for the Pi on the AP side (Optional but Recommended):**
    ```bash
    sudo nmcli con modify MyHotspot ipv4.addresses 192.168.50.1/24
    ```
2.  **Ensure it starts automatically:**
    ```bash
    sudo nmcli con modify MyHotspot connection.autoconnect yes
    ```
3.  **Set WPA2-AES:**
    ```bash
    sudo nmcli con modify MyHotspot 802-11-wireless-security.proto rsn
    sudo nmcli con modify MyHotspot 802-11-wireless-security.group ccmp
    sudo nmcli con modify MyHotspot 802-11-wireless-security.pairwise ccmp
    sudo nmcli con modify MyHotspot 802-11-wireless.powersave 2
    ```

4.  **(NOT) May need to set localozation:**
    ```bash
    sudo iw reg set SE
    ```
5.  **To check the logs:**
    ```bash
    journalctl -u NetworkManager -f
    ```

6.  **To check where the internet traffic is going:**
    ```bash
    ip route
    ```
7.  **Set route settings so that there are no routing bugs:**

    `wlan0` → upstream Wi-Fi (hotel, etc.)
    
    `eth0` → optional upstream (wired)
    
    `wlan1` → AP for your devices    

    Create a default rule using NetworkManager dispatcher:

    ### Create script:

    ```bash
    sudo nano /etc/NetworkManager/dispatcher.d/10-route-metric
    ```

    ### Paste:

    ```bash
    #!/bin/bash
    
    if [ "$2" = "up" ]; then
        if [ "$DEVICE_IFACE" = "wlan0" ]; then
            nmcli connection modify "$CONNECTION_UUID" ipv4.route-metric 100
        fi
    
        if [ "$DEVICE_IFACE" = "eth0" ]; then
            nmcli connection modify "$CONNECTION_UUID" ipv4.route-metric 50
        fi
    fi
    ```

    ### Make executable:

    ```bash
    sudo chmod +x /etc/NetworkManager/dispatcher.d/10-route-metric
    
    ```

    ```bash
    # AP should NEVER route
    nmcli connection modify MyHotspot ipv4.never-default yes
    ```

---

### Step 3: Bring the AP Online
Now, tell NetworkManager to fire up the hotspot:

```bash
sudo nmcli con up MyHotspot
```



---

### Usefull commands

**Bring down the AP**
```bash
sudo nmcli con down MyHotspot
```
**Change ssid and password**
```bash
# Change the SSID (Network Name)
sudo nmcli con modify MyHotspot 802-11-wireless.ssid "NewNetworkName"

# Change the Password
sudo nmcli con modify MyHotspot 802-11-wireless-security.psk "NewPassword123"

sudo nmcli con down MyHotspot
sudo nmcli con up MyHotspot
```



# Redirecting data and view metrics on AP

To turn your Raspberry Pi into a "VPN Gateway" for any device that connects to its Wi-Fi, we'll need to use some diagnostic tools and a bit of Tailscale routing magic.

### 1. Seeing Connected Devices
Since NetworkManager uses `dnsmasq` under the hood for its "shared" connection mode, you can see everyone who has been assigned an IP address by checking the DHCP leases file.

**The quick way:**
```bash
cat /var/lib/nm-dnsmasq-wlan0.leases
```
*This shows the MAC address, IP address, and Device Name of every connected client.*

**The "Live" way:**
If you want to see them as they connect and disconnect in real-time:
```bash
nmcli device monitor wlan0
```

---

### 2. Monitoring Data Usage
NetworkManager doesn't keep a long-term "odometer" for data by default. To see how much data is passing through your AP **right now**, use `nload`.

1.  **Install it:**
    ```bash
    sudo apt update && sudo apt install nload -y
    ```
2.  **Run it specifically for your AP interface:**
    ```bash
    nload wlan0
    ```
    *This will show you live graphs for incoming (devices uploading) and outgoing (devices downloading) traffic.*

---

### 3. Redirecting Traffic via Tailscale Exit Node
This is the most advanced part. You want your Pi's Wi-Fi clients to "tunnel" through a Tailscale exit node (like a server in another country or your home PC).

**Step A: Enable IP Forwarding**
Your Pi needs permission to pass traffic from one "pipe" (Wi-Fi) to another (Tailscale).
```bash
echo "net.ipv4.ip_forward=1" | sudo tee -a /etc/sysctl.conf
sudo sysctl -p
```

**Step B: Connect to the Exit Node**
On your Raspberry Pi, tell Tailscale to use a specific exit node. You can find the name/IP of your nodes in your Tailscale dashboard.
```bash
# Replace 100.x.y.z with your actual exit node's Tailscale IP
sudo tailscale up --exit-node=100.x.y.z --exit-node-allow-lan-access
```

**Step C: The "Magic" Routing (Post-Up)**
By default, NetworkManager's `ipv4.method shared` sets up NAT to your "main" internet (e.g., `eth0`). To force it through Tailscale (`tailscale0`), we need to tell the firewall to masquerade traffic leaving through the Tailscale interface.

Run these commands to update your firewall rules:
```bash
sudo iptables -t nat -A POSTROUTING -o tailscale0 -j MASQUERADE
sudo iptables -A FORWARD -i wlan0 -o tailscale0 -j ACCEPT
sudo iptables -A FORWARD -i tailscale0 -o wlan0 -m state --state RELATED,ESTABLISHED -j ACCEPT
```



### How to make the Firewall rules permanent?
If you reboot, the `iptables` rules will disappear. The easiest way to keep them is to install `iptables-persistent`:
```bash
sudo apt install iptables-persistent
# Select 'Yes' when it asks to save current IPv4 rules
```

**Would you like me to show you how to automate this so that if the Tailscale connection drops, the Pi automatically switches back to the regular internet so your AP doesn't "die"?**






# Troubleshooting & Tips

* **Interface Names:** Run `nmcli device` to confirm your Wi-Fi is actually named `wlan0`.
* **Regulatory Domain:** If the AP fails to start, it might be due to Wi-Fi country codes. Ensure yours is set:
    ```bash
    sudo raspi-config  # Localisation Options -> WLAN Country
    ```
* **Dual Wi-Fi:** If you are trying to use the **same** physical Wi-Fi chip to both connect to a router and host an AP, be aware that many chips struggle with "Station + AP" mode simultaneously. It is much more stable to use the built-in Wi-Fi for the AP and a USB dongle (or Ethernet) for the internet source.

---

**Would you like me to show you how to configure the routing rules if you want to block certain devices on your new AP from accessing the main network?**