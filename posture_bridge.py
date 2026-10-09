from pathlib import Path
import threading
import time
import urllib.parse
import http.client

import cv2
import mediapipe as mp
import numpy as np
from mediapipe.tasks import python
from mediapipe.tasks.python.vision import PoseLandmarker, PoseLandmarkerOptions, RunningMode


MODEL_PATH = Path(__file__).resolve().parent / "pose_landmarker_full.task"


def calculate_angle(a, b, c):
    a, b, c = np.array(a), np.array(b), np.array(c)
    ba, bc = a - b, c - b
    cosine = np.dot(ba, bc) / (np.linalg.norm(ba) * np.linalg.norm(bc) + 1e-6)
    return float(np.degrees(np.arccos(np.clip(cosine, -1.0, 1.0))))


def lm_coords(landmark, width, height):
    return [landmark.x * width, landmark.y * height]


def lm_pixel(landmark, width, height):
    return (int(landmark.x * width), int(landmark.y * height))


def draw_lines(frame, landmarks, width, height, connections):
    for start, end in connections:
        pt_a = lm_pixel(landmarks[start], width, height)
        pt_b = lm_pixel(landmarks[end], width, height)
        cv2.line(frame, pt_a, pt_b, (0, 255, 200), 4, cv2.LINE_AA)


class MJPEGStreamReader:
    def __init__(self, url, timeout=10):
        self.url = url
        self.timeout = timeout
        self.frame = None
        self.running = False
        self.thread = None
        self.lock = threading.Lock()

    def _stream_loop(self):
        parsed = urllib.parse.urlparse(self.url)
        host = parsed.hostname
        port = parsed.port or 80
        path = parsed.path or "/"

        while self.running:
            conn = None
            try:
                conn = http.client.HTTPConnection(host, port, timeout=self.timeout)
                conn.request("GET", path, headers={"Connection": "keep-alive"})
                response = conn.getresponse()
                if response.status != 200:
                    time.sleep(2)
                    continue

                buffer = b""
                while self.running:
                    chunk = response.read(4096)
                    if not chunk:
                        break
                    buffer += chunk
                    start = buffer.find(b"\xff\xd8")
                    end = buffer.find(b"\xff\xd9")
                    if start != -1 and end != -1 and end > start:
                        jpg = buffer[start:end + 2]
                        buffer = buffer[end + 2:]
                        arr = np.frombuffer(jpg, dtype=np.uint8)
                        image = cv2.imdecode(arr, cv2.IMREAD_COLOR)
                        if image is not None:
                            with self.lock:
                                self.frame = image
            except Exception:
                time.sleep(2)
            finally:
                if conn:
                    try:
                        conn.close()
                    except Exception:
                        pass

    def start(self):
        self.running = True
        self.thread = threading.Thread(target=self._stream_loop, daemon=True)
        self.thread.start()

    def read(self):
        with self.lock:
            if self.frame is None:
                return False, None
            return True, self.frame.copy()

    def stop(self):
        self.running = False


