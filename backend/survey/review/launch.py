"""Wait for backend readiness, then open the default browser (Windows too)."""

import json
import sys
import time
import urllib.error
import urllib.request
import webbrowser


def open_when_ready(port: int, timeout: float = 300):
    url = f"http://127.0.0.1:{port}"
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url + "/api/health", timeout=1) as response:
                health = json.load(response)
            if not health["ready"]:
                print("Review startup failed:", health["diagnostics"], file=sys.stderr)
                return 1
            webbrowser.open(url)
            return 0
        except (OSError, urllib.error.URLError):
            time.sleep(0.25)
    print(
        "Review backend did not become ready; inspect the console (including port collisions).",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(open_when_ready(int(sys.argv[1])))
