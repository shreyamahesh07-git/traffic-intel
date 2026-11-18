import os
import sys
import time
import json
import shutil
import threading
import numpy as np
from typing import Dict, Any, Optional

from fastapi import FastAPI, UploadFile, File, Form, BackgroundTasks
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

# Load backend configuration
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from backend.config import (
    BASE_DIR,
    BACKEND_DIR,
    FRONTEND_DIR,
    DATA_DIR,
    YOLO_MODEL_PATH,
    DQN_MODEL_PATH
)
from backend.simulation.sim_runner import (
    SumoSimulationRunner,
    PHASE_NS_GREEN,
    PHASE_NS_YELLOW,
    PHASE_ALL_RED_NS,
    PHASE_EW_GREEN,
    PHASE_EW_YELLOW,
    PHASE_ALL_RED_EW
)
from backend.density.density_estimator import TrafficDensityEstimator
from backend.controllers.fixed_controller import FixedTimeController
from backend.controllers.adaptive_controller import AdaptiveDQNController
from backend.detection.detector import VideoAnalysisEngine

app = FastAPI(title="TRAFFIC INTEL API", version="2.6.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global Simulation & AI Manager
class SimulationManager:
    def __init__(self):
        self.lock = threading.Lock()
        self.is_running = False
        self.is_paused = False
        self.controller_mode = "AI_ADAPTIVE"  # "AI_ADAPTIVE" or "FIXED_TIME"
        
        # Modules
        self.runner: Optional[SumoSimulationRunner] = None
        self.density_estimator = TrafficDensityEstimator()
        self.fixed_controller = FixedTimeController()
        self.adaptive_controller = AdaptiveDQNController()

        # Telemetry cache
        self.latest_telemetry: Dict[str, Any] = {}
        self.latest_density: Dict[str, Any] = {}
        self.worker_thread: Optional[threading.Thread] = None
        self.stop_signal = False

    def start_simulation(self):
        with self.lock:
            if self.is_running:
                self.is_paused = False
                return
            
            try:
                if self.runner is None:
                    self.runner = SumoSimulationRunner(use_gui=False)
                self.runner.start()
            except Exception as e:
                print(f"SimulationManager: Could not start SUMO runner: {e}")
            
            self.fixed_controller.reset()
            self.adaptive_controller.reset()
            
            self.is_running = True
            self.is_paused = False
            self.stop_signal = False

            if self.worker_thread is None or not self.worker_thread.is_alive():
                self.worker_thread = threading.Thread(target=self._run_loop, daemon=True)
                self.worker_thread.start()

    def pause_simulation(self):
        with self.lock:
            self.is_paused = True

    def reset_simulation(self):
        with self.lock:
            self.is_paused = True
            if self.runner:
                try:
                    self.runner.restart()
                except Exception as e:
                    print(f"SimulationManager restart error: {e}")
            self.fixed_controller.reset()
            self.adaptive_controller.reset()
            self.is_paused = False

    def set_controller_mode(self, mode: str):
        with self.lock:
            if mode in ["AI_ADAPTIVE", "FIXED_TIME"]:
                self.controller_mode = mode

    def _run_loop(self):
        while not self.stop_signal:
            if not self.is_paused and self.runner and self.runner.is_running:
                try:
                    # 1. Step simulation
                    telemetry = self.runner.step()
                    density_info = self.density_estimator.compute_density(telemetry)
                    dqn_state = density_info["dqn_state"]

                    # 2. Controller phase decision
                    if self.controller_mode == "AI_ADAPTIVE":
                        next_phase = self.adaptive_controller.step(dqn_state, telemetry=telemetry)
                    else:
                        next_phase = self.fixed_controller.step(telemetry=telemetry)
                    
                    self.runner.set_phase(next_phase)

                    # 3. Add explicit signal statuses for frontend rendering
                    cur_phase = telemetry.get("traffic_light", {}).get("current_phase", 0)
                    signals = {"NORTH": "RED", "SOUTH": "RED", "EAST": "RED", "WEST": "RED"}
                    if cur_phase == PHASE_NS_GREEN:
                        signals["NORTH"] = "GREEN"
                        signals["SOUTH"] = "GREEN"
                    elif cur_phase == PHASE_NS_YELLOW:
                        signals["NORTH"] = "YELLOW"
                        signals["SOUTH"] = "YELLOW"
                    elif cur_phase == PHASE_EW_GREEN:
                        signals["EAST"] = "GREEN"
                        signals["WEST"] = "GREEN"
                    elif cur_phase == PHASE_EW_YELLOW:
                        signals["EAST"] = "YELLOW"
                        signals["WEST"] = "YELLOW"

                    telemetry["traffic_light"]["signals"] = signals

                    with self.lock:
                        self.latest_telemetry = telemetry
                        self.latest_density = density_info

                except Exception as e:
                    print(f"SimulationManager error in step: {e}")
                    time.sleep(0.5)

            time.sleep(0.04)  # ~25 FPS pacing

    def get_status_payload(self) -> Dict[str, Any]:
        with self.lock:
            ctrl_info = self.adaptive_controller.get_info() if self.controller_mode == "AI_ADAPTIVE" else self.fixed_controller.get_info()
            return {
                "is_running": self.is_running,
                "is_paused": self.is_paused,
                "controller_mode": self.controller_mode,
                "controller_info": ctrl_info,
                "telemetry": self.latest_telemetry,
                "density": self.latest_density
            }

sim_manager = SimulationManager()

# Global video analysis engine
video_engine: Optional[VideoAnalysisEngine] = None

def get_video_engine() -> VideoAnalysisEngine:
    global video_engine
    if video_engine is None:
        video_engine = VideoAnalysisEngine(model_path=YOLO_MODEL_PATH)
    return video_engine

# --- API Endpoints ---

@app.get("/api/telemetry")
def get_telemetry():
    """Return latest simulation, controller explanation, and traffic metrics."""
    return JSONResponse(sim_manager.get_status_payload())

@app.post("/api/control/start")
def control_start():
    sim_manager.start_simulation()
    return {"status": "started", "mode": sim_manager.controller_mode}

@app.post("/api/control/pause")
def control_pause():
    sim_manager.pause_simulation()
    return {"status": "paused"}

@app.post("/api/control/reset")
def control_reset():
    sim_manager.reset_simulation()
    return {"status": "reset"}

@app.post("/api/control/mode")
def control_mode(mode: str = Form(...)):
    sim_manager.set_controller_mode(mode)
    return {"status": "mode_updated", "mode": sim_manager.controller_mode}

@app.get("/api/video/sample_data")
def get_sample_video_data():
    """Return cached YOLOv8 detections and tracking data for the default real traffic video."""
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

@app.get("/api/video/load/{video_name}")
def load_specific_video(video_name: str):
    """Load pre-analyzed video metadata and URL directly."""
    if "city" in video_name or "street" in video_name or "20261117" in video_name:
        cache_path = os.path.join(DATA_DIR, "city_street_traffic_analysis.json")
        if os.path.exists(cache_path):
            with open(cache_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                data["video_url"] = "/static/uploads/city_street_traffic.mp4"
                return JSONResponse(data)

    elif "13002160" in video_name or "highway" in video_name:
        cache_path = os.path.join(DATA_DIR, "13002160_1920_1080_60fps_analysis.json")
        if os.path.exists(cache_path):
            with open(cache_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                data["video_url"] = "/static/uploads/13002160_1920_1080_60fps.mp4"
                return JSONResponse(data)

    elif "sample" in video_name:
        return get_sample_video_data()

    return JSONResponse({"error": f"Video {video_name} not found"}, status_code=404)

@app.post("/api/video/upload")
async def upload_video(file: UploadFile = File(...)):
    """Upload user video (MP4, AVI, MOV), run YOLO detection & tracking, and return frame-indexed metadata."""
    upload_dir = os.path.join(DATA_DIR, "uploads")
    os.makedirs(upload_dir, exist_ok=True)
    save_path = os.path.join(upload_dir, file.filename)
    
    # Save file contents
    contents = await file.read()
    with open(save_path, "wb") as f:
        f.write(contents)

    # Mirror to frontend static for direct browser playback
    frontend_upload_dir = os.path.join(FRONTEND_DIR, "static", "uploads")
    os.makedirs(frontend_upload_dir, exist_ok=True)
    shutil.copy2(save_path, os.path.join(frontend_upload_dir, file.filename))

    # Fast check: Check if pre-computed analysis already exists
    base_name = os.path.splitext(file.filename)[0]
    cached_candidates = [
        os.path.join(DATA_DIR, f"{base_name}_analysis.json"),
        os.path.join(DATA_DIR, f"{file.filename}_analysis.json"),
        os.path.join(upload_dir, f"{base_name}_analysis.json")
    ]
    for c in cached_candidates:
        if os.path.exists(c):
            print(f"Serving pre-cached analysis from {c}")
            with open(c, "r", encoding="utf-8") as f:
                cached_data = json.load(f)
                cached_data["video_url"] = f"/static/uploads/{file.filename}"
                return JSONResponse(cached_data)

    # Run analysis with optimized inference
    try:
        engine = get_video_engine()
        results = engine.analyze_video(save_path)
        results["video_url"] = f"/static/uploads/{file.filename}"
        
        # Save cache for future instant reloads
        cache_save = os.path.join(DATA_DIR, f"{base_name}_analysis.json")
        with open(cache_save, "w", encoding="utf-8") as f:
            json.dump(results, f)
            
        return JSONResponse(results)
    except Exception as e:
        print(f"Error analyzing uploaded video: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)

@app.get("/api/video/file/{filename}")
def get_video_file(filename: str):
    """Serve uploaded or sample video file."""
    if filename == "sample_traffic.mp4":
        vid_path = os.path.join(DATA_DIR, "sample_traffic.mp4")
    else:
        vid_path = os.path.join(DATA_DIR, "uploads", filename)
    
    if os.path.exists(vid_path):
        return FileResponse(vid_path, media_type="video/mp4")
    return JSONResponse({"error": "Video file not found"}, status_code=404)

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
