import json
import os
import math

def calc_iou(b1, b2):
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

def nms_detections(detections, iou_thresh=0.30, contain_thresh=0.55):
    if not detections or len(detections) <= 1:
        return detections
    # Sort by confidence descending
    sorted_dets = sorted(detections, key=lambda d: d.get("confidence", 0.5), reverse=True)
    kept = []
    for d in sorted_dets:
        b1 = d["box"]
        overlap = False
        for k in kept:
            b2 = k["box"]
            iou, contain = calc_iou(b1, b2)
            if iou > iou_thresh or contain > contain_thresh:
                overlap = True
                break
        if not overlap:
            kept.append(d)
    return kept

def clean_analysis_file(filepath):
    if not os.path.exists(filepath):
        print(f"File not found: {filepath}")
        return
    
    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)
        
    print(f"Cleaning {filepath}: {len(data.get('frames', []))} frames")
    
    unique_ids = set()
    class_counts = {"Car": 0, "Truck": 0, "Bus": 0, "Motorcycle": 0}
    seen_classes = {}
    
    CLASS_PALETTE = {
        "Car": "#38bdf8",         # Sky Blue
        "Truck": "#ef4444",       # Coral Red
        "Bus": "#10b981",         # Emerald Green
        "Motorcycle": "#f59e0b"   # Amber Gold
    }
    
    for frame in data.get("frames", []):
        raw_dets = frame.get("detections", [])
        filtered_dets = nms_detections(raw_dets)
        
        cleaned_dets = []
        for d in filtered_dets:
            # Map any variant to standard 4 classes
            orig_cls = d.get("class", "Car")
            orig_type = d.get("type", "Car")
            
            # Map type to standard clean class
            if "Truck" in orig_cls or "Truck" in orig_type:
                clean_cls = "Truck"
            elif "Bus" in orig_cls or "Bus" in orig_type:
                clean_cls = "Bus"
            elif "Motorcycle" in orig_cls or "Motorcycle" in orig_type or "Moto" in orig_cls:
                clean_cls = "Motorcycle"
            else:
                clean_cls = "Car"
                
            track_id = d.get("track_id", 1)
            conf = d.get("confidence", 0.90)
            spd = d.get("speed_kmh", 45.0)
            color = CLASS_PALETTE.get(clean_cls, "#38bdf8")
            
            # Clean tag: NO CAR NAMES! Just: #ID Class Conf | Speed km/h
            clean_tag = f"#{track_id} {clean_cls} {conf} | {round(spd, 1)} km/h"
            
            cleaned_d = {
                "track_id": track_id,
                "class": clean_cls,
                "confidence": conf,
                "speed_kmh": round(spd, 1),
                "box": d.get("box", [0, 0, 50, 50]),
                "centroid": d.get("centroid", [25, 25]),
                "direction": d.get("direction", "Southbound"),
                "color": color,
                "tag": clean_tag
            }
            cleaned_dets.append(cleaned_d)
            
            if track_id not in seen_classes:
                seen_classes[track_id] = clean_cls
                class_counts[clean_cls] = class_counts.get(clean_cls, 0) + 1
                
        frame["detections"] = cleaned_dets
        frame["active_count"] = len(cleaned_dets)
        
    data["unique_total"] = len(seen_classes)
    data["unique_counts"] = class_counts
    data["category_counts"] = {
        "Cars": class_counts.get("Car", 0),
        "Trucks": class_counts.get("Truck", 0),
        "Buses": class_counts.get("Bus", 0),
        "Motorcycles": class_counts.get("Motorcycle", 0)
    }
    
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f)
        
    print(f"Cleaned {filepath}: unique total={len(seen_classes)}, counts={class_counts}")

if __name__ == "__main__":
    clean_analysis_file("d:/traffic/backend/data/13002160_1920_1080_60fps_analysis.json")
    clean_analysis_file("d:/traffic/backend/data/sample_traffic_analysis.json")

