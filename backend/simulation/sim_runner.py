import os
import sys
import traci
import sumolib
from typing import Dict, List, Any, Optional

# Ensure project root is in sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from backend.config import (
    SUMOCFG_FILE,
    SUMO_BIN,
    SUMO_GUI_BIN,
    SIMULATION_STEP_LENGTH,
    YELLOW_PHASE_DURATION,
    ALL_RED_PHASE_DURATION
)

# Standard Traffic Light Phases for the 4-way intersection
# 16-character signal states matching netconvert links:
# [0..3]: North inbound, [4..7]: East inbound, [8..11]: South inbound, [12..15]: West inbound
PHASE_NS_GREEN = 0
PHASE_NS_YELLOW = 1
PHASE_ALL_RED_NS = 2
PHASE_EW_GREEN = 3
PHASE_EW_YELLOW = 4
PHASE_ALL_RED_EW = 5

PHASE_STATES = {
    PHASE_NS_GREEN: "GGGgrrrrGGGgrrrr",     # North-South Green
    PHASE_NS_YELLOW: "yyygrrrryyygrrrr",    # North-South Yellow
    PHASE_ALL_RED_NS: "rrrrrrrrrrrrrrrr",   # All-Red Clearance
    PHASE_EW_GREEN: "rrrrGGGgrrrrGGGg",     # East-West Green
    PHASE_EW_YELLOW: "rrrryyygrrrryyyg",    # East-West Yellow
    PHASE_ALL_RED_EW: "rrrrrrrrrrrrrrrr"    # All-Red Clearance
}

PHASE_NAMES = {
    PHASE_NS_GREEN: "NORTH_SOUTH_GREEN",
    PHASE_NS_YELLOW: "NORTH_SOUTH_YELLOW",
    PHASE_ALL_RED_NS: "CLEARANCE_ALL_RED",
    PHASE_EW_GREEN: "EAST_WEST_GREEN",
    PHASE_EW_YELLOW: "EAST_WEST_YELLOW",
    PHASE_ALL_RED_EW: "CLEARANCE_ALL_RED"
}

APPROACH_EDGES = {
    "NORTH": "N2C",
    "SOUTH": "S2C",
    "EAST": "E2C",
    "WEST": "W2C"
}

DEPARTURE_EDGES = {
    "NORTH": "C2N",
    "SOUTH": "C2S",
    "EAST": "C2E",
    "WEST": "C2W"
}

