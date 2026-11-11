"""Mac notifications (silently does nothing elsewhere)."""
from __future__ import annotations

import subprocess
import sys


def mac_notification(title: str, message: str) -> bool:
    if sys.platform != "darwin":
        return False
    safe = lambda t: t.replace("\\", "").replace('"', "'")  # noqa: E731
    try:
        subprocess.run(["osascript", "-e", f'display notification "{safe(message)}" with title "{safe(title)}"'],
                       timeout=10, check=False, capture_output=True)
        return True
    except Exception:
        return False
