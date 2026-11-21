"""healthcheck.py - Docker HEALTHCHECK: healthy while the worker loop has written its health file recently.

The worker rewrites HEALTH_FILE at least every RECEIVE_WAIT_S (idle long-poll) or POLL_S (while rendering),
so a stale file means the loop is wedged (not merely busy rendering).
"""
import json
import os
import sys
import time

MAX_AGE_S = int(os.environ.get("HEALTH_MAX_AGE_S", "180"))


def main(path=None):
    path = path or os.environ.get("HEALTH_FILE", "/tmp/farm-worker.health")
    try:
        with open(path) as fh:
            h = json.load(fh)
    except (OSError, ValueError) as e:
        print(f"unhealthy: {e}")
        return 1
    age = time.time() - float(h.get("t", 0))
    if age > MAX_AGE_S:
        print(f"unhealthy: health file {age:.0f}s old (state={h.get('state')})")
        return 1
    print(f"ok: {h.get('state')} {age:.0f}s ago")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else None))
