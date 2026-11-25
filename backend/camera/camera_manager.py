"""
Live Camera & Stream Manager for Traffic Intel.
Supports:
- Local Webcam (device index 0, 1, ...)
- RTSP / IP Camera Streams (credentials masked in all logs & responses)
- HTTP / MJPEG Streams
- Fallback Local/Sample Video Files for testing when no camera is attached

Pipeline: OpenCV -> YOLOv8 -> ByteTrack -> Traffic Analytics.
Manages explicit states: DISCONNECTED, CONNECTING, CONNECTED, PROCESSING, RECONNECTING, ERROR.
"""

import os
import re
import sys
import time
import threading
from typing import Dict, Any, Optional, List
from urllib.parse import urlparse

import cv2
import numpy as np
import httpx

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from backend.config import YOLO_MODEL_PATH, DATA_DIR
from backend.detection.detector import CLASS_MAP, apply_nms, COLOR_CAR, COLOR_BUS, COLOR_TRUCK, COLOR_MOTO
from backend.detection.bytetrack import ByteTracker

CALTRANS_D7_FEED = "https://cwwp2.dot.ca.gov/data/d7/cctv/cctvStatusD07.json"
CALTRANS_OFFICIAL_PAGE = "https://dot.ca.gov/caltrans-near-me/live-traffic-cameras"

VERIFIED_LIVE_CAMERAS: Dict[str, Dict[str, Any]] = {
    "CALTRANS_D7_25": {
        "id": "CALTRANS_D7_25",
        "index": "25",
        "name": "I-5 : (25) Meadowdale",
        "location": "Los Angeles County, CA (I-5 Highway)",
        "provider": "Caltrans District 7 (California Dept. of Transportation)",
        "source_webpage": CALTRANS_OFFICIAL_PAGE,
        "stream_type": "HLS (.m3u8)",
        "stream_url": "https://wzmedia.dot.ca.gov/D7/CCTV-25.stream/playlist.m3u8",
    },
    "CALTRANS_D7_17": {
        "id": "CALTRANS_D7_17",
        "index": "17",
        "name": "I-5 : (17) South of I-10",
        "location": "Los Angeles County, CA (I-5 / I-10 Interchange)",
        "provider": "Caltrans District 7 (California Dept. of Transportation)",
        "source_webpage": CALTRANS_OFFICIAL_PAGE,
        "stream_type": "HLS (.m3u8)",
        "stream_url": "https://wzmedia.dot.ca.gov/D7/CCTV-17.stream/playlist.m3u8",
    },
    "CALTRANS_D7_40": {
        "id": "CALTRANS_D7_40",
        "index": "40",
        "name": "I-5 : (40) North of Burbank Blvd",
        "location": "Burbank, Los Angeles County, CA (I-5)",
        "provider": "Caltrans District 7 (California Dept. of Transportation)",
        "source_webpage": CALTRANS_OFFICIAL_PAGE,
        "stream_type": "HLS (.m3u8)",
        "stream_url": "https://wzmedia.dot.ca.gov/D7/CCTV-40.stream/playlist.m3u8",
    },
    "CALTRANS_D7_196": {
        "id": "CALTRANS_D7_196",
        "index": "196",
        "name": "I-110 : (196) Avenue 26 Off Ramp",
        "location": "Los Angeles County, CA (I-110 Arroyo Seco)",
        "provider": "Caltrans District 7 (California Dept. of Transportation)",
        "source_webpage": CALTRANS_OFFICIAL_PAGE,
        "stream_type": "HLS (.m3u8)",
        "stream_url": "https://wzmedia.dot.ca.gov/D7/CCTV-196.stream/playlist.m3u8",
    },
}

CLASS_BGR = {
    "Car": COLOR_CAR,
    "Bus": COLOR_BUS,
    "Truck": COLOR_TRUCK,
    "Motorcycle": COLOR_MOTO,
}


