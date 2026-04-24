"""
Real-Time Webcam Face Detection + Emotion Recognition
=======================================================
Uses OpenCV (Haar Cascade) for face detection and
DeepFace for emotion analysis (runs in background thread).

Requirements:
    pip install opencv-python deepface

First run will auto-download the emotion model (~small, one-time only).

Controls:
    Q / ESC  → Quit
    E        → Toggle eye detection
    M        → Toggle emotion display
    S        → Save screenshot
    +/-      → Adjust detection sensitivity
"""

import cv2
import sys
import threading
import queue
import time
from datetime import datetime

# ── Try importing DeepFace ────────────────────────────────────────────────────
try:
    from deepface import DeepFace
    DEEPFACE_AVAILABLE = True
except ImportError:
    DEEPFACE_AVAILABLE = False
    print("[WARN] deepface not installed. Run: pip install deepface")
    print("[WARN] Continuing with face detection only.\n")


# ── Configuration ─────────────────────────────────────────────────────────────

FACE_SCALE_FACTOR  = 1.1
FACE_MIN_NEIGHBORS = 5
FACE_MIN_SIZE      = (60, 60)
EYE_SCALE_FACTOR   = 1.1
EYE_MIN_NEIGHBORS  = 10

# Emotion → color (BGR) + emoji
EMOTION_STYLE = {
    "happy":    ((0,   210, 255), "😊"),
    "sad":      ((200,  80,  60), "😢"),
    "angry":    ((30,   30, 220), "😠"),
    "fear":     ((160,  60, 200), "😨"),
    "surprise": ((0,   200, 200), "😲"),
    "disgust":  ((40,  160,  40), "🤢"),
    "neutral":  ((180, 180, 180), "😐"),
}
DEFAULT_EMOTION_COLOR = (200, 200, 200)

FONT = cv2.FONT_HERSHEY_SIMPLEX

# How often to run emotion analysis (seconds) — keeps CPU usage low
EMOTION_INTERVAL = 0.6


# ── Load Haar Cascades ────────────────────────────────────────────────────────

def load_cascades():
    face_cascade = cv2.CascadeClassifier(
        cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
    )
    eye_cascade = cv2.CascadeClassifier(
        cv2.data.haarcascades + "haarcascade_eye.xml"
    )
    if face_cascade.empty():
        print("[ERROR] Could not load face cascade.")
        sys.exit(1)
    return face_cascade, eye_cascade


# ── Camera helpers ────────────────────────────────────────────────────────────

def try_open_camera(index, backend, timeout=3.0):
    result = [None, None]

    def _open():
        try:
            cap = cv2.VideoCapture(index, backend)
            if not cap.isOpened():
                return
            ret, frame = cap.read()
            if ret and frame is not None and frame.size > 0:
                result[0] = cap
                result[1] = frame
            else:
                cap.release()
        except Exception:
            pass

    t = threading.Thread(target=_open, daemon=True)
    t.start()
    t.join(timeout)
    return result[0], result[1]


def find_camera():
    backends = [
        (cv2.CAP_MSMF,  "MSMF"),
        (cv2.CAP_DSHOW, "DirectShow"),
        (cv2.CAP_ANY,   "Auto"),
    ]
    for index in range(3):
        for backend, name in backends:
            print(f"[...] Camera {index} via {name}...", end=" ", flush=True)
            cap, frame = try_open_camera(index, backend, timeout=3.0)
            if cap is None:
                print("timeout")
                continue
            mean = cv2.mean(frame)
            if mean[0] < 2 and mean[1] < 2 and mean[2] < 2:
                print("black frame")
                cap.release()
                continue
            print("OK ✓")
            return cap
    return None


# ── Emotion analysis (background thread) ─────────────────────────────────────

class EmotionAnalyzer:
    """
    Runs DeepFace emotion analysis in a background thread.
    Main loop submits frames via submit(); results are read via get_results().
    This way emotion analysis never blocks the camera feed.
    """

    def __init__(self):
        self._in_q   = queue.Queue(maxsize=1)   # latest frame to analyze
        self._out_q  = queue.Queue(maxsize=1)   # latest results
        self._active = True
        self._thread = threading.Thread(target=self._worker, daemon=True)
        self._thread.start()

    def submit(self, frame):
        """Send a frame for analysis (drops if worker is busy)."""
        try:
            self._in_q.put_nowait(frame.copy())
        except queue.Full:
            pass

    def get_results(self):
        """Return latest results dict {face_idx: emotion_str} or {}."""
        try:
            return self._out_q.get_nowait()
        except queue.Empty:
            return None

    def stop(self):
        self._active = False

    def _worker(self):
        while self._active:
            try:
                frame = self._in_q.get(timeout=0.5)
            except queue.Empty:
                continue

            try:
                results = DeepFace.analyze(
                    frame,
                    actions=["emotion"],
                    enforce_detection=False,
                    silent=True,
                )
                # results is a list of dicts, one per face
                emotions = {}
                for i, r in enumerate(results):
                    emotions[i] = r.get("dominant_emotion", "neutral")
                try:
                    self._out_q.put_nowait(emotions)
                except queue.Full:
                    self._out_q.get_nowait()
                    self._out_q.put_nowait(emotions)
            except Exception:
                pass