def get_pose_config(use_esp32):
    if use_esp32:
        screen_left_shoulder = 11
        screen_right_shoulder = 12
        screen_left_elbow = 13
        screen_right_elbow = 14
        screen_left_wrist = 15
        screen_right_wrist = 16
        screen_left_hip = 23
        screen_right_hip = 24
        screen_left_knee = 25
        screen_right_knee = 26
        screen_left_ankle = 27
        screen_right_ankle = 28
    else:
        screen_left_shoulder = 12
        screen_right_shoulder = 11
        screen_left_elbow = 14
        screen_right_elbow = 13
        screen_left_wrist = 16
        screen_right_wrist = 15
        screen_left_hip = 24
        screen_right_hip = 23
        screen_left_knee = 26
        screen_right_knee = 25
        screen_left_ankle = 28
        screen_right_ankle = 27

    return {
        "SCREEN_LEFT_SHOULDER": screen_left_shoulder,
        "SCREEN_RIGHT_SHOULDER": screen_right_shoulder,
        "SCREEN_LEFT_ELBOW": screen_left_elbow,
        "SCREEN_RIGHT_ELBOW": screen_right_elbow,
        "SCREEN_LEFT_WRIST": screen_left_wrist,
        "SCREEN_RIGHT_WRIST": screen_right_wrist,
        "SCREEN_LEFT_HIP": screen_left_hip,
        "SCREEN_RIGHT_HIP": screen_right_hip,
        "SCREEN_LEFT_KNEE": screen_left_knee,
        "SCREEN_RIGHT_KNEE": screen_right_knee,
        "SCREEN_LEFT_ANKLE": screen_left_ankle,
        "SCREEN_RIGHT_ANKLE": screen_right_ankle,
        "SQUAT_CONNECTIONS": [
            (screen_left_hip, screen_right_hip),
            (screen_left_hip, screen_left_knee),
            (screen_left_knee, screen_left_ankle),
            (screen_right_hip, screen_right_knee),
            (screen_right_knee, screen_right_ankle),
        ],
        "LEFT_ARM_CONNECTIONS": [
            (screen_left_shoulder, screen_left_elbow),
            (screen_left_elbow, screen_left_wrist),
        ],
        "RIGHT_ARM_CONNECTIONS": [
            (screen_right_shoulder, screen_right_elbow),
            (screen_right_elbow, screen_right_wrist),
        ],
    }


def squat_feedback(knee_angle, hip_angle):
    tips = []
    if knee_angle < 60:
        tips.append("Too deep - ease up on the knees")
    elif knee_angle > 155:
        tips.append("Go lower - aim for 90 degree bend")
    if hip_angle < 55:
        tips.append("Keep chest up - do not lean forward")
    return tips or ["Great form! Keep going!"]


def curl_feedback(elbow_angle):
    if elbow_angle > 160:
        return ["Extend fully at the bottom"]
    if elbow_angle < 40:
        return ["Nice contraction at the top"]
    return ["Controlled movement - keep it steady"]


