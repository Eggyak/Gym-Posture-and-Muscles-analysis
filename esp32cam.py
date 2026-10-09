import cv2
import numpy as np
import mediapipe as mp
from mediapipe.tasks import python
from mediapipe.tasks.python import vision
from mediapipe.tasks.python.vision import PoseLandmarker, PoseLandmarkerOptions, RunningMode
import urllib.request
import urllib.error
import os
import time

# ── Download model if not present ───────────────────────────────
MODEL_PATH = "pose_landmarker_full.task"
MODEL_URL  = "https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_full/float16/latest/pose_landmarker_full.task"

if not os.path.exists(MODEL_PATH):
    print("Downloading pose model (~7 MB) ...")
    urllib.request.urlretrieve(MODEL_URL, MODEL_PATH)
    print("Model downloaded!")

# ── ESP32-CAM stream URL ─────────────────────────────────────────
ESP32_STREAM_URL = "http://10.225.168.133/1280x1024.mjpeg"

# ── Landmark indices ─────────────────────────────────────────────
# ESP32-CAM is a fixed external camera, NOT a selfie/mirror camera.
# We do NOT flip the frame, so MediaPipe's native landmark IDs map
# directly: subject's LEFT = screen LEFT, subject's RIGHT = screen RIGHT.
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
        tips.append("Go lower — aim for 90 deg bend")
    if hip_ang < 55:
        tips.append("Keep chest up — don't lean forward")
    return tips or ["Great form! Keep going!"]

def curl_feedback(elbow_ang):
    if elbow_ang > 160:
        return ["Extend fully at the bottom"]
    elif elbow_ang < 40:
        return ["Nice contraction at the top!"]
    return ["Controlled movement — keep it steady"]

# ── ESP32 MJPEG stream reader ────────────────────────────────────
def open_esp32_stream(url, retries=5, delay=2):
    """Open ESP32-CAM MJPEG stream via OpenCV with retry logic."""
    for attempt in range(1, retries + 1):
        print(f"Connecting to ESP32-CAM (attempt {attempt}/{retries})...")
        cap = cv2.VideoCapture(url, cv2.CAP_FFMPEG)
        # Give the stream a moment to buffer
        time.sleep(1.0)
        if cap.isOpened():
            ret, frame = cap.read()
            if ret and frame is not None:
                print(f"Connected! Stream resolution: {frame.shape[1]}x{frame.shape[0]}")
                return cap
            cap.release()
        print(f"  Failed — retrying in {delay}s...")
        time.sleep(delay)
    return None

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

# ── Exercise selection ───────────────────────────────────────────
print("\n=== AI Exercise Analyzer (ESP32-CAM) ===")
exercise = input("Which exercise? (squats / curls): ").strip().lower()
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

# ── Open ESP32 stream ────────────────────────────────────────────
cap = open_esp32_stream(ESP32_STREAM_URL)
if cap is None:
    print("\nERROR: Could not connect to ESP32-CAM.")
    print(f"  Make sure the camera is powered on and reachable at:")
    print(f"  {ESP32_STREAM_URL}")
    print("  Also ensure your PC is on the same WiFi network.\n")
    exit(1)

print(f"\nAI {mode_label} Analyzer running — press Q to quit\n")

# ── Main loop ────────────────────────────────────────────────────
with PoseLandmarker.create_from_options(options) as landmarker:
    ts           = 0
    last_frame_t = time.time()
    dropped      = 0

    while True:
        ret, frame = cap.read()

        # ── Reconnect if stream drops ────────────────────────────
        if not ret or frame is None:
            dropped += 1
            print(f"Stream lost (drop #{dropped}) — reconnecting...")
            cap.release()
            time.sleep(1.5)
            cap = open_esp32_stream(ESP32_STREAM_URL, retries=10, delay=2)
            if cap is None:
                print("Could not reconnect. Exiting.")
                break
            continue

        fh, fw = frame.shape[:2]

        # ── Feed to MediaPipe ────────────────────────────────────
        # No flip — ESP32 is a fixed external camera, not a selfie cam.
        rgb      = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
        landmarker.detect_async(mp_image, ts)
        ts += 33

        lms = latest_lms

        if lms:
            # ── Draw lines for active body parts only ────────────
            if exercise == "squats":
                draw_lines(frame, lms, fw, fh, SQUAT_CONNECTIONS)
            elif curl_mode == "left":
                draw_lines(frame, lms, fw, fh, LEFT_ARM_CONNECTIONS)
            elif curl_mode == "right":
                draw_lines(frame, lms, fw, fh, RIGHT_ARM_CONNECTIONS)
            elif curl_mode == "both":
                draw_lines(frame, lms, fw, fh, BOTH_ARM_CONNECTIONS)

            # ── Angle logic ──────────────────────────────────────
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

        # ── FPS counter ──────────────────────────────────────────
        now    = time.time()
        fps    = 1.0 / max(now - last_frame_t, 0.001)
        last_frame_t = now

        # ── HUD ──────────────────────────────────────────────────
        overlay = frame.copy()
        cv2.rectangle(overlay, (0, 0), (390, 210), (0, 0, 0), -1)
        cv2.addWeighted(overlay, 0.45, frame, 0.55, 0, frame)

        cv2.putText(frame, mode_label.upper(), (15, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 255, 200), 2)

        # ESP32 cam label + FPS top-right
        cv2.putText(frame, f"ESP32-CAM  {fps:.1f}fps",
                    (fw - 260, 30),
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

        cv2.imshow(f"AI {mode_label} Analyzer — ESP32-CAM", frame)
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

cap.release()
cv2.destroyAllWindows()

print(f"\n{'='*40}")
print(f"Session Complete — {mode_label}")
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
print('='*40)