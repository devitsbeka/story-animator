"""A recording fake HTTP transport for provider tests: routes (method, path regex) -> handler. No network."""
import json
import re
import urllib.parse


class MockTransport:
    def __init__(self):
        self.routes = []
        self.calls = []

    def route(self, method, pattern, handler):
        """handler(call) -> (status, body_obj) or a constant (status, body_obj). Later routes win."""
        self.routes.insert(0, (method, re.compile(pattern), handler))
        return self

    def __call__(self, method, url, headers, body, timeout=30):
        u = urllib.parse.urlsplit(url)
        call = {"method": method, "url": url, "path": u.path, "query": dict(urllib.parse.parse_qsl(u.query)),
                "headers": dict(headers), "json": json.loads(body) if body else None}
        self.calls.append(call)
        for m, rx, h in self.routes:
            if m == method and rx.fullmatch(u.path):
                status, obj = h(call) if callable(h) else h
                return status, {}, (json.dumps(obj).encode() if obj is not None else b"")
        return 404, {}, json.dumps({"title": "Not Found", "status": 404, "detail": f"no route {method} {u.path}"}).encode()

    def find(self, method, path_rx):
        rx = re.compile(path_rx)
        return [c for c in self.calls if c["method"] == method and rx.fullmatch(c["path"])]
