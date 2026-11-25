"""
Traffic Intel Backend API Server (FastAPI).
Manages:
- Coordinated Multi-Intersection SUMO Simulation & Adaptive DQN Control
- Live Camera / RTSP / Webcam YOLOv8 + ByteTrack Analytics
- External Traffic Data Provider Adapter (TomTom / HERE)
- Real-Traffic-to-SUMO Controlled Demand Bridge
- Fixed-Time vs Adaptive DQN Comparison Analytics
"""

import os
import sys
import time
import json
import shutil
import asyncio
import threading
from contextlib import asynccontextmanager
from typing import Dict, Any, Optional, List

from fastapi import FastAPI, UploadFile, File, Form, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse, FileResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from backend.config import (
    FRONTEND_DIR,
    DATA_DIR,
    YOLO_MODEL_PATH,
)
from backend.simulation.city_runner import CitySimulationRunner, CAMERA_ZONES
from backend.controllers.multi_junction_fixed import MultiJunctionFixedController
from backend.controllers.adaptive_city_controller import AdaptiveCityController, CENTRAL_CORRIDORS
from backend.detection.detector import VideoAnalysisEngine
from backend.camera.camera_manager import LiveCameraManager, VERIFIED_LIVE_CAMERAS
from backend.traffic_provider.provider import TrafficDataProvider
from backend.evaluation.live_comparator import run_controlled_comparison


class EventLog:
    """Thread-safe ring buffer of real system events (no fabricated entries)."""

    def __init__(self, maxlen: int = 40):
        self._lock = threading.Lock()
        self._events: List[Dict[str, Any]] = []
        self._maxlen = maxlen

    def add(self, category: str, message: str, level: str = "info"):
        with self._lock:
            self._events.insert(0, {
                "timestamp": time.strftime("%H:%M:%S"),
                "epoch": time.time(),
                "category": category,
                "level": level,
                "message": message,
            })
            if len(self._events) > self._maxlen:
                self._events.pop()

    def list(self, limit: int = 15) -> List[Dict[str, Any]]:
        with self._lock:
            return list(self._events[:limit])


event_log = EventLog()


