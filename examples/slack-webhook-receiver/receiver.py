"""Costura webhook receiver: verifies X-Costura-Signature and prints each signal (README.md)."""

import hashlib
import hmac
import json
import os
import sys
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

SECRET = os.environ["COSTURA_WEBHOOK_SECRET"].encode()
MAX_AGE_SECONDS = 300


def verify(headers, body: bytes) -> bool:
    timestamp = headers.get("X-Costura-Timestamp", "")
    if not timestamp.isdigit() or abs(time.time() - int(timestamp)) > MAX_AGE_SECONDS:
        return False
    digest = hmac.new(SECRET, f"{timestamp}.".encode() + body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(headers.get("X-Costura-Signature", ""), f"v1={digest}")


class Receiver(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
        if not verify(self.headers, body):
            self.send_response(401)
            self.end_headers()
            return
        delivery = self.headers.get("X-Costura-Delivery", "?")
        print(f"delivery {delivery}: {json.loads(body).get('text', '')}", flush=True)
        self.send_response(200)
        self.end_headers()


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8089
    print(f"listening on 0.0.0.0:{port}", flush=True)
    HTTPServer(("0.0.0.0", port), Receiver).serve_forever()
