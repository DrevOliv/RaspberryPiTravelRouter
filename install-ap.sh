#!/bin/bash
set -e

SSID="RouterPi"
PASSWORD="Password123"
AP_IFACE="wlan0"
CON_NAME="MyHotspot"
STATIC_IP="192.168.50.1/24"
DISPATCHER_SCRIPT="/etc/NetworkManager/dispatcher.d/10-route-metric"

echo "=== Setting up Access Point ==="
echo "SSID:      $SSID"
echo "Interface: $AP_IFACE"
echo "IP:        $STATIC_IP"
echo ""

# Step 1: Create the AP profile
echo "[1/9] Creating AP connection profile..."
sudo nmcli con add type wifi ifname "$AP_IFACE" mode ap con-name "$CON_NAME" ssid "$SSID"

# Step 2: Set band to 2.4GHz (bg)
echo "[2/9] Setting band to bg (2.4GHz)..."
sudo nmcli con modify "$CON_NAME" 802-11-wireless.band bg

# Step 3: Set WPA2-AES security
echo "[3/9] Configuring WPA2-AES security..."
sudo nmcli con modify "$CON_NAME" \
    802-11-wireless-security.proto rsn \
    802-11-wireless-security.pairwise ccmp \
    802-11-wireless-security.group ccmp

# Step 4: Set password
echo "[4/9] Setting Wi-Fi password..."
sudo nmcli con modify "$CON_NAME" 802-11-wireless-security.psk "$PASSWORD"

# Step 5: Enable NAT + DHCP via shared mode
echo "[5/9] Setting ipv4.method shared (enables NAT + dnsmasq)..."
sudo nmcli con modify "$CON_NAME" ipv4.method shared

# Step 6: Set static IP for the AP side
echo "[6/9] Setting static IP $STATIC_IP..."
sudo nmcli con modify "$CON_NAME" ipv4.addresses "$STATIC_IP"

# Step 7: Enable autoconnect
echo "[7/9] Enabling autoconnect..."
sudo nmcli con modify "$CON_NAME" connection.autoconnect yes

# Step 8: Disable powersave for stability
echo "[8/9] Disabling powersave..."
sudo nmcli con modify "$CON_NAME" 802-11-wireless.powersave 2

# Step 9: Prevent AP from being used as default route
echo "[9/9] Setting ipv4.never-default yes..."
sudo nmcli con modify "$CON_NAME" ipv4.never-default yes

# Create dispatcher script for route metrics
echo ""
echo "=== Creating route metric dispatcher script ==="
sudo tee "$DISPATCHER_SCRIPT" > /dev/null << 'EOF'
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

sudo chmod +x "$DISPATCHER_SCRIPT"
echo "Dispatcher script created at $DISPATCHER_SCRIPT"

# Bring the AP up
echo ""
echo "=== Bringing up the Access Point ==="
sudo nmcli con up "$CON_NAME"

echo ""
echo "Done! AP '$SSID' is up on $AP_IFACE ($STATIC_IP)"
echo "Connected devices: cat /var/lib/NetworkManager/dnsmasq-$AP_IFACE.leases"