def mask_stream_credentials(url: str) -> str:
    """Masks user:password in RTSP/HTTP URLs before logging or returning to frontend."""
    if not url:
        return ""
    if url.isdigit():
        return f"Webcam #{url}"
    try:
        parsed = urlparse(url)
        if parsed.username or parsed.password:
            host_part = parsed.hostname or ""
            if parsed.port:
                host_part += f":{parsed.port}"
            masked = f"{parsed.scheme}://***:***@{host_part}{parsed.path or ''}"
            if parsed.query:
                masked += f"?{parsed.query}"
            return masked
    except Exception:
        pass
    return re.sub(r"://([^:@/]+):([^@/]+)@", "://***:***@", url)


class LiveCameraManager:
    """
    Thread-safe live camera capture, YOLOv8 detection, ByteTrack tracking,
    and traffic flow analytics manager.
    """

    def __init__(self):
        self.lock = threading.RLock()
        self.state = "DISCONNECTED"  # DISCONNECTED, CONNECTING, CONNECTED, PROCESSING, RECONNECTING, ERROR
        self.error_message: Optional[str] = None
        self.source_type = "none"  # webcam, rtsp, http, video, none
        self.masked_source = ""
        self._raw_source: Optional[Any] = None

        self.cap: Optional[cv2.VideoCapture] = None
        self.worker_thread: Optional[threading.Thread] = None
        self.stop_event = threading.Event()
        self.session_id = 0

        self.model = None
        self.tracker = ByteTracker()

        # Frame & Analytics state
        self.latest_jpeg: Optional[bytes] = None
        self.frame_width = 0
        self.frame_height = 0
        self.fps_measured = 0.0
        self.line_y_ratio = 0.55

        self.unique_crossed_ids = set()
        self.inbound_count = 0
        self.outbound_count = 0
        self.class_totals = {"Car": 0, "Bus": 0, "Truck": 0, "Motorcycle": 0}
        self.unique_class_seen: Dict[int, str] = {}
        self.latest_analytics: Dict[str, Any] = self._empty_analytics()
        self.provenance: Dict[str, Any] = self._empty_provenance()

    def _empty_provenance(self) -> Dict[str, Any]:
        return {
            "camera_name": "—",
            "camera_location": "—",
            "provider": "—",
            "source_webpage": "",
            "stream_type": "—",
            "live_status_label": "Disconnected",
            "provider_timestamp": None,
            "last_frame_time": None,
        }

    def _empty_analytics(self) -> Dict[str, Any]:
        return {
            "source_label": "No camera connected",
            "active_detected": 0,
            "total_crossed": 0,
            "inbound_count": 0,
            "outbound_count": 0,
            "class_counts": {"Car": 0, "Bus": 0, "Truck": 0, "Motorcycle": 0},
            "unique_class_totals": {"Car": 0, "Bus": 0, "Truck": 0, "Motorcycle": 0},
            "lane_counts": {"Left": 0, "Center": 0, "Right": 0},
            "queue_estimate": 0,
            "density_level": "NONE",
            "avg_relative_speed_px_s": 0.0,
            "speed_calibrated": False,
            "estimated_arrival_rate_vph": 0,
            "fps": 0.0,
            "tracked_vehicles": [],
            "timestamp": time.time(),
        }

    def _ensure_model(self):
        if self.model is None:
            from ultralytics import YOLO
            self.model = YOLO(YOLO_MODEL_PATH)

    def _reset_analytics(self):
        self.tracker.reset()
        self.unique_crossed_ids.clear()
        self.inbound_count = 0
        self.outbound_count = 0
        self.class_totals = {"Car": 0, "Bus": 0, "Truck": 0, "Motorcycle": 0}
        self.unique_class_seen.clear()
        self.latest_jpeg = None
        self.latest_analytics = self._empty_analytics()
        self.provenance = self._empty_provenance()

    def _fetch_caltrans_live_meta(self, cam_index: str) -> Optional[Dict[str, Any]]:
        """Queries official Caltrans CWWP2 JSON feed for live status and recordTimestamp."""
        try:
            resp = httpx.get(CALTRANS_D7_FEED, timeout=5.0)
            if resp.status_code == 200:
                for item in resp.json().get("data", []):
                    c = item.get("cctv", {})
                    if str(c.get("index")) == str(cam_index):
                        ts = c.get("recordTimestamp", {})
                        return {
                            "in_service": c.get("inService") == "true",
                            "timestamp": f"{ts.get('recordDate', '')} {ts.get('recordTime', '')}".strip() or None,
                            "stream_url": c.get("imageData", {}).get("streamingVideoURL") or None,
                        }
        except Exception:
            pass
        return None

    def connect(self, source_type: str, source_value: str) -> Dict[str, Any]:
        """Connects to a webcam, RTSP/HTTP IP stream, or fallback video file."""
        self.disconnect()

        with self.lock:
            self.session_id += 1
            current_session = self.session_id
            self.source_type = source_type.lower()
            self.error_message = None
            self._reset_analytics()

            if self.source_type == "verified_live":
                cam_id = str(source_value).strip() or "CALTRANS_D7_25"
                cam_spec = VERIFIED_LIVE_CAMERAS.get(cam_id)
                if not cam_spec:
                    self.state = "ERROR"
                    self.error_message = f"Unknown verified camera ID: {cam_id}"
                    return self.get_status()
                meta = self._fetch_caltrans_live_meta(cam_spec["index"])
                if meta and not meta["in_service"]:
                    self.state = "ERROR"
                    self.error_message = f"{cam_spec['name']} is currently marked out-of-service by Caltrans."
                    return self.get_status()
                stream_url = (meta and meta.get("stream_url")) or cam_spec["stream_url"]
                self._raw_source = stream_url
                self.masked_source = cam_spec["name"]
                self.provenance = {
                    "camera_name": cam_spec["name"],
                    "camera_location": cam_spec["location"],
                    "provider": cam_spec["provider"],
                    "source_webpage": cam_spec["source_webpage"],
                    "stream_type": cam_spec["stream_type"],
                    "live_status_label": "Verified live source" if (meta and meta["in_service"]) else "Live status unverified",
                    "provider_timestamp": meta.get("timestamp") if meta else None,
                    "last_frame_time": None,
                }
            elif self.source_type == "webcam":
                try:
                    idx = int(source_value) if str(source_value).strip().isdigit() else 0
                except ValueError:
                    idx = 0
                self._raw_source = idx
                self.masked_source = f"Local Webcam #{idx}"
                self.provenance = {
                    "camera_name": self.masked_source,
                    "camera_location": "Local Computer",
                    "provider": "Browser MediaDevices",
                    "source_webpage": "",
                    "stream_type": "Local Webcam",
                    "live_status_label": "Verified live source",
                    "provider_timestamp": None,
                    "last_frame_time": None,
                }
            elif self.source_type in ("rtsp", "http"):
                url = str(source_value).strip()
                if not url:
                    self.state = "ERROR"
                    self.error_message = "Stream URL cannot be empty."
                    return self.get_status()
                self._raw_source = url
                self.masked_source = mask_stream_credentials(url)
                is_videodb_sample = "samples.rts.videodb.io" in url.lower()
                self.provenance = {
                    "camera_name": "VideoDB Traffic Sample" if is_videodb_sample else self.masked_source,
                    "camera_location": "Sample Stream (Unverified)" if is_videodb_sample else "Custom IP Stream",
                    "provider": "VideoDB Sample RTSP" if is_videodb_sample else "Custom Stream URL",
                    "source_webpage": "",
                    "stream_type": self.source_type.upper(),
                    "live_status_label": "RTSP Sample — Live Status Unverified" if is_videodb_sample else "Live status unverified",
                    "provider_timestamp": None,
                    "last_frame_time": None,
                }
            elif self.source_type == "video":
                fname = os.path.basename(str(source_value).strip() or "sample_traffic.mp4")
                candidate_paths = [
                    os.path.join(DATA_DIR, fname),
                    os.path.join(DATA_DIR, "uploads", fname),
                ]
                found = next((p for p in candidate_paths if os.path.exists(p)), None)
                if not found:
                    self.state = "ERROR"
                    self.error_message = f"Demo video '{fname}' not found."
                    return self.get_status()
                self._raw_source = found
                self.masked_source = f"Demo Video ({fname})"
                self.provenance = {
                    "camera_name": fname,
                    "camera_location": "Local Test File",
                    "provider": "Local Demo Video",
                    "source_webpage": "",
                    "stream_type": "Recorded MP4",
                    "live_status_label": "Recorded sample",
                    "provider_timestamp": None,
                    "last_frame_time": None,
                }
            else:
                self.state = "ERROR"
                self.error_message = f"Unsupported camera source type: {source_type}"
                return self.get_status()

            self.state = "CONNECTING"
            self.stop_event.clear()
            self.worker_thread = threading.Thread(
                target=self._capture_loop,
                args=(current_session,),
                daemon=True,
            )
            self.worker_thread.start()
            return self.get_status()

    def restart(self) -> Dict[str, Any]:
        with self.lock:
            st = self.source_type
            raw = self._raw_source
        if st == "none" or raw is None:
            return self.get_status()
        val = os.path.basename(raw) if st == "video" else str(raw)
        return self.connect(st, val)

    def disconnect(self) -> Dict[str, Any]:
        """Stops capture thread, releases VideoCapture, and clears stale frames."""
        with self.lock:
            self.session_id += 1
            self.stop_event.set()
            thread_ref = self.worker_thread
            self.worker_thread = None

        if thread_ref and thread_ref.is_alive() and thread_ref != threading.current_thread():
            thread_ref.join(timeout=2.5)

        with self.lock:
            if self.cap is not None:
                try:
                    self.cap.release()
                except Exception:
                    pass
                self.cap = None
            self.state = "DISCONNECTED"
            self.error_message = None
            self.source_type = "none"
            self.masked_source = ""
            self._raw_source = None
            self._reset_analytics()
            return self.get_status()

    def _open_capture(self) -> Optional[cv2.VideoCapture]:
        src = self._raw_source
        if self.source_type in ("rtsp", "http"):
            import socket
            parsed = urlparse(str(src))
            host = parsed.hostname
            port = parsed.port or (554 if self.source_type == "rtsp" else 80)
            if not host:
                return None
            try:
                with socket.create_connection((host, port), timeout=2.5):
                    pass
            except Exception:
                return None
        if self.source_type == "webcam":
            cap = cv2.VideoCapture(int(src), cv2.CAP_DSHOW) if os.name == "nt" else cv2.VideoCapture(int(src))
        else:
            cap = cv2.VideoCapture(src)
        if cap is not None and cap.isOpened():
            return cap
        if cap is not None:
            cap.release()
        return None

    def _capture_loop(self, session_id: int):
        cap = self._open_capture()
        if cap is None:
            with self.lock:
                if self.session_id == session_id:
                    self.state = "ERROR"
                    self.error_message = "Unable to connect to the selected camera. Check the camera permissions or stream URL."
            return

        # Verify that actual frames can be read before reporting CONNECTED
        first_ret, first_frame = cap.read()
        if not first_ret or first_frame is None:
            cap.release()
            with self.lock:
                if self.session_id == session_id:
                    self.state = "ERROR"
                    self.error_message = "Camera stream opened, but no video frames were received. Verify stream URL or credentials."
            return

        try:
            self._ensure_model()
        except Exception as e:
            cap.release()
            with self.lock:
                if self.session_id == session_id:
                    self.state = "ERROR"
                    self.error_message = f"Failed to load YOLOv8 model: {e}"
            return

        with self.lock:
            if self.session_id != session_id or self.stop_event.is_set():
                cap.release()
                return
            self.cap = cap
            self.state = "CONNECTED"
            self.frame_width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)) or first_frame.shape[1]
            self.frame_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) or first_frame.shape[0]

        reconnect_attempts = 0
        prev_t = time.time()
        fps_smooth = 0.0
        start_time = time.time()

        while not self.stop_event.is_set():
            with self.lock:
                if self.session_id != session_id:
                    break

            ret, frame = cap.read()
            if not ret or frame is None:
                if self.source_type == "video":
                    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                    continue
                reconnect_attempts += 1
                with self.lock:
                    if self.session_id == session_id:
                        self.state = "RECONNECTING"
                        self.latest_jpeg = None
                if reconnect_attempts > 5:
                    with self.lock:
                        if self.session_id == session_id:
                            self.state = "ERROR"
                            self.error_message = f"Lost connection to {self.masked_source} after retries."
                    break
                cap.release()
                time.sleep(1.0)
                cap = self._open_capture()
                if cap is None:
                    continue
                with self.lock:
                    self.cap = cap
                    self.state = "CONNECTED"
                continue

            reconnect_attempts = 0
            # Resize overly large 4K streams for smooth real-time processing
            h, w = frame.shape[:2]
            if w > 960:
                scale = 960.0 / w
                frame = cv2.resize(frame, (960, int(h * scale)))
                h, w = frame.shape[:2]

            # YOLOv8 detection (low conf threshold so ByteTrack stage-2 can recover occlusions)
            results = self.model.predict(
                frame,
                conf=0.18,
                iou=0.45,
                classes=[2, 3, 5, 7],
                verbose=False,
            )
            raw_dets = []
            if results and len(results[0].boxes) > 0:
                for box in results[0].boxes:
                    cls_id = int(box.cls[0].item())
                    conf = float(box.conf[0].item())
                    x1, y1, x2, y2 = [float(v) for v in box.xyxy[0].tolist()]
                    if (x2 - x1) < 12 or (y2 - y1) < 12:
                        continue
                    cls_name = CLASS_MAP.get(cls_id, "Car")
                    raw_dets.append(([x1, y1, x2, y2], cls_name, conf))

            raw_dets = apply_nms(raw_dets, iou_thresh=0.35, contain_thresh=0.55)
            tracks = self.tracker.update(raw_dets)

            # Compute Analytics & Annotate Frame
            line_y = int(h * self.line_y_ratio)
            lane1_x = int(w * 0.33)
            lane2_x = int(w * 0.66)

            active_classes = {"Car": 0, "Bus": 0, "Truck": 0, "Motorcycle": 0}
            lane_counts = {"Left": 0, "Center": 0, "Right": 0}
            queued_cnt = 0
            vel_list = []
            tracked_summary = []

            # Draw lane dividers and virtual counting line
            cv2.line(frame, (lane1_x, int(h * 0.2)), (lane1_x, h), (180, 180, 180), 1, cv2.LINE_AA)
            cv2.line(frame, (lane2_x, int(h * 0.2)), (lane2_x, h), (180, 180, 180), 1, cv2.LINE_AA)
            cv2.line(frame, (0, line_y), (w, line_y), (14, 165, 233), 2, cv2.LINE_AA)
            cv2.putText(frame, "COUNTING LINE", (12, line_y - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.48, (14, 165, 233), 1, cv2.LINE_AA)

            for trk in tracks:
                tid = trk["id"]
                cls_name = trk["class"]
                conf = trk["confidence"]
                x1, y1, x2, y2 = trk["box"]
                cx, cy = trk["centroid"]
                vel_px = trk["vel_px_frame"]

                active_classes[cls_name] = active_classes.get(cls_name, 0) + 1
                if tid not in self.unique_class_seen:
                    self.unique_class_seen[tid] = cls_name
                    self.class_totals[cls_name] = self.class_totals.get(cls_name, 0) + 1

                if cx < lane1_x:
                    lane_counts["Left"] += 1
                    lane_name = "Left"
                elif cx < lane2_x:
                    lane_counts["Center"] += 1
                    lane_name = "Center"
                else:
                    lane_counts["Right"] += 1
                    lane_name = "Right"

                if vel_px < 1.0:
                    queued_cnt += 1
                vel_list.append(vel_px)

                # Virtual line crossing (deduplicated via track ID)
                t_obj = trk["track_obj"]
                if not t_obj.counted and len(t_obj.history) >= 2:
                    prev_y = t_obj.history[-2][1]
                    if (prev_y < line_y <= cy) or (prev_y > line_y >= cy):
                        t_obj.counted = True
                        self.unique_crossed_ids.add(tid)
                        if cy >= prev_y:
                            self.inbound_count += 1
                        else:
                            self.outbound_count += 1

                color = CLASS_BGR.get(cls_name, COLOR_CAR)
                cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
                label = f"#{tid} {cls_name} {int(conf * 100)}%"
                (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.45, 1)
                cv2.rectangle(frame, (x1, max(0, y1 - th - 6)), (x1 + tw + 6, y1), color, -1)
                cv2.putText(frame, label, (x1 + 3, max(th, y1 - 4)), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 1, cv2.LINE_AA)

                tracked_summary.append({
                    "id": tid,
                    "class": cls_name,
                    "confidence": conf,
                    "lane": lane_name,
                    "direction": trk["direction"],
                })

            now = time.time()
            dt = max(0.001, now - prev_t)
            prev_t = now
            inst_fps = 1.0 / dt
            fps_smooth = inst_fps if fps_smooth == 0.0 else (0.85 * fps_smooth + 0.15 * inst_fps)

            elapsed_min = max(0.05, (now - start_time) / 60.0)
            est_vph = int((len(self.unique_crossed_ids) / elapsed_min) * 60.0) if self.unique_crossed_ids else len(tracks) * 30

            active_cnt = len(tracks)
            density = "NONE" if active_cnt == 0 else ("LOW" if active_cnt <= 5 else ("MODERATE" if active_cnt <= 14 else "HIGH"))
            avg_px_s = round((sum(vel_list) / len(vel_list)) * fps_smooth, 1) if vel_list else 0.0

            ok, jpg = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 82])
            if ok:
                with self.lock:
                    if self.session_id != session_id:
                        break
                    self.state = "PROCESSING"
                    self.fps_measured = round(fps_smooth, 1)
                    self.latest_jpeg = jpg.tobytes()
                    self.provenance["last_frame_time"] = time.strftime("%H:%M:%S")
                    self.latest_analytics = {
                        "source_label": self.masked_source,
                        "active_detected": active_cnt,
                        "total_crossed": len(self.unique_crossed_ids),
                        "inbound_count": self.inbound_count,
                        "outbound_count": self.outbound_count,
                        "class_counts": active_classes,
                        "unique_class_totals": dict(self.class_totals),
                        "lane_counts": lane_counts,
                        "queue_estimate": queued_cnt,
                        "density_level": density,
                        "avg_relative_speed_px_s": avg_px_s,
                        "speed_calibrated": False,
                        "estimated_arrival_rate_vph": min(2400, est_vph),
                        "fps": self.fps_measured,
                        "tracked_vehicles": tracked_summary[:30],
                        "timestamp": now,
                    }

            if self.source_type == "video":
                time.sleep(0.04)

        try:
            cap.release()
        except Exception:
            pass

    def get_latest_frame(self) -> Optional[bytes]:
        with self.lock:
            if self.state in ("DISCONNECTED", "ERROR"):
                return None
            return self.latest_jpeg

    def start_webcam_session(self, device_label: str = "Browser Local Webcam"):
        """Initializes a browser MediaDevices webcam session (stops any prior backend stream)."""
        self.disconnect()
        with self.lock:
            self.session_id += 1
            self.source_type = "webcam"
            self.masked_source = device_label or "Browser Local Webcam"
            self.state = "CONNECTED"
            self.error_message = None
            self._reset_analytics()
        self._ensure_model()

    def process_webcam_frame(self, jpeg_bytes: bytes) -> Dict[str, Any]:
        """
        Decodes a single JPEG frame from browser MediaDevices webcam,
        runs OpenCV -> YOLOv8 -> ByteTrack -> Traffic Analytics,
        and returns bounding boxes + analytics for canvas overlay.
        """
        self._ensure_model()
        arr = np.frombuffer(jpeg_bytes, dtype=np.uint8)
        frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if frame is None:
            return {"boxes": [], "analytics": self.latest_analytics}

        h, w = frame.shape[:2]
        if w > 800:
            scale = 800.0 / w
            frame = cv2.resize(frame, (800, int(h * scale)))
            h, w = frame.shape[:2]

        results = self.model.predict(
            frame,
            conf=0.20,
            iou=0.45,
            classes=[2, 3, 5, 7],
            verbose=False,
        )
        raw_dets = []
        if results and len(results[0].boxes) > 0:
            for box in results[0].boxes:
                cls_id = int(box.cls[0].item())
                conf = float(box.conf[0].item())
                x1, y1, x2, y2 = [float(v) for v in box.xyxy[0].tolist()]
                if (x2 - x1) < 12 or (y2 - y1) < 12:
                    continue
                cls_name = CLASS_MAP.get(cls_id, "Car")
                raw_dets.append(([x1, y1, x2, y2], cls_name, conf))

        raw_dets = apply_nms(raw_dets, iou_thresh=0.35, contain_thresh=0.55)
        tracks = self.tracker.update(raw_dets)

        line_y = int(h * self.line_y_ratio)
        lane1_x = int(w * 0.33)
        lane2_x = int(w * 0.66)

        active_classes = {"Car": 0, "Bus": 0, "Truck": 0, "Motorcycle": 0}
        lane_counts = {"Left": 0, "Center": 0, "Right": 0}
        queued_cnt = 0
        vel_list = []
        boxes_out = []

        for trk in tracks:
            tid = trk["id"]
            cls_name = trk["class"]
            conf = trk["confidence"]
            x1, y1, x2, y2 = trk["box"]
            cx, cy = trk["centroid"]
            vel_px = trk["vel_px_frame"]

            active_classes[cls_name] = active_classes.get(cls_name, 0) + 1
            if tid not in self.unique_class_seen:
                self.unique_class_seen[tid] = cls_name
                self.class_totals[cls_name] = self.class_totals.get(cls_name, 0) + 1

            if cx < lane1_x:
                lane_counts["Left"] += 1
            elif cx < lane2_x:
                lane_counts["Center"] += 1
            else:
                lane_counts["Right"] += 1

            if vel_px < 1.0:
                queued_cnt += 1
            vel_list.append(vel_px)

            t_obj = trk["track_obj"]
            if not t_obj.counted and len(t_obj.history) >= 2:
                prev_y = t_obj.history[-2][1]
                if (prev_y < line_y <= cy) or (prev_y > line_y >= cy):
                    t_obj.counted = True
                    self.unique_crossed_ids.add(tid)
                    if cy >= prev_y:
                        self.inbound_count += 1
                    else:
                        self.outbound_count += 1

            boxes_out.append({
                "id": tid,
                "class": cls_name,
                "confidence": conf,
                "nx1": round(x1 / w, 4),
                "ny1": round(y1 / h, 4),
                "nx2": round(x2 / w, 4),
                "ny2": round(y2 / h, 4),
            })

        now = time.time()
        active_cnt = len(tracks)
        density = "NONE" if active_cnt == 0 else ("LOW" if active_cnt <= 5 else ("MODERATE" if active_cnt <= 14 else "HIGH"))
        avg_px_s = round((sum(vel_list) / len(vel_list)) * 12.0, 1) if vel_list else 0.0

        with self.lock:
            self.state = "PROCESSING"
            self.fps_measured = 12.0
            self.latest_analytics = {
                "source_label": self.masked_source,
                "active_detected": active_cnt,
                "total_crossed": len(self.unique_crossed_ids),
                "inbound_count": self.inbound_count,
                "outbound_count": self.outbound_count,
                "class_counts": active_classes,
                "unique_class_totals": dict(self.class_totals),
                "lane_counts": lane_counts,
                "queue_estimate": queued_cnt,
                "density_level": density,
                "avg_relative_speed_px_s": avg_px_s,
                "speed_calibrated": False,
                "estimated_arrival_rate_vph": min(2400, active_cnt * 30),
                "fps": 12.0,
                "timestamp": now,
            }
            return {
                "boxes": boxes_out,
                "line_y_ratio": self.line_y_ratio,
                "analytics": self.latest_analytics,
            }

    def get_status(self) -> Dict[str, Any]:
        with self.lock:
            return {
                "state": self.state,
                "source_type": self.source_type,
                "source_label": self.masked_source,
                "error": self.error_message,
                "fps": self.fps_measured,
                "provenance": dict(self.provenance),
                "analytics": self.latest_analytics if self.state in ("CONNECTED", "PROCESSING") else self._empty_analytics(),
            }
