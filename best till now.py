import cv2
import numpy as np
import mediapipe as mp
from mediapipe.tasks import python
from mediapipe.tasks.python import vision
from mediapipe.tasks.python.vision import PoseLandmarker, PoseLandmarkerOptions, RunningMode
import urllib.request
import urllib.parse
import os
import time
import sys
import threading

# ── Download model if not present ───────────────────────────────
MODEL_PATH = "pose_landmarker_full.task"
MODEL_URL  = "https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_full/float16/latest/pose_landmarker_full.task"

if not os.path.exists(MODEL_PATH):
    print("Downloading pose model (~7 MB) ...")
    urllib.request.urlretrieve(MODEL_URL, MODEL_PATH)
    print("Model downloaded!")

ESP32_IP         = "10.225.168.133"
ESP32_STREAM_URL = f"http://{ESP32_IP}/1024x768.mjpeg"

# ══════════════════════════════════════════════════════════════════
#  MJPEG byte-stream reader — robust ESP32-CAM connection
# ══════════════════════════════════════════════════════════════════
class MJPEGStreamReader:
    def __init__(self, url, timeout=10):
        self.url     = url
        self.timeout = timeout
        self.frame   = None
        self.running = False
        self._thread = None
        self._lock   = threading.Lock()

    def _stream_loop(self):
        import http.client
        parsed = urllib.parse.urlparse(self.url)
        host   = parsed.hostname
        port   = parsed.port or 80
        path   = parsed.path or "/"

        while self.running:
            conn = None
            try:
                conn = http.client.HTTPConnection(host, port, timeout=self.timeout)
                conn.request("GET", path, headers={"Connection": "keep-alive"})
                resp = conn.getresponse()

                if resp.status != 200:
                    print(f"\nHTTP {resp.status} from ESP32 — retrying...")
                    time.sleep(2)
                    continue

                buf = b""
                while self.running:
                    chunk = resp.read(4096)
                    if not chunk:
                        break
                    buf += chunk
                    start = buf.find(b'\xff\xd8')
                    end   = buf.find(b'\xff\xd9')
                    if start != -1 and end != -1 and end > start:
                        jpg = buf[start:end + 2]
                        buf = buf[end + 2:]
                        arr = np.frombuffer(jpg, dtype=np.uint8)
                        img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
                        if img is not None:
                            with self._lock:
                                self.frame = img

            except Exception as e:
                print(f"\nStream error: {e} — reconnecting in 2s...")
                time.sleep(2)
            finally:
                if conn:
                    try: conn.close()
                    except: pass

    def start(self):
        self.running = True
        self._thread = threading.Thread(target=self._stream_loop, daemon=True)
        self._thread.start()

    def read(self):
        with self._lock:
            if self.frame is None:
                return False, None
            return True, self.frame.copy()

    def stop(self):
        self.running = False

# ── Camera source selection ──────────────────────────────────────
print("\n=== AI Exercise Analyzer ===")
print("Camera source:")
print("  1. Laptop Webcam")
print("  2. ESP32-CAM")
cam_choice = input("Select camera (1 / 2): ").strip()

if cam_choice == "2":
    USE_ESP32 = True
    cam_label = "ESP32-CAM"
else:
    USE_ESP32 = False
    cam_label = "Webcam"

# ── Landmark indices ─────────────────────────────────────────────
# Webcam: frame is flipped (selfie view) so left/right are swapped vs MediaPipe IDs
# ESP32:  frame is NOT flipped so MediaPipe IDs map directly
if USE_ESP32:
    SCREEN_LEFT_SHOULDER  = 11
    SCREEN_RIGHT_SHOULDER = 12
    SCREEN_LEFT_ELBOW     = 13
    SCREEN_RIGHT_ELBOW    = 14
    SCREEN_LEFT_WRIST     = 15
    SCREEN_RIGHT_WRIST    = 16
    SCREEN_LEFT_HIP       = 23
    SCREEN_RIGHT_HIP      = 24
    SCREEN_LEFT_KNEE      = 25
    SCREEN_RIGHT_KNEE     = 26
    SCREEN_LEFT_ANKLE     = 27
    SCREEN_RIGHT_ANKLE    = 28
