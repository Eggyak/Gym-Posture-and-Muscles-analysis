from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs, urlparse
import json
import os
import threading
import time
from collections import deque

import serial

from posture_bridge import PostureBridge


DEFAULT_PORT = "COM4"
DEFAULT_BAUD = 115200


class EmgBridge:
    def __init__(self):
        self.lock = threading.Lock()
        self.serial_conn = None
        self.reader_thread = None
        self.stop_event = threading.Event()
        self.connected = False
        self.port = DEFAULT_PORT
        self.baud_rate = DEFAULT_BAUD
        self.last_line = ""
        self.last_error = ""
        self.sensor_a = None
        self.sensor_b = None
        self.mvc_a = 0.0
        self.mvc_b = 0.0
        self.sample_seq = 0
        self.samples = deque(maxlen=4000)

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

        # Expected ESP32 format:
        # raw1,envelope1,raw2,envelope2
        # We intentionally plot and analyze only raw1 and raw2.
        if len(values) >= 4:
            return values[0], values[2]
        if len(values) >= 2:
            return values[0], values[1]
        if len(values) == 1:
            return values[0], None
        return None, None

    def read_loop(self):
        while not self.stop_event.is_set():
            try:
                raw = self.serial_conn.readline()
                if not raw:
                    continue
                line = raw.decode("utf-8", errors="ignore").strip()
                if not line:
                    continue
                sensor_a, sensor_b = self.parse_line(line)
                with self.lock:
                    self.last_line = line
                    self.last_error = ""
                    if sensor_a is not None:
                        self.sensor_a = sensor_a
                        self.mvc_a = max(self.mvc_a, abs(sensor_a))
                    if sensor_b is not None:
                        self.sensor_b = sensor_b
                        self.mvc_b = max(self.mvc_b, abs(sensor_b))
                    if sensor_a is not None or sensor_b is not None:
                        self.sample_seq += 1
                        self.samples.append({
                            "seq": self.sample_seq,
                            "a": sensor_a,
                            "b": sensor_b,
                        })
            except serial.SerialException as exc:
                with self.lock:
                    self.last_error = str(exc)
                    self.connected = False
                break
            except Exception as exc:
                with self.lock:
                    self.last_error = str(exc)
            time.sleep(0.02)

        self.close_serial()

    def close_serial(self):
        with self.lock:
            conn = self.serial_conn
            self.serial_conn = None
            self.connected = False
        if conn and conn.is_open:
            conn.close()

    def connect(self, port, baud_rate):
        self.disconnect()
        self.stop_event.clear()
        serial_conn = serial.Serial(port, baud_rate, timeout=1)
        time.sleep(2)
        with self.lock:
            self.serial_conn = serial_conn
            self.connected = True
            self.port = port
            self.baud_rate = baud_rate
            self.last_error = ""
            self.last_line = ""
            self.sensor_a = None
            self.sensor_b = None
            self.mvc_a = 0.0
            self.mvc_b = 0.0
            self.sample_seq = 0
            self.samples.clear()
        self.reader_thread = threading.Thread(target=self.read_loop, daemon=True)
        self.reader_thread.start()

    def disconnect(self):
        self.stop_event.set()
        self.close_serial()

    def snapshot(self, since_seq=0):
        with self.lock:
            imbalance = None
            if self.sensor_a is not None and self.sensor_b is not None:
                imbalance = abs(self.sensor_a - self.sensor_b)
            new_samples = [sample for sample in self.samples if sample["seq"] > since_seq]
            return {
                "connected": self.connected,
                "port": self.port,
                "baud_rate": self.baud_rate,
                "last_line": self.last_line,
                "last_error": self.last_error,
                "sensor_a": self.sensor_a,
                "sensor_b": self.sensor_b,
                "mvc_a": self.mvc_a,
                "mvc_b": self.mvc_b,
                "imbalance": imbalance,
                "seq": self.sample_seq,
                "samples": new_samples,
            }


BRIDGE = EmgBridge()
POSTURE = PostureBridge()


class GymHandler(SimpleHTTPRequestHandler):
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
            self.send_json(BRIDGE.snapshot(since_seq=since_seq))
            return
        if parsed.path == "/api/posture/status":
            self.send_json(POSTURE.snapshot())
            return
        if parsed.path == "/api/posture/feed":
            self.send_response(200)
            self.send_header("Age", "0")
            self.send_header("Cache-Control", "no-cache, private")
            self.send_header("Pragma", "no-cache")
            self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
            self.end_headers()
            try:
                while True:
                    frame = POSTURE.latest_frame()
                    if frame is None:
                        time.sleep(0.1)
                        continue
                    self.wfile.write(b"--frame\r\n")
                    self.send_header("Content-Type", "image/jpeg")
                    self.send_header("Content-Length", str(len(frame)))
                    self.end_headers()
                    self.wfile.write(frame)
                    self.wfile.write(b"\r\n")
                    time.sleep(0.05)
            except (BrokenPipeError, ConnectionResetError):
                return
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

        if parsed.path == "/api/emg/connect":
            port = payload.get("port") or DEFAULT_PORT
            baud_rate = int(payload.get("baud_rate") or DEFAULT_BAUD)
            try:
                BRIDGE.connect(port, baud_rate)
                self.send_json({"ok": True, "message": f"Connected to {port} at {baud_rate} baud."})
            except Exception as exc:
                self.send_json({"ok": False, "message": str(exc)}, status=500)
            return

        if parsed.path == "/api/emg/disconnect":
            BRIDGE.disconnect()
            self.send_json({"ok": True, "message": "Disconnected from EMG serial bridge."})
            return

        if parsed.path == "/api/posture/start":
            exercise = payload.get("exercise") or "squats"
            camera_source = payload.get("camera_source") or "webcam"
            esp32_url = payload.get("esp32_url") or ""
            try:
                POSTURE.start(exercise=exercise, camera_source=camera_source, esp32_url=esp32_url)
                self.send_json({"ok": True, "message": f"Started Python posture analysis for {exercise}."})
            except Exception as exc:
                self.send_json({"ok": False, "message": str(exc)}, status=500)
            return

        if parsed.path == "/api/posture/stop":
            POSTURE.stop()
            self.send_json({"ok": True, "message": "Stopped Python posture analysis."})
            return

        self.send_json({"ok": False, "message": "Unknown API endpoint."}, status=404)


def main():
    root = Path(__file__).resolve().parent
    os.chdir(root)
    server = ThreadingHTTPServer(("127.0.0.1", 8000), GymHandler)
    print("Serving Smart Gym Dashboard at http://127.0.0.1:8000")
    print("Open http://127.0.0.1:8000 in your browser")
    print(f"Default EMG serial port is {DEFAULT_PORT} at {DEFAULT_BAUD} baud")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping server...")
    finally:
        BRIDGE.disconnect()
        POSTURE.stop()
        server.server_close()


if __name__ == "__main__":
    main()