class SumoSimulationRunner:
    """
    Continuous SUMO Simulation Runner with TraCI interface.
    Controls simulation execution, vehicle telemetry extraction, and signal phase manipulation.
    """
    def __init__(self, use_gui: bool = False, step_length: float = SIMULATION_STEP_LENGTH):
        self.use_gui = use_gui
        self.step_length = step_length
        self.sumo_bin = SUMO_GUI_BIN if use_gui else SUMO_BIN
        self.is_running = False
        self.step_count = 0
        self.current_time = 0.0
        
        # Traffic light state
        self.tl_id = "intersection"
        self.current_phase = PHASE_NS_GREEN
        self.phase_step_timer = 0
        self.phase_duration = 30.0  # seconds
        
        # Vehicle ID mapping and detection tags
        self.vehicle_id_map: Dict[str, int] = {}
        self.next_vid_num = 1
        self.total_departed = 0
        self.total_arrived = 0
        self.cumulative_waiting_time = 0.0

    def start(self):
        """Start the SUMO simulation via TraCI."""
        if self.is_running:
            return

        cmd = [
            self.sumo_bin,
            "-c", SUMOCFG_FILE,
            "--step-length", str(self.step_length),
            "--no-warnings", "true",
            "--collision.action", "warn"
        ]
        if self.use_gui:
            cmd.extend(["--start", "true", "--quit-on-end", "true"])

        traci.start(cmd)
        self.is_running = True
        self.step_count = 0
        self.current_time = 0.0
        
        # Ensure traffic light is set to initial phase
        self.set_phase(PHASE_NS_GREEN)

    def set_phase(self, phase_index: int):
        """Set traffic light state to specified phase."""
        if not self.is_running:
            return
        self.current_phase = phase_index
        state_str = PHASE_STATES.get(phase_index, "rrrrrrrrrrrrrrrr")
        traci.trafficlight.setRedYellowGreenState(self.tl_id, state_str)
        self.phase_step_timer = 0

    def get_phase_name(self) -> str:
        return PHASE_NAMES.get(self.current_phase, "UNKNOWN")

    def get_phase_state_string(self) -> str:
        return PHASE_STATES.get(self.current_phase, "rrrrrrrrrrrrrrrr")

    def step(self) -> Dict[str, Any]:
        """
        Advance the simulation by one step.
        Returns detailed telemetry snapshot.
        """
        if not self.is_running:
            self.start()

        traci.simulationStep()
        self.step_count += 1
        self.current_time = self.step_count * self.step_length
        self.phase_step_timer += 1

        # Track arrival/departure counts
        self.total_departed += traci.simulation.getDepartedNumber()
        self.total_arrived += traci.simulation.getArrivedNumber()

        return self.get_telemetry_snapshot()

    def get_telemetry_snapshot(self) -> Dict[str, Any]:
        """Extract complete directional telemetry and vehicle lists from TraCI."""
        vehicle_ids = traci.vehicle.getIDList()
        
        directional_data = {
            "NORTH": {"vehicles": [], "queue_count": 0, "waiting_time": 0.0, "avg_speed": 0.0},
            "SOUTH": {"vehicles": [], "queue_count": 0, "waiting_time": 0.0, "avg_speed": 0.0},
            "EAST": {"vehicles": [], "queue_count": 0, "waiting_time": 0.0, "avg_speed": 0.0},
            "WEST": {"vehicles": [], "queue_count": 0, "waiting_time": 0.0, "avg_speed": 0.0}
        }
        
        all_vehicles = []
        total_waiting_time = 0.0

        for vid in vehicle_ids:
            try:
                edge_id = traci.vehicle.getRoadID(vid)
                lane_id = traci.vehicle.getLaneID(vid)
                x, y = traci.vehicle.getPosition(vid)
                speed = traci.vehicle.getSpeed(vid)
                vtype = traci.vehicle.getTypeID(vid).lower()
                wait_time = traci.vehicle.getWaitingTime(vid)
                acc_wait_time = traci.vehicle.getAccumulatedWaitingTime(vid)
                angle = traci.vehicle.getAngle(vid)

                total_waiting_time += wait_time

                # Assign stable integer vehicle ID
                if vid not in self.vehicle_id_map:
                    self.vehicle_id_map[vid] = self.next_vid_num
                    self.next_vid_num += 1
                clean_id = self.vehicle_id_map[vid]

                # Format vehicle class code and confidence matching target design
                cls_code = "CAR"
                if "bus" in vtype:
                    cls_code = "BUS"
                elif "truck" in vtype:
                    cls_code = "TRU"
                elif "motor" in vtype:
                    cls_code = "MOT"

                # Deterministic high-confidence detection score (0.91 - 0.98)
                conf = round(0.91 + ((clean_id * 7 + 13) % 8) * 0.01, 2)
                tag_label = f"#{clean_id} {cls_code} {conf:.2f}"

                v_info = {
                    "id": vid,
                    "num_id": clean_id,
                    "type": "bus" if cls_code == "BUS" else ("truck" if cls_code == "TRU" else ("motorcycle" if cls_code == "MOT" else "car")),
                    "class_code": cls_code,
                    "confidence": conf,
                    "tag": tag_label,
                    "x": round(x, 2),
                    "y": round(y, 2),
                    "speed": round(speed, 2),
                    "speed_kmh": round(speed * 3.6, 1),
                    "angle": round(angle, 1),
                    "lane_id": lane_id,
                    "edge_id": edge_id,
                    "waiting_time": round(wait_time, 1),
                    "accumulated_waiting_time": round(acc_wait_time, 1),
                    "is_queued": speed < 0.3  # SUMO definition of queued vehicle
                }
                all_vehicles.append(v_info)

                # Assign to inbound direction if currently approaching
                for direction, edge in APPROACH_EDGES.items():
                    if edge_id == edge:
                        directional_data[direction]["vehicles"].append(v_info)
                        if v_info["is_queued"]:
                            directional_data[direction]["queue_count"] += 1
                        directional_data[direction]["waiting_time"] += wait_time

            except traci.TraCIException:
                continue

        # Calculate directional averages
        for d, data in directional_data.items():
            count = len(data["vehicles"])
            if count > 0:
                total_speed = sum(v["speed_kmh"] for v in data["vehicles"])
                data["avg_speed"] = round(total_speed / count, 1)
            else:
                data["avg_speed"] = 0.0
            data["waiting_time"] = round(data["waiting_time"], 1)

        self.cumulative_waiting_time += total_waiting_time

        telemetry = {
            "step": self.step_count,
            "simulation_time_sec": round(self.current_time, 2),
            "traffic_light": {
                "id": self.tl_id,
                "current_phase": self.current_phase,
                "phase_name": self.get_phase_name(),
                "state_string": self.get_phase_state_string(),
                "phase_elapsed_sec": round(self.phase_step_timer * self.step_length, 1)
            },
            "metrics": {
                "active_vehicles": len(vehicle_ids),
                "total_departed": self.total_departed,
                "total_arrived": self.total_arrived,
                "total_waiting_time_sec": round(total_waiting_time, 1),
                "cumulative_waiting_time_sec": round(self.cumulative_waiting_time, 1),
            },
            "directional": directional_data,
            "vehicles": all_vehicles
        }
        return telemetry

    def close(self):
        """Close TraCI simulation instance."""
        if self.is_running:
            try:
                traci.close()
            except Exception:
                pass
            self.is_running = False

    def restart(self):
        """Cleanly restart simulation from step 0."""
        self.vehicle_id_map.clear()
        self.next_vid_num = 1
        self.close()
        self.start()

if __name__ == "__main__":
    print("Testing SumoSimulationRunner for 50 steps...")
    runner = SumoSimulationRunner(use_gui=False)
    runner.start()
    
    for i in range(50):
        # Switch phase at step 25 to test dynamic signal control
        if i == 25:
            print("  Switching to Phase EW_GREEN at step 25...")
            runner.set_phase(PHASE_EW_GREEN)
            
        data = runner.step()
        if i % 10 == 0 or i == 49:
            tl = data["traffic_light"]
            m = data["metrics"]
            print(f"Step {data['step']:03d} (t={data['simulation_time_sec']}s): Active={m['active_vehicles']}, Departed={m['total_departed']}, Phase={tl['phase_name']}")
            
    runner.close()
    print("Simulation runner verified successfully.")

