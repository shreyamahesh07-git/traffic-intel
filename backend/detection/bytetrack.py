"""
ByteTrack Multi-Object Tracker for Traffic Intel.
Implements two-stage association (high-confidence + low-confidence recovery)
using IoU cost matrix and Hungarian linear sum assignment (scipy),
with constant-velocity bounding box prediction to prevent ID switches.
"""

from typing import List, Dict, Any, Tuple
import numpy as np
from scipy.optimize import linear_sum_assignment


def _iou_batch(bb_test: np.ndarray, bb_gt: np.ndarray) -> np.ndarray:
    """Computes pairwise IoU between two arrays of [x1, y1, x2, y2] boxes."""
    if len(bb_test) == 0 or len(bb_gt) == 0:
        return np.zeros((len(bb_test), len(bb_gt)), dtype=np.float32)

    bb_gt = np.expand_dims(bb_gt, 0)
    bb_test = np.expand_dims(bb_test, 1)

    xx1 = np.maximum(bb_test[..., 0], bb_gt[..., 0])
    yy1 = np.maximum(bb_test[..., 1], bb_gt[..., 1])
    xx2 = np.minimum(bb_test[..., 2], bb_gt[..., 2])
    yy2 = np.minimum(bb_test[..., 3], bb_gt[..., 3])
    w = np.maximum(0.0, xx2 - xx1)
    h = np.maximum(0.0, yy2 - yy1)
    inter = w * h

    area_test = (bb_test[..., 2] - bb_test[..., 0]) * (bb_test[..., 3] - bb_test[..., 1])
    area_gt = (bb_gt[..., 2] - bb_gt[..., 0]) * (bb_gt[..., 3] - bb_gt[..., 1])
    union = area_test + area_gt - inter
    return np.where(union > 0, inter / union, 0.0)


class ByteTrackObject:
    def __init__(self, track_id: int, box: List[float], cls_name: str, conf: float):
        self.track_id = track_id
        self.box = np.array(box, dtype=np.float32)  # [x1, y1, x2, y2]
        self.cls_name = cls_name
        self.conf = conf
        self.vx = 0.0
        self.vy = 0.0
        self.age = 1
        self.lost_frames = 0
        self.history: List[Tuple[float, float]] = [self.centroid()]
        self.counted = False
        self.direction = "Unknown"

    def centroid(self) -> Tuple[float, float]:
        return (
            float((self.box[0] + self.box[2]) * 0.5),
            float((self.box[1] + self.box[3]) * 0.5),
        )

    def predict(self) -> np.ndarray:
        """Predict next box using smoothed centroid velocity."""
        return np.array(
            [
                self.box[0] + self.vx,
                self.box[1] + self.vy,
                self.box[2] + self.vx,
                self.box[3] + self.vy,
            ],
            dtype=np.float32,
        )

    def update(self, new_box: List[float], cls_name: str, conf: float):
        old_cx, old_cy = self.centroid()
        nb = np.array(new_box, dtype=np.float32)
        new_cx = float((nb[0] + nb[2]) * 0.5)
        new_cy = float((nb[1] + nb[3]) * 0.5)

        dx = new_cx - old_cx
        dy = new_cy - old_cy
        self.vx = 0.6 * self.vx + 0.4 * dx
        self.vy = 0.6 * self.vy + 0.4 * dy

        if abs(dy) > 1.5:
            self.direction = "Inbound" if dy > 0 else "Outbound"
        elif abs(dx) > 1.5:
            self.direction = "Eastbound" if dx > 0 else "Westbound"

        self.box = nb
        if conf >= 0.45 or self.conf < 0.45:
            self.cls_name = cls_name
        self.conf = conf
        self.age += 1
        self.lost_frames = 0
        self.history.append((new_cx, new_cy))
        if len(self.history) > 25:
            self.history.pop(0)