else:
    # After cv2.flip(frame,1): subject right → screen left
    SCREEN_LEFT_SHOULDER  = 12
    SCREEN_RIGHT_SHOULDER = 11
    SCREEN_LEFT_ELBOW     = 14
    SCREEN_RIGHT_ELBOW    = 13
    SCREEN_LEFT_WRIST     = 16
    SCREEN_RIGHT_WRIST    = 15
    SCREEN_LEFT_HIP       = 24
    SCREEN_RIGHT_HIP      = 23
    SCREEN_LEFT_KNEE      = 26
    SCREEN_RIGHT_KNEE     = 25
    SCREEN_LEFT_ANKLE     = 28
    SCREEN_RIGHT_ANKLE    = 27

# ── Connection sets ──────────────────────────────────────────────
SQUAT_CONNECTIONS = [
    (SCREEN_LEFT_HIP,   SCREEN_RIGHT_HIP),
    (SCREEN_LEFT_HIP,   SCREEN_LEFT_KNEE),
    (SCREEN_LEFT_KNEE,  SCREEN_LEFT_ANKLE),
    (SCREEN_RIGHT_HIP,  SCREEN_RIGHT_KNEE),
    (SCREEN_RIGHT_KNEE, SCREEN_RIGHT_ANKLE),
]
LEFT_ARM_CONNECTIONS = [
    (SCREEN_LEFT_SHOULDER, SCREEN_LEFT_ELBOW),
    (SCREEN_LEFT_ELBOW,    SCREEN_LEFT_WRIST),
]
RIGHT_ARM_CONNECTIONS = [
    (SCREEN_RIGHT_SHOULDER, SCREEN_RIGHT_ELBOW),
    (SCREEN_RIGHT_ELBOW,    SCREEN_RIGHT_WRIST),
]
BOTH_ARM_CONNECTIONS = LEFT_ARM_CONNECTIONS + RIGHT_ARM_CONNECTIONS

LINE_COLOR     = (0, 255, 200)
LINE_THICKNESS = 4

# ── Helpers ──────────────────────────────────────────────────────
def calculate_angle(a, b, c):
    a, b, c = np.array(a), np.array(b), np.array(c)
    ba, bc  = a - b, c - b
    cos_val = np.dot(ba, bc) / (np.linalg.norm(ba) * np.linalg.norm(bc) + 1e-6)
    return float(np.degrees(np.arccos(np.clip(cos_val, -1.0, 1.0))))

def lm_coords(landmark, w, h):
    return [landmark.x * w, landmark.y * h]

def lm_pixel(landmark, w, h):
    return (int(landmark.x * w), int(landmark.y * h))

def draw_lines(frame, lms, fw, fh, connections):
    for (a, b) in connections:
        pt_a = lm_pixel(lms[a], fw, fh)
        pt_b = lm_pixel(lms[b], fw, fh)
        cv2.line(frame, pt_a, pt_b, LINE_COLOR, LINE_THICKNESS, cv2.LINE_AA)

# ── Feedback ─────────────────────────────────────────────────────
def squat_feedback(knee_ang, hip_ang):
    tips = []
    if knee_ang < 60:
        tips.append("Too deep — ease up on the knees!")
    elif knee_ang > 155:
        tips.append("Go lower — aim for a 90 deg bend")
    if hip_ang < 55:
        tips.append("Keep chest up — don't lean forward")
    return tips or ["Great form! Keep going!"]

def curl_feedback(elbow_ang):
    if elbow_ang > 160:
        return ["Extend fully at the bottom"]
    elif elbow_ang < 40:
        return ["Nice contraction at the top!"]
    return ["Controlled movement — keep it steady"]

# ── Terminal live status ──────────────────────────────────────────
def print_live_status(mode_label, exercise, curl_mode,
                      rep_count, rep_count_left, rep_count_right, feedback):
    if exercise == "squats":
        reps_str = f"Reps: {rep_count}"
    elif curl_mode == "left":
        reps_str = f"Left Reps: {rep_count_left}"
    elif curl_mode == "right":
        reps_str = f"Right Reps: {rep_count_right}"
    else:
        reps_str = f"Left: {rep_count_left}  |  Right: {rep_count_right}"

    tips_str = " / ".join(feedback[:2]) if feedback else "—"
    sys.stdout.write(
        f"\r\033[2K┌─ {mode_label} ──────────────────────────\n"
        f"\033[2K│  {reps_str}\n"
        f"\033[2K│  Tip: {tips_str}\n"
        f"\033[2K└─────────────────────────────────────────\n"
        f"\033[4A"
    )
    sys.stdout.flush()

