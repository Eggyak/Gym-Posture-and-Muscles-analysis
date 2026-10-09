from collections import deque
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs, urlparse
import json
import math
import os
import random
import threading
import time

import serial


DEFAULT_PORT = "COM5"
DEFAULT_BAUD = 115200


class EmgBridge:
    def __init__(self):
        self.lock = threading.Lock()
        self.serial_conn = None
        self.reader_thread = None
        self.fake_thread = None
        self.stop_event = threading.Event()
        self.connected = False
        self.source = "fake"
        self.scenario = "resting"
        self.port = DEFAULT_PORT
        self.baud_rate = DEFAULT_BAUD
        self.last_line = ""
        self.last_error = ""
        self.sensor_a = None
        self.sensor_b = None
        self.mvc_a = 0.0
        self.mvc_b = 0.0
        self.seq = 0
        self.samples = deque(maxlen=6000)
        self.phase = 0.0
        self.fake_index = 0

    def _append_sample(self, sensor_a, sensor_b, raw_line):
        with self.lock:
            self.sensor_a = sensor_a
            self.sensor_b = sensor_b
            self.mvc_a = max(self.mvc_a, abs(sensor_a))
            self.mvc_b = max(self.mvc_b, abs(sensor_b))
            self.last_line = raw_line
            self.last_error = ""
            self.seq += 1
            self.samples.append({"seq": self.seq, "a": sensor_a, "b": sensor_b})

    def parse_line(self, line):
        cleaned = line.replace("Received:", "").strip()
        separators = [",", ";", "|", " "]
        parts = [cleaned]
        for separator in separators:
            if separator in cleaned:
                parts = [item for item in cleaned.split(separator) if item]
                break

        values = []
        for part in parts:
            try:
                values.append(float(part))
            except ValueError:
                continue

        if len(values) >= 4:
          return values[0], values[2]
        if len(values) >= 2:
          return values[0], values[1]
        if len(values) == 1:
          return values[0], 0.0
        return None, None

    def _serial_loop(self):
        while not self.stop_event.is_set():
            try:
                raw = self.serial_conn.readline()
                if not raw:
                    continue
                line = raw.decode("utf-8", errors="ignore").strip()
                if not line:
                    continue
                sensor_a, sensor_b = self.parse_line(line)
                if sensor_a is None and sensor_b is None:
                    continue
                self._append_sample(sensor_a or 0.0, sensor_b or 0.0, line)
            except serial.SerialException as exc:
                with self.lock:
                    self.last_error = str(exc)
                    self.connected = False
                break
            except Exception as exc:
                with self.lock:
                    self.last_error = str(exc)

        self._close_serial()

    def _fake_pair(self):
        t = self.fake_index
        self.phase += 0.24
        self.fake_index += 1

        if self.scenario == "resting":
            a = random.uniform(-6, 6)
            b = random.uniform(-5, 5)
        elif self.scenario == "mild":
            a = 28 * math.sin(self.phase * 1.7) + random.uniform(-4, 4)
            b = 24 * math.sin(self.phase * 1.7 + 0.4) + random.uniform(-4, 4)
        elif self.scenario == "maximal":
            a = 165 * math.sin(self.phase * 2.2) + random.uniform(-12, 12)
            b = 145 * math.sin(self.phase * 2.2 + 0.3) + random.uniform(-10, 10)
        elif self.scenario == "fatigue":
            envelope = max(35, 190 - t * 0.14)
            drift = max(8, 42 - t * 0.02)
            a = envelope * math.sin(self.phase * 2.1) + random.uniform(-drift, drift)
            b = (envelope - 18) * math.sin(self.phase * 2.1 + 0.35) + random.uniform(-drift, drift)
        else:
            a = 180 * math.sin(self.phase * 2.1) + random.uniform(-10, 10)
            b = 58 * math.sin(self.phase * 2.1 + 0.3) + random.uniform(-7, 7)

        return round(a, 2), round(b, 2)

    def _fake_loop(self):
        while not self.stop_event.is_set():
            sensor_a, sensor_b = self._fake_pair()
            self._append_sample(sensor_a, sensor_b, f"{sensor_a},{sensor_b}")
            time.sleep(0.01)

    def _close_serial(self):
        with self.lock:
            conn = self.serial_conn
            self.serial_conn = None
            if self.source == "serial":
                self.connected = False
        if conn and conn.is_open:
            conn.close()

    def disconnect(self):
        self.stop_event.set()
        self._close_serial()
        with self.lock:
            self.connected = False

    def _reset_state(self):
        with self.lock:
            self.last_line = ""
            self.last_error = ""
            self.sensor_a = None
            self.sensor_b = None
            self.mvc_a = 0.0
            self.mvc_b = 0.0
            self.seq = 0
            self.samples.clear()
            self.phase = 0.0
            self.fake_index = 0

    def connect_serial(self, port, baud_rate):
        self.disconnect()
        self.stop_event = threading.Event()
        self._reset_state()
        serial_conn = serial.Serial(port, baud_rate, timeout=0.02)
        time.sleep(0.5)
        with self.lock:
            self.serial_conn = serial_conn
            self.connected = True
            self.source = "serial"
            self.port = port
            self.baud_rate = baud_rate
            self.scenario = "real"
        self.reader_thread = threading.Thread(target=self._serial_loop, daemon=True)
        self.reader_thread.start()

    def start_fake(self, scenario):
        self.disconnect()
        self.stop_event = threading.Event()
        self._reset_state()
        with self.lock:
            self.connected = True
            self.source = "fake"
            self.scenario = scenario
        self.fake_thread = threading.Thread(target=self._fake_loop, daemon=True)
        self.fake_thread.start()

    def snapshot(self, since_seq=0):
        with self.lock:
            imbalance = None
            if self.sensor_a is not None and self.sensor_b is not None:
                imbalance = abs(self.sensor_a - self.sensor_b)
            return {
                "connected": self.connected,
                "source": self.source,
                "scenario": self.scenario,
                "port": self.port,
                "baud_rate": self.baud_rate,
                "last_line": self.last_line,
                "last_error": self.last_error,
                "sensor_a": self.sensor_a,
                "sensor_b": self.sensor_b,
                "mvc_a": self.mvc_a,
                "mvc_b": self.mvc_b,
                "imbalance": imbalance,
                "seq": self.seq,
                "samples": [sample for sample in self.samples if sample["seq"] > since_seq],
            }