class SimulationManager:
    def __init__(self):
        self.lock = threading.RLock()
        self.is_running = False
        self.is_paused = False
        self.controller_mode = "AI_ADAPTIVE"  # "AI_ADAPTIVE", "GREEN_WAVE", "FIXED_TIME", "MANUAL"
        self.active_camera = "CITY_OVERVIEW"
        self.base_step_delay = 0.25
        self.step_delay = 0.25
        self.speed_multiplier = 1.0
        self.traffic_scale = 1.0

        self.city_runner: Optional[CitySimulationRunner] = None
        self.fixed_controller = MultiJunctionFixedController()
        self.adaptive_controller = AdaptiveCityController()

        self.latest_telemetry: Dict[str, Any] = {}
        self.worker_thread: Optional[threading.Thread] = None
        self.stop_signal = False
        self.last_error: Optional[str] = None

    def start_simulation(self):
        with self.lock:
            if self.is_running:
                self.is_paused = False
                event_log.add("Simulation", "Resumed SUMO simulation.")
                return

            try:
                if self.city_runner is None:
                    self.city_runner = CitySimulationRunner(use_gui=False)
                self.city_runner.start()
                self.last_error = None
            except Exception as e:
                self.last_error = str(e)
                event_log.add("Simulation", f"Failed to start SUMO: {e}", level="error")
                print(f"SimulationManager: Could not start City runner: {e}")
                return

            self.fixed_controller.reset()
            self.adaptive_controller.reset()
            self.is_running = True
            self.is_paused = False
            self.stop_signal = False
            event_log.add("Simulation", f"Started SUMO simulation ({self.controller_mode}).")

            if self.worker_thread is None or not self.worker_thread.is_alive():
                self.worker_thread = threading.Thread(target=self._run_loop, daemon=True)
                self.worker_thread.start()

    def pause_simulation(self):
        with self.lock:
            self.is_paused = True
            event_log.add("Simulation", "Paused SUMO simulation.")

    def stop_simulation(self):
        with self.lock:
            self.stop_signal = True
            self.is_running = False
            self.is_paused = False
            if self.city_runner:
                try:
                    self.city_runner.stop()
                except Exception as e:
                    print(f"SimulationManager stop error: {e}")
            self.latest_telemetry = {}
            event_log.add("Simulation", "Stopped SUMO simulation and released TraCI.")

    def reset_simulation(self):
        with self.lock:
            was_running = self.is_running
            self.is_paused = True
            if self.city_runner:
                try:
                    self.city_runner.restart()
                    self.is_running = True
                    self.last_error = None
                except Exception as e:
                    self.last_error = str(e)
                    print(f"SimulationManager restart error: {e}")
            self.fixed_controller.reset()
            self.adaptive_controller.reset()
            self.is_paused = False
            if was_running:
                event_log.add("Simulation", "Reset SUMO network and controllers.")

    def set_controller_mode(self, mode: str):
        with self.lock:
            if mode in ["AI_ADAPTIVE", "GREEN_WAVE", "FIXED_TIME", "MANUAL"]:
                self.controller_mode = mode
                self.adaptive_controller.configure_timings(green_wave=(mode == "GREEN_WAVE"))
                event_log.add("Controller", f"Switched signal controller mode to {mode}.")

    def set_camera_zone(self, zone_id: str):
        with self.lock:
            if zone_id in CAMERA_ZONES:
                self.active_camera = zone_id

    def set_sim_speed(self, multiplier: float):
        with self.lock:
            m = max(0.2, min(5.0, float(multiplier)))
            self.speed_multiplier = m
            self.step_delay = self.base_step_delay / m

    def set_demand_scale(self, scale: float):
        with self.lock:
            self.traffic_scale = float(scale)
            if self.city_runner and self.city_runner.is_running:
                self.city_runner.set_traffic_scale(scale)

    def _run_loop(self):
        while not self.stop_signal:
            if not self.is_paused and self.city_runner and self.city_runner.is_running:
                try:
                    with self.lock:
                        if not self.city_runner or not self.city_runner.is_running:
                            continue
                        telemetry = self.city_runner.step()

                        if self.controller_mode == "AI_ADAPTIVE":
                            self.adaptive_controller.step(telemetry, self.city_runner, green_wave=False)
                        elif self.controller_mode == "GREEN_WAVE":
                            self.adaptive_controller.step(telemetry, self.city_runner, green_wave=True)
                        elif self.controller_mode == "FIXED_TIME":
                            target_phases = self.fixed_controller.step()
                            for tlid, pidx in target_phases.items():
                                self.city_runner.set_tl_phase(tlid, pidx)

                        self.latest_telemetry = telemetry
                except Exception as e:
                    self.last_error = str(e)
                    print(f"SimulationManager error in step: {e}")
                    time.sleep(0.5)

            time.sleep(self.step_delay)

    def get_status_payload(self) -> Dict[str, Any]:
        with self.lock:
            if self.controller_mode in ("AI_ADAPTIVE", "GREEN_WAVE"):
                ctrl_info = self.adaptive_controller.get_info()
            else:
                ctrl_info = self.fixed_controller.get_info()

            tl_map = self.latest_telemetry.get("traffic_lights", {})
            central_tl = tl_map.get("TL_CENTRAL", {})
            metrics = self.latest_telemetry.get("metrics", {})

            return {
                "is_running": self.is_running,
                "is_paused": self.is_paused,
                "last_error": self.last_error,
                "controller_mode": self.controller_mode,
                "controller_info": ctrl_info,
                "speed_multiplier": self.speed_multiplier,
                "traffic_scale": self.traffic_scale,
                "active_camera": self.active_camera,
                "camera_zones": CAMERA_ZONES,
                "telemetry": self.latest_telemetry,
                "metrics": metrics,
                "traffic_light": central_tl,
                "traffic_lights": tl_map,
                "roundabout": self.latest_telemetry.get("roundabout", {}),
                "t_junction": self.latest_telemetry.get("t_junction", {}),
                "intersection_4way": self.latest_telemetry.get("intersection_4way", {}),
                "vehicles": self.latest_telemetry.get("vehicles", []),
            }


