import io

from TravelRouter.components.wifi.data_models import WifiCurrent, WifiNetwork

# _____________________________ Funcs For wifi qr code ____________________________________

def wifi_qr_payload(ssid: str, password: str) -> str:
    escaped_ssid = ssid.replace("\\", "\\\\").replace(";", r"\;").replace(",", r"\,").replace(":", r"\:")
    escaped_password = password.replace("\\", "\\\\").replace(";", r"\;").replace(",", r"\,").replace(":", r"\:")
    return f"WIFI:T:WPA;S:{escaped_ssid};P:{escaped_password};;"



def wifi_qr_svg(ssid: str, password: str) -> str:
    try:
        import qrcode
        from qrcode.image.svg import SvgPathImage
    except ImportError:
        return (
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 280 280" role="img" aria-label="QR unavailable">'
            '<rect width="280" height="280" rx="24" fill="#fffaf2"/>'
            '<text x="140" y="132" text-anchor="middle" font-size="18" fill="#1f2a30">QR library missing</text>'
            '<text x="140" y="158" text-anchor="middle" font-size="14" fill="#6d776f">Install requirements.txt</text>'
            "</svg>"
        )

    qr = qrcode.QRCode(border=2, box_size=8)
    qr.add_data(wifi_qr_payload(ssid, password))
    qr.make(fit=True)
    image = qr.make_image(image_factory=SvgPathImage)
    buffer = io.BytesIO()
    image.save(buffer)
    return buffer.getvalue().decode("utf-8")

# ___________________________ Parse wifi scan result _____________________________________________

def split_nmcli_row(row: str) -> list[str]:
    parts = []
    current = []
    escape = False
    for char in row:
        if escape:
            current.append(char)
            escape = False
            continue
        if char == "\\":
            escape = True
            continue
        if char == ":":
            parts.append("".join(current))
            current = []
            continue
        current.append(char)
    parts.append("".join(current))
    return [part.replace("\\:", ":") for part in parts]

def parse_wifi_scan_rows(stdout: str) -> list[WifiNetwork]:
    networks = []
    seen = set()
    for row in stdout.splitlines():
        if not row.strip():
            continue
        parts = split_nmcli_row(row)
        ssid = (parts[0] if len(parts) > 0 else "").strip() or "Hidden network"
        signal_text = (parts[1] if len(parts) > 1 else "").strip()
        security = (parts[2] if len(parts) > 2 else "").strip() or "Open"
        key = (ssid, security)
        if key in seen:
            continue
        seen.add(key)
        try:
            signal = int(signal_text)
        except ValueError:
            signal = 0
        networks.append(
            WifiNetwork(
                ssid=ssid,
                security=security,
                is_open=security.lower() in {"", "open", "--"},
                signal=signal,
            )
        )

    networks.sort(key=lambda network: (-network.signal, network.ssid.lower()))
    return networks

# _______________________ Parse current wifi data ____________________________

def parse_current_network(stdout: str) -> WifiCurrent:
    lines = stdout.strip().split("\n")
    return WifiCurrent(
        state=lines[0] if len(lines) > 0 else "",
        ssid=lines[1] if len(lines) > 1 else "",
        operstate=lines[2] if len(lines) > 2 else "",
        eth_operstate=lines[3] if len(lines) > 3 else "",
    )

if __name__ == '__main__':
    print(wifi_qr_svg("test", "test"))
