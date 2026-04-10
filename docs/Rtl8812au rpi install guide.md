# RTL8812AU WiFi Driver — Raspberry Pi Install Guide

Driver repo: [morrownr/8812au-20210820](https://github.com/morrownr/8812au-20210820)
Tested on: Debian GNU/Linux 13 (trixie), kernel `6.12.75+rpt-rpi-v8`

---

## Before You Start

### Check if you even need this driver

As of kernel 6.14, the RTL8812AU chipset is supported by the built-in `rtw88` driver. Check first:

```bash
uname -r
```

If your kernel is **6.14 or newer**, plug in your adapter and check if it's already detected:

```bash
lsmod | grep rtw
ip link
```

If the adapter shows up, you're done — no compilation needed.

---

## Step 1 — Update the system

```bash
sudo apt update && sudo apt upgrade
sudo reboot
```

---

## Step 2 — Install build dependencies

### ⚠️ Troubleshooting: `raspberrypi-kernel-headers` not found

The official README suggests:

```bash
sudo apt install -y raspberrypi-kernel-headers build-essential bc dkms git
```

This will **fail** on Debian trixie (and similar non-Raspberry Pi OS setups) with:

```
E: Unable to locate package raspberrypi-kernel-headers
```

**Fix:** Find the correct headers package for your exact running kernel. First, check what's available:

```bash
apt-cache search linux-headers | grep rpt
```

Then match the output to your kernel version (`uname -r`). For kernel `6.12.75+rpt-rpi-v8`, the correct command is:

```bash
sudo apt install -y linux-headers-6.12.75+rpt-rpi-v8 build-essential bc dkms git
```

> **Tip:** Replace `6.12.75` with whatever version `uname -r` reports on your system. Always look for the `+rpt-rpi-v8` suffix for a 64-bit Pi running an RPi-flavoured kernel.

---

## Step 3 — Clone the repository

```bash
git clone https://github.com/morrownr/8812au-20210820.git
cd 8812au-20210820
```

---

## Step 4 — Compile and install

```bash
sudo ./install-driver.sh
```

The script will compile the driver, install it via DKMS, and prompt you to reboot. Allow the reboot.

> DKMS means the driver will **automatically recompile** whenever a new kernel is installed — you won't need to redo this manually.

---

## Step 5 — Verify the driver loaded

After rebooting:

```bash
lsmod | grep 8812au
```

You should see `8812au` listed. Also check that your adapter is visible:

```bash
ip link
```

---

## Finding the Compiled Driver File

The compiled kernel module is installed at:

```bash
find /lib/modules -name "8812au.ko*" 2>/dev/null
```

Typically: `/lib/modules/<kernel-version>/updates/dkms/8812au.ko.xz`

To copy it off the Pi to your Mac:

```bash
scp user@<pi-ip>:/lib/modules/$(uname -r)/updates/dkms/8812au.ko.xz ~/Desktop/
```

> **Important:** The `.ko` file is tied to the exact kernel version it was compiled for. It cannot be reused on a different kernel. The most reliable way to "save" the driver for reuse is to **keep the cloned git repo** — DKMS handles recompilation automatically on kernel updates.

---

## Upgrading the Driver

Run this every 2–3 months or before a major OS/kernel upgrade:

```bash
cd 8812au-20210820
git pull
sudo ./install-driver.sh
```

---

## Removing the Driver

```bash
cd 8812au-20210820
sudo ./remove-driver.sh
```

---

## General Troubleshooting

### gcc version mismatch

If compilation fails, check that your gcc major version matches the one used to build your kernel:

```bash
cat /proc/version   # shows kernel's gcc version
gcc --version       # shows your installed gcc version
```

If they differ (e.g. kernel used gcc-12, you have gcc-10), install the matching version:

```bash
sudo apt install gcc-12
```

### Should I cross-compile on my Mac with Docker?

No. Kernel modules must be compiled against the exact kernel headers of the running kernel. Cross-compiling on a Mac adds significant complexity (ARM toolchain, exact header matching, manual `.ko` copying) with no benefit. Always compile natively on the Pi.

### Driver not loading after install

If you skipped the reboot at the end of `install-driver.sh`, the driver may not be active. Always reboot:

```bash
sudo reboot
```

### Previously installed conflicting drivers

If you've installed another RTL8812AU driver before, check for conflicts:

```bash
sudo dkms status
```

Remove any conflicting entries before reinstalling.