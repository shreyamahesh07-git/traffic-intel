import os
import sys

# Base directories
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKEND_DIR = os.path.join(BASE_DIR, "backend")
FRONTEND_DIR = os.path.join(BASE_DIR, "frontend")

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

# Model Paths
MODELS_DIR = os.path.join(BACKEND_DIR, "models")
YOLO_MODEL_PATH = os.path.join(MODELS_DIR, "yolov8n.pt")
DQN_MODEL_PATH = os.path.join(MODELS_DIR, "dqn_traffic_model.pt")

# Data & Logging
DATA_DIR = os.path.join(BACKEND_DIR, "data")
EVAL_DIR = os.path.join(BACKEND_DIR, "evaluation")

# Simulation Constants
SIMULATION_STEP_LENGTH = 0.5  # seconds per TraCI step
YELLOW_PHASE_DURATION = 3     # seconds
ALL_RED_PHASE_DURATION = 2    # seconds
MIN_GREEN_DURATION = 10       # seconds
MAX_GREEN_DURATION = 60       # seconds
DEFAULT_FIXED_GREEN = 30      # seconds for fixed-time baseline