# ── Milestone recommendations ─────────────────────────────────────
def milestone_recommendation(total_reps):
    milestones = {
        5:  "Good warm-up! Keep your breathing steady.",
        10: "10 reps! Focus on controlled movement.",
        15: "Halfway to 30! Stay strong.",
        20: "20 reps — excellent endurance!",
        25: "Almost there — push through!",
        30: "30 reps! Consider a short rest.",
        50: "50 reps! Outstanding stamina!",
    }
    if total_reps in milestones:
        print(f"\n\n  Rep {total_reps}: {milestones[total_reps]}\n")

# ── Open camera ──────────────────────────────────────────────────
if USE_ESP32:
    print(f"\nConnecting to ESP32-CAM at {ESP32_STREAM_URL} ...")
    cap = MJPEGStreamReader(ESP32_STREAM_URL, timeout=10)
    cap.start()

    print("Waiting for first frame", end="", flush=True)
    for _ in range(40):
        time.sleep(0.25)
        ret, frame = cap.read()
        if ret and frame is not None:
            print(f"\nConnected! Resolution: {frame.shape[1]}x{frame.shape[0]}")
            break
        print(".", end="", flush=True)
    else:
        print("\nERROR: No frames received from ESP32-CAM.")
        print(f"  URL tried: {ESP32_STREAM_URL}")
        print("  Check: same WiFi? ESP32 powered on? IP correct?")
        cap.stop()
        exit(1)
else:
    cap = cv2.VideoCapture(0)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH,  1280)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
    if not cap.isOpened():
        print("ERROR: Could not open webcam.")
        exit(1)
    print("Webcam opened successfully.")

# ── Exercise selection ───────────────────────────────────────────
exercise = input("\nWhich exercise? (squats / curls): ").strip().lower()
if exercise not in ["squats", "curls"]:
    print("Invalid choice. Exiting.")
    exit()

curl_mode = None
if exercise == "curls":
    hand_count = input("One hand or both hands? (one / both): ").strip().lower()
    if hand_count == "one":
        hand_choice = input("Which hand? (left / right): ").strip().lower()
        curl_mode = hand_choice if hand_choice in ["left", "right"] else "left"
    else:
        curl_mode = "both"

if exercise == "squats":
    mode_label = "Squats"
elif curl_mode == "both":
    mode_label = "Curls — Both Hands"
else:
    mode_label = f"Curls — {curl_mode.capitalize()} Hand"

# ── State ────────────────────────────────────────────────────────
rep_count_left  = 0
rep_count_right = 0
rep_count       = 0
stage_left      = None
stage_right     = None
stage           = None
feedback        = ["Stand in front of the camera!"]
last_angles     = {}
latest_lms      = None
prev_total_reps = 0

def on_result(result, output_image, timestamp_ms):
    global latest_lms
    latest_lms = result.pose_landmarks[0] if result.pose_landmarks else None

# ── Build landmarker ─────────────────────────────────────────────
base_options = python.BaseOptions(model_asset_path=MODEL_PATH)
options = PoseLandmarkerOptions(
    base_options=base_options,
    running_mode=RunningMode.LIVE_STREAM,
    result_callback=on_result,
    min_pose_detection_confidence=0.6,
    min_pose_presence_confidence=0.6,
    min_tracking_confidence=0.6,
)

print(f"\nAI {mode_label} Analyzer [{cam_label}] running — press Q to quit\n")
print(); print(); print(); print()

