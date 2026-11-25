"""
Controlled Fixed-Time vs Adaptive DQN Comparison Runner.
Executes identical SUMO demand scenarios under both Fixed-Time and Adaptive DQN
controllers and computes actual observed performance metrics.
"""

import os
import sys
import time
from typing import Dict, Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from backend.controllers.multi_junction_fixed import MultiJunctionFixedController
from backend.controllers.adaptive_city_controller import AdaptiveCityController
from backend.simulation.city_runner import CitySimulationRunner


def run_controlled_comparison(scenario: str = "SURGE_NORTH", steps: int = 120) -> Dict[str, Any]:
    """
    Runs Fixed-Time and Adaptive DQN back-to-back on an isolated headless SUMO
    instance with identical traffic scenario and step count.
    """
    steps = max(40, min(300, int(steps)))
    results = {}

    for mode_key in ("FIXED_TIME", "AI_ADAPTIVE"):
        runner = CitySimulationRunner(use_gui=False)
        fixed_ctrl = MultiJunctionFixedController()
        adaptive_ctrl = AdaptiveCityController()

        wait_samples = []
        queue_samples = []
        speed_samples = []
        total_wait_acc = 0.0
        last_arrived = 0

        try:
            runner.start()
            runner.set_scenario(scenario)

            for _ in range(steps):
                telemetry = runner.step()
                if mode_key == "FIXED_TIME":
                    phases = fixed_ctrl.step()
                    for tlid, pidx in phases.items():
                        runner.set_tl_phase(tlid, pidx)
                else:
                    adaptive_ctrl.step(telemetry, runner)

                m = telemetry.get("metrics", {})
                active = max(1, m.get("total_active", 0))
                q = m.get("total_queued", 0)
                w = m.get("total_waiting_seconds", 0.0)
                spd = m.get("average_speed_kmh", 0.0)

                queue_samples.append(q)
                wait_samples.append(w / active)
                speed_samples.append(spd)
                total_wait_acc += w * runner.step_length
                last_arrived = telemetry.get("total_arrived", 0)
        finally:
            runner.stop()

        n = max(1, len(queue_samples))
        results[mode_key] = {
            "avg_waiting_time_sec": round(sum(wait_samples) / n, 2),
            "avg_queue_length": round(sum(queue_samples) / n, 2),
            "total_vehicles_served": int(last_arrived),
            "throughput_vph": round((last_arrived / max(1.0, steps * 0.5)) * 3600.0, 1),
            "avg_speed_kmh": round(sum(speed_samples) / n, 2),
            "total_time_waiting_sec": round(total_wait_acc, 1),
        }

    f = results["FIXED_TIME"]
    a = results["AI_ADAPTIVE"]

    def _pct_diff(base_val: float, new_val: float, lower_is_better: bool = True) -> float:
        if base_val <= 0:
            return 0.0
        diff = ((base_val - new_val) / base_val) * 100.0 if lower_is_better else ((new_val - base_val) / base_val) * 100.0
        return round(diff, 1)

    return {
        "scenario": scenario,
        "steps": steps,
        "sim_duration_sec": round(steps * 0.5, 1),
        "timestamp": time.time(),
        "data_source": "Simulation",
        "fixed_time": f,
        "adaptive_dqn": a,
        "deltas": {
            "waiting_time_reduction_pct": _pct_diff(f["avg_waiting_time_sec"], a["avg_waiting_time_sec"], True),
            "queue_reduction_pct": _pct_diff(f["avg_queue_length"], a["avg_queue_length"], True),
            "speed_improvement_pct": _pct_diff(f["avg_speed_kmh"], a["avg_speed_kmh"], False),
            "throughput_change_pct": _pct_diff(f["throughput_vph"], a["throughput_vph"], False),
        },
    }
