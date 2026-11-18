import os
import sys
import numpy as np
from typing import Dict, List, Tuple, Any, Optional

# Load backend configuration
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from backend.config import (
    MAX_GREEN_DURATION,
    MIN_GREEN_DURATION
)

# Directional edge mapping
APPROACH_EDGES = {
    "NORTH": "N2C",
    "SOUTH": "S2C",
    "EAST": "E2C",
    "WEST": "W2C"
}

# Maximum theoretical approach capacity (150m road, 3 lanes)
APPROACH_MAX_CAPACITY = 30.0  # nominal saturation vehicle count
MAX_QUEUE_NORMALIZER = 25.0    # max queue for state normalization
MAX_WAIT_NORMALIZER = 120.0   # max waiting time in seconds for normalization

# Density Categories
DENSITY_LOW = "LOW"
DENSITY_MEDIUM = "MEDIUM"
DENSITY_HIGH = "HIGH"
DENSITY_CONGESTED = "CONGESTED"

class TrafficDensityEstimator:
    """
    Directional Traffic Density, Queue Length, and Congestion Estimator.
    Computes real-time traffic density metrics per approach and compiles
    normalized state vectors for Deep Q-Network (DQN) signal optimization.
    """
    def __init__(self, speed_threshold_kmh: float = 1.0):
        # Vehicles moving slower than 1.0 km/h (0.28 m/s) are counted in queue
        self.speed_threshold_kmh = speed_threshold_kmh
        self.history_records: List[Dict[str, Any]] = []

    def compute_density(self, telemetry: Dict[str, Any]) -> Dict[str, Any]:
        """
        Analyzes simulation telemetry to compute directional queue length,
        waiting times, density scores, and congestion categories.
        """
        directional_telemetry = telemetry.get("directional", {})
        vehicles = telemetry.get("vehicles", [])
        tl_info = telemetry.get("traffic_light", {})
        
        # Group vehicles by approach edge
        vehicles_by_edge: Dict[str, List[Dict[str, Any]]] = {
            "N2C": [], "S2C": [], "E2C": [], "W2C": []
        }
        for v in vehicles:
            edge = v.get("edge_id", "")
            if edge in vehicles_by_edge:
                vehicles_by_edge[edge].append(v)

        directional_density: Dict[str, Dict[str, Any]] = {}
        total_intersection_queue = 0
        total_intersection_wait = 0.0

        for direction, edge_id in APPROACH_EDGES.items():
            app_vehs = vehicles_by_edge[edge_id]
            veh_count = len(app_vehs)
            
            # Queue detection: vehicles on inbound approach with speed < threshold
            queued_vehs = [v for v in app_vehs if v.get("speed_kmh", 0.0) < self.speed_threshold_kmh]
            queue_count = len(queued_vehs)
            total_intersection_queue += queue_count

            # Physical queue length in meters (estimating space taken on road)
            # Car=7.5m, Bus=15m, Truck=13.5m, Moto=3.7m with gaps
            queue_meters = sum(
                15.0 if v.get("type") == "bus" else
                13.5 if v.get("type") == "truck" else
                3.7 if v.get("type") == "motorcycle" else 7.5
                for v in queued_vehs
            )
            # Multi-lane distribution: divide by 3 lanes
            queue_length_meters = round(queue_meters / 3.0, 1) if queue_meters > 0 else 0.0

            # Waiting time metrics (seconds)
            wait_times = [v.get("waiting_time", 0.0) for v in app_vehs]
            total_wait_sec = round(sum(wait_times), 1)
            total_intersection_wait += total_wait_sec
            avg_wait_sec = round(total_wait_sec / veh_count, 1) if veh_count > 0 else 0.0
            max_wait_sec = round(max(wait_times), 1) if wait_times else 0.0

            # Average approach speed
            speeds = [v.get("speed_kmh", 0.0) for v in app_vehs]
            avg_speed_kmh = round(sum(speeds) / veh_count, 1) if veh_count > 0 else 50.0

            # Normalized density score [0.0 - 1.0]
            # Blend vehicle volume ratio (40%) and queue ratio (60%)
            vol_ratio = min(1.0, veh_count / APPROACH_MAX_CAPACITY)
            queue_ratio = min(1.0, queue_count / (APPROACH_MAX_CAPACITY * 0.75))
            density_score = round(0.4 * vol_ratio + 0.6 * queue_ratio, 3)

            # Density Category Classification
            if density_score >= 0.75 or queue_count >= 10 or max_wait_sec >= 45.0:
                category = DENSITY_CONGESTED
                is_congested = True
            elif density_score >= 0.50 or queue_count >= 6:
                category = DENSITY_HIGH
                is_congested = False
            elif density_score >= 0.25 or queue_count >= 3:
                category = DENSITY_MEDIUM
                is_congested = False
            else:
                category = DENSITY_LOW
                is_congested = False

            directional_density[direction] = {
                "approach": direction,
                "edge_id": edge_id,
                "vehicle_count": veh_count,
                "queue_count": queue_count,
                "queue_length_meters": queue_length_meters,
                "total_waiting_time_sec": total_wait_sec,
                "avg_waiting_time_sec": avg_wait_sec,
                "max_waiting_time_sec": max_wait_sec,
                "avg_speed_kmh": avg_speed_kmh,
                "density_score": density_score,
                "density_category": category,
                "is_congested": is_congested
            }

        # Build normalized 16-dimensional DQN State Representation Vector
        dqn_state = self.extract_dqn_state(directional_density, tl_info)

        # Congestion summary
        congested_approaches = [d for d, val in directional_density.items() if val["is_congested"]]

        result = {
            "step": telemetry.get("step", 0),
            "simulation_time_sec": telemetry.get("simulation_time_sec", 0.0),
            "total_intersection_queue": total_intersection_queue,
            "total_intersection_wait_sec": round(total_intersection_wait, 1),
            "congested_approaches": congested_approaches,
            "has_bottleneck": len(congested_approaches) > 0,
            "directional": directional_density,
            "dqn_state": dqn_state
        }
        return result

    def extract_dqn_state(self, directional_density: Dict[str, Dict[str, Any]], tl_info: Dict[str, Any]) -> List[float]:
        """
        Compiles a normalized 16-element continuous feature vector for the DQN agent:
        [0..3]: Normalized queue lengths (N, S, E, W)
        [4..7]: Normalized total waiting times (N, S, E, W)
        [8..11]: Density scores [0..1] (N, S, E, W)
        [12]: Current traffic light phase (normalized: phase / 5.0)
        [13]: Phase elapsed duration (normalized: elapsed / 60.0)
        [14]: Combined North-South queue ratio vs Total queue
        [15]: Combined East-West queue ratio vs Total queue
        """
        dirs = ["NORTH", "SOUTH", "EAST", "WEST"]
        
        # 1. Normalized Queues
        norm_queues = [
            min(1.0, directional_density[d]["queue_count"] / MAX_QUEUE_NORMALIZER)
            for d in dirs
        ]
        
        # 2. Normalized Waiting Times
        norm_waits = [
            min(1.0, directional_density[d]["total_waiting_time_sec"] / MAX_WAIT_NORMALIZER)
            for d in dirs
        ]
        
        # 3. Density Scores
        densities = [directional_density[d]["density_score"] for d in dirs]
        
        # 4. Phase and Timing features
        current_phase = tl_info.get("current_phase", 0)
        norm_phase = current_phase / 5.0
        phase_elapsed = tl_info.get("phase_elapsed_sec", 0.0)
        norm_elapsed = min(1.0, phase_elapsed / 60.0)

        # 5. Directional Balance Ratios
        ns_queue = directional_density["NORTH"]["queue_count"] + directional_density["SOUTH"]["queue_count"]
        ew_queue = directional_density["EAST"]["queue_count"] + directional_density["WEST"]["queue_count"]
        tot_queue = ns_queue + ew_queue
        ns_ratio = (ns_queue / tot_queue) if tot_queue > 0 else 0.5
        ew_ratio = (ew_queue / tot_queue) if tot_queue > 0 else 0.5

        state_vector = (
            norm_queues +         # 4 features
            norm_waits +          # 4 features
            densities +           # 4 features
            [norm_phase, norm_elapsed, round(ns_ratio, 3), round(ew_ratio, 3)] # 4 features
        )
        return [round(f, 4) for f in state_vector]