# ── Drawing helpers ───────────────────────────────────────────────────────────

def draw_face_box(frame, x, y, w, h, emotion=None):
    """Corner-bracket face box, colored by emotion."""
    color = EMOTION_STYLE.get(emotion, (None, None))[0] if emotion else None
    color = color or (0, 220, 120)

    c = 20
    segs = [
        ((x, y + c), (x, y), (x + c, y)),
        ((x + w - c, y), (x + w, y), (x + w, y + c)),
        ((x + w, y + h - c), (x + w, y + h), (x + w - c, y + h)),
        ((x + c, y + h), (x, y + h), (x, y + h - c)),
    ]
    for seg in segs:
        for i in range(len(seg) - 1):
            cv2.line(frame, seg[i], seg[i + 1], color, 2)

    # Subtle tinted overlay inside
    ov = frame.copy()
    cv2.rectangle(ov, (x, y), (x + w, y + h), color, -1)
    cv2.addWeighted(ov, 0.06, frame, 0.94, 0, frame)

    # Emotion label below the box
    if emotion:
        emoji = EMOTION_STYLE.get(emotion, ("", ""))[1]
        label = f"{emoji} {emotion.upper()}"
        ty = y + h + 20
        # Background pill
        (tw, th), _ = cv2.getTextSize(label, FONT, 0.55, 1)
        cv2.rectangle(frame, (x, ty - th - 4), (x + tw + 8, ty + 4), color, -1)
        cv2.putText(frame, label, (x + 4, ty), FONT, 0.55, (0, 0, 0), 1, cv2.LINE_AA)


