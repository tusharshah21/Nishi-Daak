#!/usr/bin/env python3
"""Nishi Daak presence service. Runs as root on the UNO Q's Debian host.

Every SCAN_SECONDS: arp-scan the home Wi-Fi for MACs, and BLE-scan for a device count.
Serves the latest result as JSON at GET /latest on 0.0.0.0:5000.
BLE addresses are never stored, only the count and the strongest RSSI.
"""
import asyncio
import json
import os
import re
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

IFACE = os.environ.get("NISHI_IFACE", "wlan0")  # arp-scan would otherwise pick the first interface, maybe a docker bridge
SCAN_SECONDS = int(os.environ.get("NISHI_SCAN_SECONDS", "15"))
BLE_SECONDS = float(os.environ.get("NISHI_BLE_SECONDS", "5"))
PORT = int(os.environ.get("NISHI_PORT", "5000"))
MAC_RE = re.compile(r"\b([0-9a-f]{2}(?::[0-9a-f]{2}){5})\b", re.I)

latest = {"timestamp": None, "wifi_macs": [], "ble_count": 0, "ble_strongest": None}


def scan_wifi():
    # Locked phones in Wi-Fi power save answer ARP after up to ~2 s; the defaults (500 ms, 2 retries) miss them.
    # Measured on a locked phone: default 4/6 scans, these settings 6/6, about 13 s per scan instead of 2 s.
    out = subprocess.run(["arp-scan", "--localnet", "-q", "-I", IFACE, "--retry=4", "--timeout=1500"],
                         capture_output=True, text=True, timeout=60).stdout
    return sorted({m.lower() for m in MAC_RE.findall(out)})


def scan_ble():
    from bleak import BleakScanner

    found = asyncio.run(BleakScanner.discover(timeout=BLE_SECONDS, return_adv=True))
    rssis = [adv.rssi for _, adv in found.values()]  # addresses are dropped right here
    return len(rssis), max(rssis, default=None)


def scanner():
    global latest
    while True:
        result = dict(latest)
        try:
            result["wifi_macs"] = scan_wifi()
        except Exception as e:
            print("wifi scan failed:", e, flush=True)
        try:
            result["ble_count"], result["ble_strongest"] = scan_ble()
        except Exception as e:
            print("ble scan failed:", e, flush=True)
        result["timestamp"] = time.time()
        latest = result  # swap the whole dict so readers never see a half-written scan
        time.sleep(SCAN_SECONDS)


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path != "/latest":
            self.send_error(404)
            return
        body = json.dumps(latest).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass  # keep journald quiet: one line per poll is noise


if __name__ == "__main__":
    threading.Thread(target=scanner, daemon=True).start()
    print(f"nishi presence on :{PORT}, iface {IFACE}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