if __name__ == "__main__":
    from backend.simulation.sim_runner import SumoSimulationRunner
    
    print("Initializing TrafficDensityEstimator...")
    estimator = TrafficDensityEstimator()
    
    print("Testing density estimation over 30 continuous simulation steps...")
    runner = SumoSimulationRunner(use_gui=False)
    runner.start()
    
    for step in range(30):
        telemetry = runner.step()
        density_data = estimator.compute_density(telemetry)
        
        if (step + 1) % 10 == 0 or step == 29:
            print(f"\n--- Step {step + 1} (t={density_data['simulation_time_sec']}s) ---")
            print(f"Total Queue: {density_data['total_intersection_queue']} veh | Total Wait: {density_data['total_intersection_wait_sec']}s")
            print(f"Congested approaches: {density_data['congested_approaches']}")
            for d, vals in density_data["directional"].items():
                print(f"  {d:5s}: Count={vals['vehicle_count']:2d} | Queue={vals['queue_count']:2d} ({vals['queue_length_meters']:4.1f}m) | Wait={vals['total_waiting_time_sec']:5.1f}s | Speed={vals['avg_speed_kmh']:4.1f} km/h | Density={vals['density_score']:.2f} [{vals['density_category']}]")
            print(f"DQN State Vector (len={len(density_data['dqn_state'])}): {density_data['dqn_state']}")

    runner.close()
    print("\nPhase 4 TrafficDensityEstimator verified successfully!")

