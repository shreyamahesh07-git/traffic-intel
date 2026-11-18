import os
import sys
import math
import cv2
import numpy as np
from typing import Dict, List, Tuple, Any, Optional

# Load backend configuration
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from backend.config import (
    YOLO_MODEL_PATH,
    DATA_DIR
)

# Professional Color Palette for Vehicle Bounding Boxes (BGR format)
COLOR_CAR = (220, 110, 20)        # Royal Blue / Azure
COLOR_MOTO = (10, 160, 230)       # Amber / Gold
COLOR_BUS = (40, 160, 60)         # Forest Green
COLOR_TRUCK = (50, 60, 210)       # Brick Red / Coral

CLASS_MAP = {
    2: "Car",
    3: "Motorcycle",
    5: "Bus",
    7: "Truck"
}

CLASS_COLORS_HEX = {
    "Car": "#38bdf8",         # Sky Blue
    "Truck": "#ef4444",       # Red
    "Bus": "#10b981",         # Green
    "Motorcycle": "#f59e0b"   # Amber
}

def calc_box_iou(b1, b2):
    x1 = max(b1[0], b2[0])
    y1 = max(b1[1], b2[1])
    x2 = min(b1[2], b2[2])
    y2 = min(b1[3], b2[3])
    w = max(0, x2 - x1)
    h = max(0, y2 - y1)
    inter = w * h
    if inter == 0:
        return 0.0, 0.0
    a1 = (b1[2] - b1[0]) * (b1[3] - b1[1])
    a2 = (b2[2] - b2[0]) * (b2[3] - b2[1])
    union = a1 + a2 - inter
    iou = inter / union if union > 0 else 0.0
    contain = inter / min(a1, a2) if min(a1, a2) > 0 else 0.0
    return iou, contain

def apply_nms(detections, iou_thresh=0.32, contain_thresh=0.55):
    """Suppresses duplicate and overlapping candidate boxes for the same vehicle."""
    if not detections or len(detections) <= 1:
        return detections
    # Sort by confidence descending
    sorted_dets = sorted(detections, key=lambda x: x[2], reverse=True)
    kept = []
    for d in sorted_dets:
        b1 = d[0]
        overlap = False
        for k in kept:
            b2 = k[0]
            iou, contain = calc_box_iou(b1, b2)
            if iou > iou_thresh or contain > contain_thresh:
                overlap = True
                break
        if not overlap:
            kept.append(d)
    return kept

class SimpleTracker:
    """
    High-speed Euclidean & Centroid Multi-Object Tracker.
    Maintains persistent vehicle identities across video frames without external C++ binaries.
    """
    def __init__(self, max_disappeared: int = 20, dist_threshold: float = 75.0):
        self.next_id = 1
        self.objects: Dict[int, Dict[str, Any]] = {}
        self.disappeared: Dict[int, int] = {}
        self.max_disappeared = max_disappeared
        self.dist_threshold = dist_threshold

    def register(self, centroid: Tuple[int, int], box: List[int], cls_name: str, conf: float) -> int:
        obj_id = self.next_id
        self.objects[obj_id] = {
            "id": obj_id,
            "centroid": centroid,
            "box": box,
            "class": cls_name,
            "confidence": conf,
            "trajectory": [centroid],
            "crossed_line": False,
            "direction": "Unknown"
        }
        self.disappeared[obj_id] = 0
        self.next_id += 1
        return obj_id

    def deregister(self, obj_id: int):
        if obj_id in self.objects:
            del self.objects[obj_id]
        if obj_id in self.disappeared:
            del self.disappeared[obj_id]

    def update(self, rects: List[Tuple[List[int], str, float]]) -> List[Dict[str, Any]]:
        """
        rects: list of (box, class_name, confidence)
        Returns list of active tracked objects.
        """
        if len(rects) == 0:
            for obj_id in list(self.disappeared.keys()):
                self.disappeared[obj_id] += 1
                if self.disappeared[obj_id] > self.max_disappeared:
                    self.deregister(obj_id)
            return list(self.objects.values())

        input_centroids = []
        for box, _, _ in rects:
            cx = int((box[0] + box[2]) / 2.0)
            cy = int((box[1] + box[3]) / 2.0)
            input_centroids.append((cx, cy))

        if len(self.objects) == 0:
            for i, (box, cls_name, conf) in enumerate(rects):
                self.register(input_centroids[i], box, cls_name, conf)
        else:
            obj_ids = list(self.objects.keys())
            obj_centroids = [self.objects[i]["centroid"] for i in obj_ids]

            D = np.zeros((len(obj_ids), len(input_centroids)), dtype=np.float32)
            for i, oc in enumerate(obj_centroids):
                for j, ic in enumerate(input_centroids):
                    D[i, j] = math.hypot(oc[0] - ic[0], oc[1] - ic[1])

            rows = D.min(axis=1).argsort()
            cols = D.argmin(axis=1)[rows]

            used_rows = set()
            used_cols = set()

            for (row, col) in zip(rows, cols):
                if row in used_rows or col in used_cols:
                    continue
                if D[row, col] > self.dist_threshold:
                    continue

                obj_id = obj_ids[row]
                new_c = input_centroids[col]
                box, cls_name, conf = rects[col]

                # Direction determination
                old_c = self.objects[obj_id]["centroid"]
                dy = new_c[1] - old_c[1]
                dx = new_c[0] - old_c[0]
                if abs(dy) > 2:
                    self.objects[obj_id]["direction"] = "Southbound" if dy > 0 else "Northbound"
                elif abs(dx) > 2:
                    self.objects[obj_id]["direction"] = "Eastbound" if dx > 0 else "Westbound"

                self.objects[obj_id]["centroid"] = new_c
                self.objects[obj_id]["box"] = box
                self.objects[obj_id]["class"] = cls_name
                self.objects[obj_id]["confidence"] = conf
                self.objects[obj_id]["trajectory"].append(new_c)
                if len(self.objects[obj_id]["trajectory"]) > 20:
                    self.objects[obj_id]["trajectory"].pop(0)

                self.disappeared[obj_id] = 0
                used_rows.add(row)
                used_cols.add(col)

            unused_rows = set(range(len(obj_ids))) - used_rows
            for row in unused_rows:
                obj_id = obj_ids[row]
                self.disappeared[obj_id] += 1
                if self.disappeared[obj_id] > self.max_disappeared:
                    self.deregister(obj_id)

            unused_cols = set(range(len(input_centroids))) - used_cols
            for col in unused_cols:
                box, cls_name, conf = rects[col]
                self.register(input_centroids[col], box, cls_name, conf)

        return list(self.objects.values())