# ── Main loop ────────────────────────────────────────────────────
with PoseLandmarker.create_from_options(options) as landmarker:
    ts           = 0
    last_frame_t = time.time()

    while True:
        ret, frame = cap.read()

        if not ret or frame is None:
            if USE_ESP32:
                time.sleep(0.05)   # background thread is reconnecting
                continue
            else:
                break

        fh, fw = frame.shape[:2]

        # Flip only for webcam (selfie view)
        if not USE_ESP32:
            frame = cv2.flip(frame, 1)

        rgb      = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
        landmarker.detect_async(mp_image, ts)
        ts += 33

        lms = latest_lms

        if lms:
            # ── Draw skeleton lines ───────────────────────────────
            if exercise == "squats":
                draw_lines(frame, lms, fw, fh, SQUAT_CONNECTIONS)
            elif curl_mode == "left":
                draw_lines(frame, lms, fw, fh, LEFT_ARM_CONNECTIONS)
            elif curl_mode == "right":
                draw_lines(frame, lms, fw, fh, RIGHT_ARM_CONNECTIONS)
            elif curl_mode == "both":
                draw_lines(frame, lms, fw, fh, BOTH_ARM_CONNECTIONS)

            # ── Squat logic (from working webcam code) ────────────
            if exercise == "squats":
                shoulder = lm_coords(lms[SCREEN_LEFT_SHOULDER], fw, fh)
                hip      = lm_coords(lms[SCREEN_LEFT_HIP],      fw, fh)
                knee     = lm_coords(lms[SCREEN_LEFT_KNEE],     fw, fh)
                ankle    = lm_coords(lms[SCREEN_LEFT_ANKLE],    fw, fh)

                knee_ang = calculate_angle(hip, knee, ankle)
                hip_ang  = calculate_angle(shoulder, hip, knee)

                if knee_ang > 160:
                    stage = "up"
                if knee_ang < 90 and stage == "up":
                    stage = "down"
                    rep_count += 1

                feedback = squat_feedback(knee_ang, hip_ang)

                knee_pt = lm_pixel(lms[SCREEN_LEFT_KNEE], fw, fh)
                hip_pt  = lm_pixel(lms[SCREEN_LEFT_HIP],  fw, fh)
                cv2.putText(frame, f"{int(knee_ang)}deg",
                            (knee_pt[0]+10, knee_pt[1]),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 0), 2)
                cv2.putText(frame, f"{int(hip_ang)}deg",
                            (hip_pt[0]+10, hip_pt[1]),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 0), 2)

            # ── Curl logic (from working webcam code) ─────────────
            elif exercise == "curls":
                if curl_mode in ("left", "both"):
                    l_ang = calculate_angle(
                        lm_coords(lms[SCREEN_LEFT_SHOULDER], fw, fh),
                        lm_coords(lms[SCREEN_LEFT_ELBOW],    fw, fh),
                        lm_coords(lms[SCREEN_LEFT_WRIST],    fw, fh),
                    )
                    last_angles["L"] = l_ang
                    if l_ang > 150:
                        stage_left = "down"
                    if l_ang < 50 and stage_left == "down":
                        stage_left = "up"
                        rep_count_left += 1
                    l_pt = lm_pixel(lms[SCREEN_LEFT_ELBOW], fw, fh)
                    cv2.putText(frame, f"L:{int(l_ang)}deg",
                                (l_pt[0]+10, l_pt[1]),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 0), 2)

                if curl_mode in ("right", "both"):
                    r_ang = calculate_angle(
                        lm_coords(lms[SCREEN_RIGHT_SHOULDER], fw, fh),
                        lm_coords(lms[SCREEN_RIGHT_ELBOW],    fw, fh),
                        lm_coords(lms[SCREEN_RIGHT_WRIST],    fw, fh),
                    )
                    last_angles["R"] = r_ang
                    if r_ang > 150:
                        stage_right = "down"
                    if r_ang < 50 and stage_right == "down":
                        stage_right = "up"
                        rep_count_right += 1
                    r_pt = lm_pixel(lms[SCREEN_RIGHT_ELBOW], fw, fh)
                    cv2.putText(frame, f"R:{int(r_ang)}deg",
                                (r_pt[0]+10, r_pt[1]),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 0), 2)

                if curl_mode == "left":
                    feedback = curl_feedback(last_angles.get("L", 90))
                elif curl_mode == "right":
                    feedback = curl_feedback(last_angles.get("R", 90))
                else:
                    feedback = list(dict.fromkeys(
                        curl_feedback(last_angles.get("L", 90)) +
                        curl_feedback(last_angles.get("R", 90))
                    ))

        # ── Milestone check ───────────────────────────────────────
        if exercise == "squats":
            total_reps = rep_count
        elif curl_mode == "both":
            total_reps = rep_count_left + rep_count_right
        elif curl_mode == "left":
            total_reps = rep_count_left
        else:
            total_reps = rep_count_right

        if total_reps != prev_total_reps:
            milestone_recommendation(total_reps)
            prev_total_reps = total_reps

        print_live_status(mode_label, exercise, curl_mode,
                          rep_count, rep_count_left, rep_count_right, feedback)

        # ── FPS ───────────────────────────────────────────────────
        now          = time.time()
        fps          = 1.0 / max(now - last_frame_t, 0.001)
        last_frame_t = now

        # ── HUD overlay ───────────────────────────────────────────
        overlay = frame.copy()
        cv2.rectangle(overlay, (0, 0), (390, 210), (0, 0, 0), -1)
        cv2.addWeighted(overlay, 0.45, frame, 0.55, 0, frame)

        cv2.putText(frame, mode_label.upper(), (15, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 255, 200), 2)
        cv2.putText(frame, f"{cam_label}  {fps:.1f}fps", (fw - 240, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (180, 180, 180), 2)

        if exercise == "squats":
            cv2.putText(frame, f"REPS: {rep_count}", (15, 80),
                        cv2.FONT_HERSHEY_SIMPLEX, 1.4, (0, 255, 128), 3)
        elif curl_mode == "left":
            cv2.putText(frame, f"LEFT REPS: {rep_count_left}", (15, 80),
                        cv2.FONT_HERSHEY_SIMPLEX, 1.1, (0, 255, 128), 3)
        elif curl_mode == "right":
            cv2.putText(frame, f"RIGHT REPS: {rep_count_right}", (15, 80),
                        cv2.FONT_HERSHEY_SIMPLEX, 1.1, (0, 255, 128), 3)
        elif curl_mode == "both":
            cv2.putText(frame, f"L: {rep_count_left}   R: {rep_count_right}", (15, 80),
                        cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0, 255, 128), 3)

        stage_val = stage if exercise == "squats" else (stage_left or stage_right or "—")
        cv2.putText(frame, f"Stage: {str(stage_val).upper()}", (15, 125),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.65, (200, 200, 200), 2)

        for i, tip in enumerate(feedback[:2]):
            cv2.putText(frame, tip, (15, 158 + i * 28),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 220, 255), 2)

        cv2.imshow(f"AI {mode_label} — {cam_label}", frame)
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