def draw_eye_dots(frame, roi_color, roi_gray):
    eye_cascade = cv2.CascadeClassifier(
        cv2.data.haarcascades + "haarcascade_eye.xml"
    )
    eyes = eye_cascade.detectMultiScale(roi_gray, 1.1, 10)
    for (ex, ey, ew, eh) in eyes:
        cv2.rectangle(roi_color, (ex, ey), (ex+ew, ey+eh), (80, 180, 255), 1)
        cv2.circle(roi_color, (ex+ew//2, ey+eh//2), 3, (80, 180, 255), -1)


def draw_hud(frame, face_count, show_emotion, eye_on, sensitivity, fps):
    fh, fw = frame.shape[:2]

    # Top bar
    ov = frame.copy()
    cv2.rectangle(ov, (0, 0), (fw, 38), (10, 10, 10), -1)
    cv2.addWeighted(ov, 0.6, frame, 0.4, 0, frame)

    cv2.putText(frame, "● LIVE",               (10, 26),  FONT, 0.55, (0, 220, 120), 1, cv2.LINE_AA)
    cv2.putText(frame, f"Faces: {face_count}", (90, 26),  FONT, 0.55, (255,255,255), 1, cv2.LINE_AA)
    cv2.putText(frame, f"FPS: {fps:.0f}",      (190, 26), FONT, 0.55, (255,255,255), 1, cv2.LINE_AA)
    cv2.putText(frame, f"Sen: {sensitivity}",  (265, 26), FONT, 0.55, (255,255,255), 1, cv2.LINE_AA)

    em_col  = (0, 200, 255) if show_emotion else (100, 100, 100)
    eye_col = (80, 180, 255) if eye_on else (100, 100, 100)
    cv2.putText(frame, f"Mood: {'ON' if show_emotion else 'OFF'}", (fw - 220, 26), FONT, 0.5, em_col,  1, cv2.LINE_AA)
    cv2.putText(frame, f"Eyes: {'ON' if eye_on else 'OFF'}",       (fw - 110, 26), FONT, 0.5, eye_col, 1, cv2.LINE_AA)

    # Bottom bar
    ov2 = frame.copy()
    cv2.rectangle(ov2, (0, fh - 30), (fw, fh), (10, 10, 10), -1)
    cv2.addWeighted(ov2, 0.6, frame, 0.4, 0, frame)
    cv2.putText(frame, "Q/ESC: Quit  |  M: Mood  |  E: Eyes  |  S: Screenshot  |  +/-: Sensitivity",
                (10, fh - 10), FONT, 0.38, (160, 160, 160), 1, cv2.LINE_AA)


def save_screenshot(frame, face_count):
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    fn = f"screenshot_{ts}_faces{face_count}.png"
    cv2.imwrite(fn, frame)
    print(f"[INFO] Saved → {fn}")


# ── Main loop ─────────────────────────────────────────────────────────────────

def run():
    face_cascade, eye_cascade = load_cascades()

    print("[INFO] Searching for webcam...")
    cap = find_camera()
    if cap is None:
        print("\n[ERROR] No working camera found.")
        print("[TIP]  Windows: Settings > Privacy & Security > Camera → allow Python")
        print("[TIP]  Close Teams, Zoom, or any other app using the camera")
        sys.exit(1)

    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)

    # Start emotion analyzer
    analyzer      = EmotionAnalyzer() if DEEPFACE_AVAILABLE else None
    last_emotions = {}          # {face_idx: emotion_str}
    last_sent     = 0.0         # time we last submitted a frame for analysis

    eye_detection  = False
    show_emotion   = True
    sensitivity    = 3
    prev_tick      = cv2.getTickCount()
    fps            = 0.0

    print("[INFO] Ready! Press Q or ESC to quit.\n")
    if DEEPFACE_AVAILABLE:
        print("[INFO] Emotion model will load on first detection (one-time, ~2 sec).\n")

    while True:
        ret, frame = cap.read()
        if not ret or frame is None:
            continue

        tick      = cv2.getTickCount()
        fps       = cv2.getTickFrequency() / max(tick - prev_tick, 1)
        prev_tick = tick

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        gray = cv2.equalizeHist(gray)

        min_neighbors = max(1, FACE_MIN_NEIGHBORS - 3 + sensitivity)
        faces = face_cascade.detectMultiScale(
            gray,
            scaleFactor  = FACE_SCALE_FACTOR,
            minNeighbors = min_neighbors,
            minSize      = FACE_MIN_SIZE,
            flags        = cv2.CASCADE_SCALE_IMAGE,
        )
        face_count = len(faces) if len(faces) > 0 else 0

        # Submit frame for emotion analysis periodically
        if analyzer and show_emotion and face_count > 0:
            now = time.time()
            if now - last_sent >= EMOTION_INTERVAL:
                analyzer.submit(frame)
                last_sent = now

        # Pull latest emotion results if available
        if analyzer:
            new = analyzer.get_results()
            if new is not None:
                last_emotions = new

        # Draw faces
        for i, (x, y, w, h) in enumerate(faces):
            emotion = last_emotions.get(i) if show_emotion else None
            draw_face_box(frame, x, y, w, h, emotion=emotion)

            if eye_detection:
                roi_gray  = gray[y:y+h, x:x+w]
                roi_color = frame[y:y+h, x:x+w]
                eyes = eye_cascade.detectMultiScale(roi_gray, EYE_SCALE_FACTOR, EYE_MIN_NEIGHBORS)
                for (ex, ey, ew, eh) in eyes:
                    cv2.rectangle(roi_color, (ex, ey), (ex+ew, ey+eh), (80, 180, 255), 1)
                    cv2.circle(roi_color, (ex+ew//2, ey+eh//2), 3, (80, 180, 255), -1)

        draw_hud(frame, face_count, show_emotion and DEEPFACE_AVAILABLE, eye_detection, sensitivity, fps)

        # If deepface not installed, show install hint
        if not DEEPFACE_AVAILABLE:
            cv2.putText(frame, "pip install deepface  to enable emotion detection",
                        (10, 60), FONT, 0.5, (0, 180, 255), 1, cv2.LINE_AA)

        cv2.imshow("Face Detection + Emotion — Real-Time", frame)

        key = cv2.waitKey(1) & 0xFF
        if key in (ord("q"), 27):
            break
        elif key == ord("m"):
            show_emotion = not show_emotion
            print(f"[INFO] Emotion display: {'ON' if show_emotion else 'OFF'}")
        elif key == ord("e"):
            eye_detection = not eye_detection
            print(f"[INFO] Eye detection: {'ON' if eye_detection else 'OFF'}")
        elif key == ord("s"):
            save_screenshot(frame, face_count)
        elif key in (ord("+"), ord("=")):
            sensitivity = min(sensitivity + 1, 8)
        elif key == ord("-"):
            sensitivity = max(sensitivity - 1, 1)

    if analyzer:
        analyzer.stop()
    cap.release()
    cv2.destroyAllWindows()
    print("[INFO] Stopped.")


if __name__ == "__main__":
    run()