BRIDGE = EmgBridge()


class Handler(SimpleHTTPRequestHandler):
    def send_json(self, payload, status=200):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/emg/status":
            params = parse_qs(parsed.query)
            since_seq = int(params.get("since", ["0"])[0])
            self.send_json(BRIDGE.snapshot(since_seq))
            return
        super().do_GET()

    def do_POST(self):
        parsed = urlparse(self.path)
        content_length = int(self.headers.get("Content-Length", "0"))
        raw_body = self.rfile.read(content_length) if content_length else b"{}"
        try:
            payload = json.loads(raw_body.decode("utf-8"))
        except json.JSONDecodeError:
            payload = {}

        if parsed.path == "/api/emg/fake/start":
            scenario = payload.get("scenario") or "resting"
            BRIDGE.start_fake(scenario)
            self.send_json({"ok": True, "message": f"Fake scenario started: {scenario}"})
            return

        if parsed.path == "/api/emg/connect":
            try:
                BRIDGE.connect_serial(payload.get("port") or DEFAULT_PORT, int(payload.get("baud_rate") or DEFAULT_BAUD))
                self.send_json({"ok": True, "message": f"Connected to {payload.get('port') or DEFAULT_PORT}."})
            except Exception as exc:
                self.send_json({"ok": False, "message": str(exc)}, status=500)
            return

        if parsed.path == "/api/emg/disconnect":
            BRIDGE.disconnect()
            self.send_json({"ok": True, "message": "Signal source stopped."})
            return

        self.send_json({"ok": False, "message": "Unknown endpoint."}, status=404)


def main():
  root = Path(__file__).resolve().parent
  os.chdir(root)
  server = ThreadingHTTPServer(("127.0.0.1", 8010), Handler)
  print("Serving EMG-only dashboard at http://127.0.0.1:8010")
  try:
      server.serve_forever()
  except KeyboardInterrupt:
      print("\nStopping server...")
  finally:
      BRIDGE.disconnect()
      server.server_close()


if __name__ == "__main__":
  main()