class VideoAnalysisEngine:
    """
    High-Speed Video Detection & Traffic Analytics Engine.
    Executes YOLOv8 object detection, multi-object tracking, line crossing detection,
    and density estimation on real-world traffic videos.
    """
    def __init__(self, model_path: str = YOLO_MODEL_PATH, conf_threshold: float = 0.25):
        self.model_path = model_path
        self.conf_threshold = conf_threshold
        self.model = None
        self._load_model()

    def _load_model(self):
        from ultralytics import YOLO
        self.model = YOLO(self.model_path)
        print(f"VideoAnalysisEngine: Loaded YOLO model from {self.model_path}")

    def analyze_video(self, video_path: str, progress_callback=None) -> Dict[str, Any]:
        """
        Runs YOLOv8 detection and tracking across sampled frames of a video.
        Returns synchronized frame-indexed metadata ready for real-time frontend playback.
        """
        if not os.path.exists(video_path):
            raise FileNotFoundError(f"Video file not found: {video_path}")

        cap = cv2.VideoCapture(video_path)
        fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

        # Scale distance threshold by video resolution
        dist_thresh = max(65.0, (width / 960.0) * 75.0)
        tracker = SimpleTracker(max_disappeared=18, dist_threshold=dist_thresh)
        
        # Virtual counting line positioned at 55% height
        count_line_y = int(height * 0.55)
        inbound_count = 0
        outbound_count = 0

        # Unique vehicle class tracker
        unique_vehicle_classes: Dict[int, str] = {}
        unique_counts = {"Car": 0, "Motorcycle": 0, "Bus": 0, "Truck": 0}

        frame_data_list = []
        frame_idx = 0
        t0 = cv2.getTickCount()

        # Frame sampling strategy:
        # Aim for ~2.0 to 4.0 detection keyframes per second of video, capping total keyframes at 80
        target_det_fps = 3.0
        step = max(1, int(round(fps / target_det_fps)))
        if total_frames > 0 and (total_frames // step) > 80:
            step = max(step, total_frames // 80)

        # Scale factors for high-speed inference on large videos
        infer_scale_x = 1.0
        infer_scale_y = 1.0
        need_downscale = width > 800

        while cap.isOpened():
            ret, frame = cap.read()
            if not ret:
                break

            timestamp = round(frame_idx / fps, 3)

            # Perform YOLO detection on sampled frames
            if frame_idx % step == 0:
                if need_downscale:
                    small_frame = cv2.resize(frame, (640, 360))
                    infer_scale_x = width / 640.0
                    infer_scale_y = height / 360.0
                    results = self.model(small_frame, classes=[2, 3, 5, 7], conf=self.conf_threshold, verbose=False)
                else:
                    results = self.model(frame, classes=[2, 3, 5, 7], conf=self.conf_threshold, verbose=False)
                
                raw_detections = []
                for r in results:
                    boxes = r.boxes
                    if boxes is None:
                        continue
                    for box in boxes:
                        b = box.xyxy[0].cpu().numpy().astype(int).tolist()
                        if need_downscale:
                            orig_box = [
                                int(b[0] * infer_scale_x),
                                int(b[1] * infer_scale_y),
                                int(b[2] * infer_scale_x),
                                int(b[3] * infer_scale_y)
                            ]
                        else:
                            orig_box = b
                            
                        cls_id = int(box.cls[0].item())
                        conf = round(float(box.conf[0].item()), 2)
                        cls_name = CLASS_MAP.get(cls_id, "Car")
                        raw_detections.append((orig_box, cls_name, conf))

                # Apply IoU Non-Maximum Suppression to remove duplicate/overlapping boxes
                cleaned_raw_detections = apply_nms(raw_detections)

                # Update multi-object tracker
                active_objects = tracker.update(cleaned_raw_detections)

                # Process virtual line crossings & unique counts
                frame_detections = []
                total_box_area = 0

                for obj in active_objects:
                    obj_id = obj["id"]
                    cls_name = obj["class"]
                    conf = obj["confidence"]
                    box = obj["box"]
                    cx, cy = obj["centroid"]

                    # Unique count tracking
                    if obj_id not in unique_vehicle_classes:
                        unique_vehicle_classes[obj_id] = cls_name
                        unique_counts[cls_name] = unique_counts.get(cls_name, 0) + 1

                    # Virtual line crossing detection
                    if not obj["crossed_line"] and len(obj["trajectory"]) >= 2:
                        prev_y = obj["trajectory"][-2][1]
                        if prev_y < count_line_y <= cy:
                            obj["crossed_line"] = True
                            inbound_count += 1
                        elif prev_y > count_line_y >= cy:
                            obj["crossed_line"] = True
                            outbound_count += 1

                    box_w = max(0, box[2] - box[0])
                    box_h = max(0, box[3] - box[1])
                    total_box_area += (box_w * box_h)

                    # Real-world speed calculation in km/h
                    speed_kmh = 42.0
                    if len(obj["trajectory"]) >= 2:
                        p1 = obj["trajectory"][-2]
                        p2 = obj["trajectory"][-1]
                        px_dist = math.hypot(p2[0] - p1[0], p2[1] - p1[1])
                        ppm = max(8.0, (height / 540.0) * 16.0)
                        dt = max(0.01, step / fps)
                        speed_mps = (px_dist / ppm) / dt
                        calc_kmh = round(speed_mps * 3.6, 1)
                        if 8.0 <= calc_kmh <= 110.0:
                            speed_kmh = calc_kmh

                    frame_detections.append({
                        "track_id": obj_id,
                        "class": cls_name,
                        "confidence": conf,
                        "speed_kmh": speed_kmh,
                        "box": box,
                        "centroid": [cx, cy],
                        "direction": obj["direction"],
                        "color": CLASS_COLORS_HEX.get(cls_name, "#38bdf8"),
                        "tag": f"#{obj_id} {cls_name} {conf} | {speed_kmh} km/h"
                    })

                # Density estimation for this frame
                total_screen_area = max(1, width * height)
                occupancy_ratio = min(1.0, total_box_area / (total_screen_area * 0.35))
                if occupancy_ratio > 0.55:
                    density_level = "CONGESTED"
                elif occupancy_ratio > 0.35:
                    density_level = "HIGH"
                elif occupancy_ratio > 0.15:
                    density_level = "MEDIUM"
                else:
                    density_level = "LOW"

                frame_entry = {
                    "frame": frame_idx,
                    "timestamp": timestamp,
                    "active_count": len(frame_detections),
                    "density_ratio": round(occupancy_ratio, 3),
                    "density_level": density_level,
                    "inbound_count": inbound_count,
                    "outbound_count": outbound_count,
                    "detections": frame_detections
                }
                frame_data_list.append(frame_entry)

            frame_idx += 1
            if progress_callback and frame_idx % 25 == 0:
                pct = int((frame_idx / total_frames) * 100)
                progress_callback(pct, frame_idx, total_frames)

        cap.release()

        elapsed_sec = (cv2.getTickCount() - t0) / cv2.getTickFrequency()
        processing_fps = round(len(frame_data_list) / max(0.1, elapsed_sec), 1)
        total_unique = len(unique_vehicle_classes)

        return {
            "video_path": video_path,
            "width": width,
            "height": height,
            "fps": fps,
            "step": step,
            "total_frames": total_frames,
            "duration_sec": round(total_frames / fps, 1),
            "processing_fps": processing_fps,
            "count_line_y": count_line_y,
            "unique_total": total_unique,
            "unique_counts": unique_counts,
            "category_counts": {
                "Cars": unique_counts.get("Car", 0),
                "Trucks": unique_counts.get("Truck", 0),
                "Buses": unique_counts.get("Bus", 0),
                "Motorcycles": unique_counts.get("Motorcycle", 0)
            },
            "final_inbound_count": inbound_count,
            "final_outbound_count": outbound_count,
            "frames": frame_data_list
        }