sim_manager = SimulationManager()
camera_manager = LiveCameraManager()
traffic_provider = TrafficDataProvider()
video_engine: Optional[VideoAnalysisEngine] = None
latest_comparison_result: Optional[Dict[str, Any]] = None


def get_video_engine() -> VideoAnalysisEngine:
    global video_engine
    if video_engine is None:
        video_engine = VideoAnalysisEngine(model_path=YOLO_MODEL_PATH)
    return video_engine


@asynccontextmanager
async def lifespan(app_instance: FastAPI):
    event_log.add("System", "Traffic Intel API server started.")
    threading.Thread(target=camera_manager._ensure_model, daemon=True).start()
    yield
    print("Shutting down Traffic Intel resources...")
    camera_manager.disconnect()
    sim_manager.stop_simulation()


app = FastAPI(title="TRAFFIC INTEL API", version="3.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- Overview & Health ---

@app.get("/api/overview")
def get_overview():
    sim_status = sim_manager.get_status_payload()
    cam_status = camera_manager.get_status()
    prov_status = traffic_provider.get_status()
    return JSONResponse({
        "simulation": {
            "is_running": sim_status["is_running"],
            "is_paused": sim_status["is_paused"],
            "controller_mode": sim_status["controller_mode"],
            "active_vehicles": sim_status["metrics"].get("total_active", 0),
            "avg_speed_kmh": sim_status["metrics"].get("average_speed_kmh", 0.0),
            "total_queued": sim_status["metrics"].get("total_queued", 0),
            "intersections": sim_status["controller_info"].get("intersections", {}),
            "traffic_lights": sim_status["traffic_lights"],
            "last_error": sim_status["last_error"],
        },
        "camera": cam_status,
        "traffic_provider": prov_status,
        "events": event_log.list(15),
    })


# --- Simulation & Geometry Endpoints ---

@app.get("/api/network/geometry")
def get_network_geometry():
    if sim_manager.city_runner is None:
        sim_manager.city_runner = CitySimulationRunner(use_gui=False)
    return JSONResponse(sim_manager.city_runner.get_network_geometry())


@app.get("/api/telemetry")
def get_telemetry():
    return JSONResponse(sim_manager.get_status_payload())


@app.get("/api/stream")
async def stream_telemetry():
    async def event_generator():
        while True:
            payload = sim_manager.get_status_payload()
            yield f"data: {json.dumps(payload)}\n\n"
            await asyncio.sleep(0.08)
    return StreamingResponse(event_generator(), media_type="text/event-stream")


@app.post("/api/control/camera")
def control_camera(zone: str = Form(...)):
    sim_manager.set_camera_zone(zone)
    return {"status": "camera_updated", "active_camera": sim_manager.active_camera}


@app.post("/api/control/start")
def control_start():
    sim_manager.start_simulation()
    return {"status": "started", "mode": sim_manager.controller_mode, "is_running": sim_manager.is_running}


@app.post("/api/control/pause")
def control_pause():
    sim_manager.pause_simulation()
    return {"status": "paused"}


@app.post("/api/control/stop")
def control_stop():
    sim_manager.stop_simulation()
    return {"status": "stopped"}


@app.post("/api/control/reset")
def control_reset():
    sim_manager.reset_simulation()
    return {"status": "reset"}


@app.post("/api/control/mode")
def control_mode(mode: str = Form(...)):
    sim_manager.set_controller_mode(mode)
    return {"status": "mode_updated", "mode": sim_manager.controller_mode}


@app.post("/api/control/flush_corridor")
def control_flush_corridor(corridor_id: Optional[int] = Form(None), tl_id: str = Form("TL_CENTRAL")):
    if corridor_id is None:
        corridor_id = sim_manager.adaptive_controller.get_heaviest_corridor(tl_id)
    sim_manager.adaptive_controller.force_corridor(tl_id, corridor_id)
    event_log.add("Controller", f"Operator requested safe corridor switch on {tl_id} -> Corridor {corridor_id}.")
    return {"status": "corridor_flushed", "tl_id": tl_id, "corridor": corridor_id}


@app.post("/api/control/scale")
def control_scale(scale: float = Form(...)):
    sim_manager.set_demand_scale(scale)
    event_log.add("Simulation", f"Traffic demand scale set to {scale}x.")
    return {"status": "scale_updated", "scale": sim_manager.traffic_scale}


@app.post("/api/simulation/scenario")
def set_simulation_scenario(scenario: str = Form(...)):
    if not sim_manager.is_running:
        sim_manager.start_simulation()
    if sim_manager.city_runner:
        res = sim_manager.city_runner.set_scenario(scenario)
        event_log.add("Simulation", f"Applied traffic scenario: {res}.")
        return {"status": "scenario_updated", "scenario": res}
    return JSONResponse({"status": "error", "message": "Simulation runner not active"}, status_code=400)


@app.post("/api/simulation/surge")
def create_simulation_surge(approach: str = Form("north"), count: int = Form(8)):
    if not sim_manager.is_running:
        sim_manager.start_simulation()
    if sim_manager.city_runner:
        cnt = sim_manager.city_runner.create_traffic_surge(approach=approach, count=count)
        event_log.add("Simulation", f"Injected {cnt} vehicles onto {approach.upper()} approach.")
        return {"status": "surge_created", "approach": approach, "count": cnt}
    return JSONResponse({"status": "error", "message": "Simulation runner not active"}, status_code=400)


@app.post("/api/simulation/reset_scenario")
def reset_simulation_scenario():
    if sim_manager.city_runner:
        res = sim_manager.city_runner.reset_scenario()
        event_log.add("Simulation", "Reset scenario to NORMAL balanced demand.")
        return {"status": "scenario_reset", "scenario": res}
    return {"status": "error", "message": "Simulation runner not active"}


@app.post("/api/control/emergency")
def control_emergency():
    if not sim_manager.is_running:
        sim_manager.start_simulation()
    if sim_manager.city_runner:
        vid = sim_manager.city_runner.spawn_emergency_vehicle()
        event_log.add("Emergency", f"Dispatched emergency vehicle {vid}.", level="warning")
        return {"status": "emergency_dispatched", "vehicle_id": vid}
    return {"status": "error", "message": "Simulation runner not active"}


@app.post("/api/control/signal_override")
def control_signal_override(tl_id: str = Form(...), phase_index: int = Form(...)):
    if sim_manager.city_runner and sim_manager.is_running:
        sim_manager.city_runner.set_tl_phase(tl_id, phase_index)
        event_log.add("Controller", f"Manual phase override on {tl_id} -> Phase {phase_index}.")
        return {"status": "signal_overridden", "tl_id": tl_id, "phase": phase_index}
    return {"status": "error", "message": "Simulation runner not active"}


@app.post("/api/control/sim_speed")
def control_sim_speed(multiplier: float = Form(...)):
    sim_manager.set_sim_speed(multiplier)
    return {"status": "speed_updated", "multiplier": multiplier}


# --- Real Traffic to Simulation Bridge ---

@app.post("/api/simulation/apply_real_traffic")
def apply_real_traffic_to_sumo(
    source: str = Form("camera"),
    approach: str = Form("north"),
    arrival_rate_vph: Optional[int] = Form(None),
    congestion_level: Optional[str] = Form(None),
):
    """
    Converts real-world observations (from live camera or traffic provider)
    into controlled SUMO vehicle demand. Only affects the SUMO simulation.
    """
    if not sim_manager.is_running:
        sim_manager.start_simulation()

    if source == "camera":
        cam = camera_manager.get_status()
        if cam["state"] not in ("CONNECTED", "PROCESSING"):
            return JSONResponse(
                {"status": "error", "message": "Camera is not connected. Connect a camera first."},
                status_code=400,
            )
        vph = arrival_rate_vph or cam["analytics"].get("estimated_arrival_rate_vph", 0)
        density = cam["analytics"].get("density_level", "LOW")
        surge_count = max(2, min(14, int(round(vph / 120.0))))
        scale = 1.0 if density == "LOW" else (1.5 if density == "MODERATE" else 2.2)
    else:
        lvl = (congestion_level or "MODERATE").upper()
        surge_count = 3 if lvl == "FLOWING" else (7 if lvl == "MODERATE" else 12)
        scale = 0.9 if lvl == "FLOWING" else (1.4 if lvl == "MODERATE" else 2.0)
        vph = surge_count * 120

    sim_manager.set_demand_scale(scale)
    injected = sim_manager.city_runner.create_traffic_surge(approach=approach, count=surge_count)
    msg = (
        f"Controlled Simulation Input ({source}): Applied {vph} veh/h observation "
        f"-> {injected} vehicles on {approach.upper()} approach, demand scale {scale}x."
    )
    event_log.add("Bridge", msg)
    return {
        "status": "applied",
        "data_source": "Controlled simulation input",
        "observation_source": source,
        "approach": approach,
        "injected_vehicles": injected,
        "demand_scale": scale,
        "message": msg,
    }


# --- Live Camera Endpoints ---

@app.get("/api/camera/catalog")
def camera_catalog():
    return JSONResponse({"verified_cameras": list(VERIFIED_LIVE_CAMERAS.values())})


@app.post("/api/camera/connect")
def camera_connect(source_type: str = Form(...), source_value: str = Form("0")):
    res = camera_manager.connect(source_type, source_value)
    event_log.add("Camera", f"Connecting to {res['source_label'] or source_type}...")
    return JSONResponse(res)


@app.post("/api/camera/disconnect")
def camera_disconnect():
    res = camera_manager.disconnect()
    event_log.add("Camera", "Camera disconnected and stream released.")
    return JSONResponse(res)


@app.post("/api/camera/restart")
def camera_restart():
    res = camera_manager.restart()
    event_log.add("Camera", f"Restarted camera stream ({res['source_label']}).")
    return JSONResponse(res)


@app.get("/api/camera/status")
def camera_status():
    return JSONResponse(camera_manager.get_status())


@app.get("/api/camera/stream")
def camera_stream():
    """MJPEG live stream of YOLOv8 + ByteTrack annotated frames."""
    def gen():
        while True:
            st = camera_manager.get_status()["state"]
            if st in ("DISCONNECTED", "ERROR"):
                break
            jpg = camera_manager.get_latest_frame()
            if jpg is not None:
                yield (
                    b"--frame\r\n"
                    b"Content-Type: image/jpeg\r\n\r\n" + jpg + b"\r\n"
                )
            time.sleep(0.05)

    st = camera_manager.get_status()["state"]
    if st in ("DISCONNECTED", "ERROR"):
        return Response(status_code=204)
    return StreamingResponse(gen(), media_type="multipart/x-mixed-replace; boundary=frame")


@app.websocket("/ws/camera/webcam")
async def webcam_ws_endpoint(websocket: WebSocket):
    """Receives live JPEG frames from browser MediaDevices webcam, runs YOLOv8 + ByteTrack, returns boxes + analytics."""
    await websocket.accept()
    device_label = websocket.query_params.get("label", "Local Webcam")
    camera_manager.start_webcam_session(device_label)
    try:
        while True:
            frame_bytes = await websocket.receive_bytes()
            try:
                result = await asyncio.to_thread(camera_manager.process_webcam_frame, frame_bytes)
                await websocket.send_json(result)
            except Exception as proc_err:
                await websocket.send_json({"error": f"Detection model unavailable: {proc_err}"})
    except WebSocketDisconnect:
        pass
    except Exception as e:
        print(f"Webcam WS error: {e}")
    finally:
        camera_manager.disconnect()


# --- Live Traffic Map & Provider Endpoints ---

@app.get("/api/map/status")
def map_status(lat: Optional[float] = None, lon: Optional[float] = None):
    st = traffic_provider.get_status()
    c_lat = lat if lat is not None else st["default_center"][0]
    c_lon = lon if lon is not None else st["default_center"][1]
    sim_markers = traffic_provider.get_simulation_markers(c_lat, c_lon)
    cam = camera_manager.get_status()
    cam_markers = []
    if cam["state"] in ("CONNECTED", "PROCESSING"):
        cam_markers.append({
            "id": "CAM_LIVE_01",
            "name": cam["source_label"],
            "lat": round(c_lat + 0.0008, 6),
            "lon": round(c_lon - 0.0008, 6),
            "state": cam["state"],
            "active_detected": cam["analytics"]["active_detected"],
            "source": "Live camera",
        })
    return JSONResponse({
        "provider_status": st,
        "simulation_markers": sim_markers,
        "camera_markers": cam_markers,
    })


@app.get("/api/map/traffic")
def map_traffic(lat: Optional[float] = None, lon: Optional[float] = None, include_demo: bool = False):
    return JSONResponse(traffic_provider.fetch_road_traffic(lat=lat, lon=lon, include_demo=include_demo))


@app.get("/api/map/tile/{z}/{x}/{y}")
def map_flow_tile(z: int, x: int, y: int):
    tile_bytes = traffic_provider.fetch_flow_tile(z, x, y)
    if tile_bytes is None:
        return Response(status_code=204)
    return Response(content=tile_bytes, media_type="image/png")


# --- Analytics & Comparison Endpoints ---

@app.get("/api/analytics/comparison")
def get_latest_comparison():
    if latest_comparison_result is None:
        return JSONResponse({"available": False, "message": "No simulation results available yet."})
    return JSONResponse({"available": True, "result": latest_comparison_result})


@app.post("/api/analytics/compare")
def run_comparison(scenario: str = Form("SURGE_NORTH"), steps: int = Form(100)):
    global latest_comparison_result
    was_running = sim_manager.is_running
    was_paused = sim_manager.is_paused
    if was_running:
        sim_manager.stop_simulation()

    try:
        res = run_controlled_comparison(scenario=scenario, steps=steps)
        latest_comparison_result = res
        event_log.add("Analytics", f"Completed Fixed-Time vs Adaptive DQN benchmark ({scenario}, {steps} steps).")
        return JSONResponse({"available": True, "result": res})
    except Exception as e:
        event_log.add("Analytics", f"Comparison failed: {e}", level="error")
        return JSONResponse({"available": False, "error": str(e)}, status_code=500)
    finally:
        if was_running:
            sim_manager.start_simulation()
            if was_paused:
                sim_manager.pause_simulation()


# --- Settings Endpoints ---

@app.get("/api/settings")
def get_settings():
    return JSONResponse({
        "timings": {
            "min_green_sec": sim_manager.adaptive_controller.min_green,
            "max_green_sec": sim_manager.adaptive_controller.max_green,
            "max_red_sec": sim_manager.adaptive_controller.max_red,
            "yellow_sec": sim_manager.adaptive_controller.yellow_dur,
            "green_wave_enabled": sim_manager.adaptive_controller.green_wave_enabled,
        },
        "provider": traffic_provider.get_status(),
    })


@app.post("/api/settings/timings")
def update_timings(
    min_green: float = Form(...),
    max_green: float = Form(...),
    max_red: float = Form(...),
    yellow_dur: float = Form(3.0),
    green_wave: bool = Form(False),
):
    if max_green <= min_green:
        return JSONResponse(
            {"status": "error", "message": "Maximum green must be greater than minimum green."},
            status_code=400,
        )
    if max_red <= 0:
        return JSONResponse(
            {"status": "error", "message": "Maximum red must be a positive value."},
            status_code=400,
        )
    if yellow_dur < 3.0:
        return JSONResponse(
            {"status": "error", "message": "Yellow clearance cannot be below safe 3.0s minimum."},
            status_code=400,
        )
    sim_manager.adaptive_controller.configure_timings(
        min_green=min_green,
        max_green=max_green,
        max_red=max_red,
        yellow_dur=yellow_dur,
        green_wave=green_wave,
    )
    event_log.add("Settings", f"Updated signal timings (MinG={min_green}s, MaxG={max_green}s, MaxR={max_red}s, Yellow={yellow_dur}s).")
    return {"status": "updated", "timings": sim_manager.adaptive_controller.get_info()["timings"]}


@app.post("/api/settings/provider")
def update_provider_runtime(
    provider: str = Form("none"),
    api_key: str = Form(""),
    default_lat: float = Form(28.6139),
    default_lon: float = Form(77.2090),
):
    p = provider.lower().strip()
    traffic_provider.provider = p
    if p == "tomtom" and api_key.strip():
        traffic_provider.tomtom_key = api_key.strip()
    elif p == "here" and api_key.strip():
        traffic_provider.here_key = api_key.strip()
    traffic_provider.default_lat = float(default_lat)
    traffic_provider.default_lon = float(default_lon)
    traffic_provider._cache.clear()
    event_log.add("Settings", f"Updated traffic provider settings ({p}).")
    return JSONResponse(traffic_provider.get_status())


# --- Legacy Optional Fallback Video Endpoints (kept for testing) ---

@app.get("/api/video/sample_data")
def get_sample_video_data():
    cache_path = os.path.join(DATA_DIR, "sample_traffic_analysis.json")
    if os.path.exists(cache_path):
        with open(cache_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            data["video_url"] = "/static/sample_traffic.mp4"
            return JSONResponse(data)
    sample_vid = os.path.join(DATA_DIR, "sample_traffic.mp4")
    if not os.path.exists(sample_vid):
        return JSONResponse({"error": "sample_traffic.mp4 not found"}, status_code=404)
    engine = get_video_engine()
    results = engine.analyze_video(sample_vid)
    results["video_url"] = "/static/sample_traffic.mp4"
    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(results, f)
    return JSONResponse(results)


@app.post("/api/video/upload")
async def upload_video(file: UploadFile = File(...)):
    upload_dir = os.path.join(DATA_DIR, "uploads")
    os.makedirs(upload_dir, exist_ok=True)
    save_path = os.path.join(upload_dir, file.filename)
    contents = await file.read()
    with open(save_path, "wb") as f:
        f.write(contents)
    frontend_upload_dir = os.path.join(FRONTEND_DIR, "uploads")
    os.makedirs(frontend_upload_dir, exist_ok=True)
    shutil.copy2(save_path, os.path.join(frontend_upload_dir, file.filename))
    try:
        engine = get_video_engine()
        results = engine.analyze_video(save_path)
        results["video_url"] = f"/static/uploads/{file.filename}"
        return JSONResponse(results)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


# Serve Frontend static assets and uploads
uploads_dir = os.path.join(FRONTEND_DIR, "uploads")
os.makedirs(uploads_dir, exist_ok=True)
app.mount("/static/uploads", StaticFiles(directory=uploads_dir), name="static_uploads")
app.mount("/uploads", StaticFiles(directory=uploads_dir), name="uploads")
app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")


@app.get("/", response_class=HTMLResponse)
def serve_index():
    index_file = os.path.join(FRONTEND_DIR, "index.html")
    if os.path.exists(index_file):
        with open(index_file, "r", encoding="utf-8") as f:
            return f.read()
    return "<h1>TRAFFIC INTEL Backend Running</h1>"


if __name__ == "__main__":
    print("Starting TRAFFIC INTEL API Server on port 8000...")
    sim_manager.start_simulation()
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="info")
