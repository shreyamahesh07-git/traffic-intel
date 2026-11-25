import os
import sys
from dotenv import load_dotenv

# Base directories
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKEND_DIR = os.path.join(BASE_DIR, "backend")
FRONTEND_DIR = os.path.join(BASE_DIR, "frontend")

# Load environment variables from .env if present
load_dotenv(os.path.join(BASE_DIR, ".env"))

# Keep Ultralytics config inside project directory to avoid AppData permission issues
os.environ.setdefault("YOLO_CONFIG_DIR", os.path.join(BASE_DIR, ".ultralytics"))

# SUMO Environment
SUMO_HOME = os.path.join(BASE_DIR, "sumo")
os.environ["SUMO_HOME"] = SUMO_HOME
sumo_bin_dir = os.path.join(SUMO_HOME, "bin")
if sumo_bin_dir not in os.environ.get("PATH", ""):
    os.environ["PATH"] = sumo_bin_dir + os.pathsep + os.environ.get("PATH", "")

SUMO_BIN = os.path.join(sumo_bin_dir, "sumo.exe")
SUMO_GUI_BIN = os.path.join(sumo_bin_dir, "sumo-gui.exe")
NETCONVERT_BIN = os.path.join(sumo_bin_dir, "netconvert.exe")

# Simulation Network Files
SIMULATION_DIR = os.path.join(BACKEND_DIR, "simulation")
NETWORKS_DIR = os.path.join(SIMULATION_DIR, "networks")
NET_FILE = os.path.join(NETWORKS_DIR, "intersection.net.xml")
ROU_FILE = os.path.join(NETWORKS_DIR, "intersection.rou.xml")
SUMOCFG_FILE = os.path.join(NETWORKS_DIR, "intersection.sumocfg")

CITY_NET_FILE = os.path.join(NETWORKS_DIR, "city.net.xml")
CITY_ROU_FILE = os.path.join(NETWORKS_DIR, "city.rou.xml")
CITY_SUMOCFG_FILE = os.path.join(NETWORKS_DIR, "city.sumocfg")

# Model Paths
MODELS_DIR = os.path.join(BACKEND_DIR, "models")
YOLO_MODEL_PATH = os.path.join(MODELS_DIR, "yolov8n.pt")
DQN_MODEL_PATH = os.path.join(MODELS_DIR, "dqn_traffic_model.pt")

# Data & Logging
DATA_DIR = os.path.join(BACKEND_DIR, "data")
EVAL_DIR = os.path.join(BACKEND_DIR, "evaluation")

# Simulation & Signal Control Constants (aligned with city.net.xml 4-phase logic)
SIMULATION_STEP_LENGTH = 0.5  # seconds per TraCI step
YELLOW_PHASE_DURATION = 3     # seconds (matches 3s yellow in city.net.xml)
ALL_RED_PHASE_DURATION = 2    # legacy single-intersection constant (unused in city.net.xml)
MIN_GREEN_DURATION = 10       # seconds minimum green before switching
MAX_GREEN_DURATION = 45       # seconds maximum green before forced reconsideration
MAX_RED_DURATION = 50         # seconds maximum red threshold for starvation prevention
DEFAULT_FIXED_GREEN = 30      # seconds for fixed-time baseline

# External Traffic Data Provider Configuration (via environment variables)
TRAFFIC_PROVIDER = os.getenv("TRAFFIC_PROVIDER", "none").lower()  # "tomtom", "here", or "none"
TOMTOM_API_KEY = os.getenv("TOMTOM_API_KEY", "")
HERE_API_KEY = os.getenv("HERE_API_KEY", "")
DEFAULT_MAP_LAT = float(os.getenv("DEFAULT_MAP_LAT", "28.6139"))
DEFAULT_MAP_LON = float(os.getenv("DEFAULT_MAP_LON", "77.2090"))