class ByteTracker:
    """
    Two-stage ByteTrack multi-object tracker.
    Stage 1: High-confidence detections matched against active + lost tracks.
    Stage 2: Low-confidence detections matched against remaining active tracks.
    """

    def __init__(
        self,
        high_thresh: float = 0.42,
        low_thresh: float = 0.18,
        iou_thresh: float = 0.25,
        track_buffer: int = 24,
    ):
        self.high_thresh = high_thresh
        self.low_thresh = low_thresh
        self.iou_thresh = iou_thresh
        self.track_buffer = track_buffer
        self.next_id = 1
        self.tracks: Dict[int, ByteTrackObject] = {}

    def reset(self):
        self.next_id = 1
        self.tracks.clear()

    def _associate(
        self, track_ids: List[int], dets: List[Tuple[List[float], str, float]], iou_min: float
    ) -> Tuple[List[Tuple[int, int]], List[int], List[int]]:
        if not track_ids or not dets:
            return [], list(track_ids), list(range(len(dets)))

        pred_boxes = np.array([self.tracks[tid].predict() for tid in track_ids], dtype=np.float32)
        det_boxes = np.array([d[0] for d in dets], dtype=np.float32)
        iou_mat = _iou_batch(pred_boxes, det_boxes)
        cost_mat = 1.0 - iou_mat

        row_ind, col_ind = linear_sum_assignment(cost_mat)
        matches = []
        matched_t = set()
        matched_d = set()

        for r, c in zip(row_ind, col_ind):
            if iou_mat[r, c] >= iou_min:
                matches.append((track_ids[r], c))
                matched_t.add(track_ids[r])
                matched_d.add(c)

        unmatched_tracks = [tid for tid in track_ids if tid not in matched_t]
        unmatched_dets = [i for i in range(len(dets)) if i not in matched_d]
        return matches, unmatched_tracks, unmatched_dets

    def update(self, detections: List[Tuple[List[float], str, float]]) -> List[Dict[str, Any]]:
        """
        detections: list of ([x1, y1, x2, y2], class_name, confidence)
        Returns active visible tracks with stable IDs.
        """
        high_dets = [d for d in detections if d[2] >= self.high_thresh]
        low_dets = [d for d in detections if self.low_thresh <= d[2] < self.high_thresh]

        all_track_ids = list(self.tracks.keys())
        # Stage 1: High-confidence association
        matches_1, unmatched_t1, unmatched_d1 = self._associate(all_track_ids, high_dets, self.iou_thresh)
        for tid, det_idx in matches_1:
            box, cls_name, conf = high_dets[det_idx]
            self.tracks[tid].update(box, cls_name, conf)

        # Stage 2: Low-confidence recovery for remaining active tracks
        active_rem = [tid for tid in unmatched_t1 if self.tracks[tid].lost_frames <= 3]
        matches_2, unmatched_t2, _ = self._associate(active_rem, low_dets, max(0.15, self.iou_thresh - 0.05))
        matched_stage2 = set()
        for tid, det_idx in matches_2:
            box, cls_name, conf = low_dets[det_idx]
            self.tracks[tid].update(box, cls_name, conf)
            matched_stage2.add(tid)

        # Age unmatched tracks
        for tid in unmatched_t1:
            if tid not in matched_stage2:
                self.tracks[tid].lost_frames += 1

        # Remove expired tracks
        for tid in list(self.tracks.keys()):
            if self.tracks[tid].lost_frames > self.track_buffer:
                del self.tracks[tid]

        # Initialize new tracks from unmatched high-confidence detections
        for det_idx in unmatched_d1:
            box, cls_name, conf = high_dets[det_idx]
            tid = self.next_id
            self.next_id += 1
            self.tracks[tid] = ByteTrackObject(tid, box, cls_name, conf)

        # Return currently visible tracks
        visible = []
        for tid, trk in self.tracks.items():
            if trk.lost_frames == 0:
                cx, cy = trk.centroid()
                vel_px = float(np.hypot(trk.vx, trk.vy))
                visible.append({
                    "id": tid,
                    "box": [int(v) for v in trk.box.tolist()],
                    "centroid": [int(cx), int(cy)],
                    "class": trk.cls_name,
                    "confidence": round(float(trk.conf), 2),
                    "direction": trk.direction,
                    "vel_px_frame": round(vel_px, 2),
                    "age": trk.age,
                    "track_obj": trk,
                })
        return visible