class PostureBridge:
    def __init__(self):
        self.lock = threading.Lock()
        self.thread = None
        self.stop_event = threading.Event()
        self.cap = None
        self.running = False
        self.exercise = "squats"
        self.camera_source = "webcam"
        self.esp32_url = ""
        self.frame_jpeg = None
        self.stage = "READY"
        self.feedback = ["Stand in front of the camera"]
        self.rep_count = 0
        self.rep_count_left = 0
        self.rep_count_right = 0
        self.posture_score = 0
        self.fps = 0.0
        self.last_error = ""
        self.stage_left = None
        self.stage_right = None
        self.stage_main = None
        self.pose_config = get_pose_config(False)

    def snapshot(self):
        with self.lock:
            total_reps = self.rep_count if self.exercise == "squats" else self.rep_count_left + self.rep_count_right
            return {
                "running": self.running,
                "exercise": self.exercise,
                "camera_source": self.camera_source,
                "stage": self.stage,
                "feedback": list(self.feedback),
                "rep_count": self.rep_count,
                "rep_count_left": self.rep_count_left,
                "rep_count_right": self.rep_count_right,
                "total_reps": total_reps,
                "posture_score": self.posture_score,
                "fps": self.fps,
                "last_error": self.last_error,
            }

    def latest_frame(self):
        with self.lock:
            return self.frame_jpeg

    def start(self, exercise="squats", camera_source="webcam", esp32_url=""):
        self.stop()
        self.stop_event.clear()
        with self.lock:
            self.exercise = exercise
            self.camera_source = camera_source
            self.esp32_url = esp32_url
            self.stage = "READY"
            self.feedback = ["Stand in front of the camera"]
            self.rep_count = 0
            self.rep_count_left = 0
            self.rep_count_right = 0
            self.posture_score = 0
            self.last_error = ""
            self.stage_left = None
            self.stage_right = None
            self.stage_main = None
            self.pose_config = get_pose_config(camera_source == "esp32")
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=2)
        self.thread = None
        self.running = False
        if self.cap is not None:
            if hasattr(self.cap, "stop"):
                self.cap.stop()
            elif hasattr(self.cap, "release"):
                self.cap.release()
            self.cap = None

    def _open_camera(self):
        if self.camera_source == "esp32" and self.esp32_url:
            cap = MJPEGStreamReader(self.esp32_url, timeout=10)
            cap.start()
            received_frame = False
            for _ in range(40):
                time.sleep(0.25)
                ok, frame = cap.read()
                if ok and frame is not None:
                    received_frame = True
                    return cap
            cap.stop()
            self._set_error(f"No frames received from ESP32-CAM at {self.esp32_url}")
            return None
        cap = cv2.VideoCapture(0)
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
        return cap

    def _set_error(self, message):
        with self.lock:
            self.last_error = message

    def _encode_frame(self, frame):
        ok, encoded = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
        if ok:
            with self.lock:
                self.frame_jpeg = encoded.tobytes()

    def _update_squat(self, frame, landmarks, width, height):
        cfg = self.pose_config
        draw_lines(frame, landmarks, width, height, cfg["SQUAT_CONNECTIONS"])
        shoulder = lm_coords(landmarks[cfg["SCREEN_LEFT_SHOULDER"]], width, height)
        hip = lm_coords(landmarks[cfg["SCREEN_LEFT_HIP"]], width, height)
        knee = lm_coords(landmarks[cfg["SCREEN_LEFT_KNEE"]], width, height)
        ankle = lm_coords(landmarks[cfg["SCREEN_LEFT_ANKLE"]], width, height)
        knee_angle = calculate_angle(hip, knee, ankle)
        hip_angle = calculate_angle(shoulder, hip, knee)

        if knee_angle > 160:
            self.stage_main = "up"
        if knee_angle < 90 and self.stage_main == "up":
            self.stage_main = "down"
            self.rep_count += 1

        score = 100
        if knee_angle > 155:
            score -= 18
        if knee_angle < 60:
            score -= 12
        if hip_angle < 55:
            score -= 20
        self.posture_score = max(50, round(score))
        self.feedback = squat_feedback(knee_angle, hip_angle)
        self.stage = (self.stage_main or "ready").upper()

        knee_pt = lm_pixel(landmarks[cfg["SCREEN_LEFT_KNEE"]], width, height)
        hip_pt = lm_pixel(landmarks[cfg["SCREEN_LEFT_HIP"]], width, height)
        cv2.putText(frame, f"{int(knee_angle)}deg", (knee_pt[0] + 10, knee_pt[1]), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 0), 2)
        cv2.putText(frame, f"{int(hip_angle)}deg", (hip_pt[0] + 10, hip_pt[1]), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 0), 2)

    def _update_curls(self, frame, landmarks, width, height):
        cfg = self.pose_config
        both_arm_connections = cfg["LEFT_ARM_CONNECTIONS"] + cfg["RIGHT_ARM_CONNECTIONS"]
        draw_lines(frame, landmarks, width, height, both_arm_connections)
        left_angle = calculate_angle(
            lm_coords(landmarks[cfg["SCREEN_LEFT_SHOULDER"]], width, height),
            lm_coords(landmarks[cfg["SCREEN_LEFT_ELBOW"]], width, height),
            lm_coords(landmarks[cfg["SCREEN_LEFT_WRIST"]], width, height),
        )
        right_angle = calculate_angle(
            lm_coords(landmarks[cfg["SCREEN_RIGHT_SHOULDER"]], width, height),
            lm_coords(landmarks[cfg["SCREEN_RIGHT_ELBOW"]], width, height),
            lm_coords(landmarks[cfg["SCREEN_RIGHT_WRIST"]], width, height),
        )

        if left_angle > 150:
            self.stage_left = "down"
        if left_angle < 50 and self.stage_left == "down":
            self.stage_left = "up"
            self.rep_count_left += 1

        if right_angle > 150:
            self.stage_right = "down"
        if right_angle < 50 and self.stage_right == "down":
            self.stage_right = "up"
            self.rep_count_right += 1

        self.feedback = list(dict.fromkeys(curl_feedback(left_angle) + curl_feedback(right_angle)))
        self.posture_score = max(55, round(100 - max(0, left_angle - 160) / 3 - max(0, right_angle - 160) / 3))
        self.stage = f"L:{(self.stage_left or '-').upper()} R:{(self.stage_right or '-').upper()}"

        left_pt = lm_pixel(landmarks[cfg["SCREEN_LEFT_ELBOW"]], width, height)
        right_pt = lm_pixel(landmarks[cfg["SCREEN_RIGHT_ELBOW"]], width, height)
        cv2.putText(frame, f"L:{int(left_angle)}deg", (left_pt[0] + 10, left_pt[1]), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 0), 2)
        cv2.putText(frame, f"R:{int(right_angle)}deg", (right_pt[0] + 10, right_pt[1]), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 0), 2)

    def _draw_hud(self, frame, width):
        overlay = frame.copy()
        cv2.rectangle(overlay, (0, 0), (420, 220), (0, 0, 0), -1)
        cv2.addWeighted(overlay, 0.45, frame, 0.55, 0, frame)
        title = "SQUATS" if self.exercise == "squats" else "CURLS"
        cv2.putText(frame, title, (15, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 200), 2)
        cv2.putText(frame, f"FPS {self.fps:.1f}", (width - 150, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (180, 180, 180), 2)

        if self.exercise == "squats":
            reps_text = f"REPS: {self.rep_count}"
        else:
            reps_text = f"L:{self.rep_count_left} R:{self.rep_count_right}"
        cv2.putText(frame, reps_text, (15, 80), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0, 255, 128), 3)
        cv2.putText(frame, f"Stage: {self.stage}", (15, 125), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (200, 200, 200), 2)
        cv2.putText(frame, f"Score: {self.posture_score}%", (15, 155), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (255, 220, 80), 2)
        for index, tip in enumerate(self.feedback[:2]):
            cv2.putText(frame, tip, (15, 185 + index * 24), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 220, 255), 2)

    def _run(self):
        if not MODEL_PATH.exists():
            self._set_error(f"Missing model file: {MODEL_PATH}")
            return

        self.cap = self._open_camera()
        if not self.cap:
            return
        if hasattr(self.cap, "isOpened") and not self.cap.isOpened():
            self._set_error("Could not open posture camera source.")
            return

        self.running = True
        base_options = python.BaseOptions(model_asset_path=str(MODEL_PATH))
        options = PoseLandmarkerOptions(
            base_options=base_options,
            running_mode=RunningMode.VIDEO,
            min_pose_detection_confidence=0.6,
            min_pose_presence_confidence=0.6,
            min_tracking_confidence=0.6,
        )

        last_frame_time = time.time()
        with PoseLandmarker.create_from_options(options) as landmarker:
            while not self.stop_event.is_set():
                ok, frame = self.cap.read()
                if not ok or frame is None:
                    self._set_error("Could not read frame from posture camera.")
                    time.sleep(0.2)
                    continue

                if self.camera_source != "esp32":
                    frame = cv2.flip(frame, 1)
                height, width = frame.shape[:2]
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
                result = landmarker.detect_for_video(mp_image, int(time.time() * 1000))
                landmarks = result.pose_landmarks[0] if result.pose_landmarks else None

                if landmarks:
                    if self.exercise == "squats":
                        self._update_squat(frame, landmarks, width, height)
                    else:
                        self._update_curls(frame, landmarks, width, height)
                else:
                    self.feedback = ["Stand fully inside the camera frame"]
                    self.stage = "SEARCHING"
                    self.posture_score = 0

                now = time.time()
                self.fps = 1.0 / max(now - last_frame_time, 0.001)
                last_frame_time = now
                self._draw_hud(frame, width)
                self._encode_frame(frame)

        self.running = False
        if self.cap is not None:
            self.cap.release()
            self.cap = None