# ── Cleanup ──────────────────────────────────────────────────────
if USE_ESP32:
    cap.stop()
else:
    cap.release()
cv2.destroyAllWindows()

# ── Final summary ─────────────────────────────────────────────────
print("\n\n\n\n")
print("=" * 44)
print(f"  SESSION COMPLETE — {mode_label} [{cam_label}]")
print("=" * 44)

if exercise == "squats":
    print(f"  Total Squats : {rep_count}")
elif curl_mode == "left":
    print(f"  Left  Curls  : {rep_count_left}")
elif curl_mode == "right":
    print(f"  Right Curls  : {rep_count_right}")
elif curl_mode == "both":
    print(f"  Left  Curls  : {rep_count_left}")
    print(f"  Right Curls  : {rep_count_right}")
    print(f"  Total Curls  : {rep_count_left + rep_count_right}")

print()

if exercise == "squats":       final_total = rep_count
elif curl_mode == "both":      final_total = rep_count_left + rep_count_right
elif curl_mode == "left":      final_total = rep_count_left
else:                          final_total = rep_count_right

print("  Recommendation:")
if final_total == 0:
    print("  No reps detected. Make sure you are fully visible to the camera.")
elif final_total < 5:
    print("  Short session — try to aim for at least 3 sets of 10 reps.")
elif final_total < 10:
    print("  Good start! Next session aim for 10+ reps per set.")
elif final_total < 20:
    print("  Solid effort! Try increasing to 3 sets of 12-15 for muscle growth.")
elif final_total < 30:
    print("  Great session! Add a bit more weight or resistance next time.")
elif final_total < 50:
    print("  Excellent endurance! Consider adding progressive overload.")
else:
    print("  Outstanding performance! Make sure to rest and recover well.")

print("=" * 44)