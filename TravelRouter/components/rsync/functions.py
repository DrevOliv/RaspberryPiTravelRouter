import re

# Matches rsync --info=progress2 lines, e.g.:
#       1,234,567  45%   10.23MB/s    0:01:23
#       1,234,567  45%   10.23MB/s    0:01:23 (xfr#3, ir-chk=234/567)
_PROGRESS_RE = re.compile(
    r"^\s+([\d,]+)\s+(\d+)%\s+([\d.]+\s*\S+/s)\s+([\d:]+)"
)


def parse_progress(line: str) -> dict | None:
    """
    Parse one rsync --info=progress2 output line.

    Returns {"bytes": int, "percent": int, "speed": str, "eta": str}
    or None if the line is not a progress line.
    """
    m = _PROGRESS_RE.match(line)
    if not m:
        return None
    return {
        "bytes":   int(m.group(1).replace(",", "")),
        "percent": int(m.group(2)),
        "speed":   m.group(3).strip(),
        "eta":     m.group(4),
    }
