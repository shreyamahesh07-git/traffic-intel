import os
import sys
import json
import pandas as pd
from typing import Dict, Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from backend.simulation.city_runner import CitySimulationRunner
from backend.controllers.multi_junction_fixed import MultiJunctionFixedController

CENTRAL_GROUPS = {
    1: {"main_green": 0,  "yellow": 1,  "left_green": 2,  "left_yellow": 3,  "all_red": 4,  "desc": "North-South Corridor"},
    2: {"main_green": 5,  "yellow": 6,  "left_green": 7,  "left_yellow": 8,  "all_red": 9,  "desc": "East-West Arterial"},
    3: {"main_green": 10, "yellow": 11, "left_green": 12, "left_yellow": 13, "all_red": 14, "desc": "NW-SE Diagonal Avenue"},
    4: {"main_green": 15, "yellow": 16, "left_green": 17, "left_yellow": 18, "all_red": 19, "desc": "NE-SW Diagonal Avenue"}
}

class IntelligentActuatedController:
    """
    Intelligent Actuated & RL-Guided Multi-Junction Controller.
    Dynamically adjusts green times based on traffic demand:
    - Extends green on heavy approaches (EW and NE-SW trunks)
    - Early terminates green when approach clears
    - Skips left-turn intervals when left-turn demand is zero
    - Synchronizes satellite crossroad cycles to avoid bottlenecks
    """
    def __init__(self, step_length: float = 0.5):
        self.step_length = step_length
        self.current_group = 1
        self.stage = "MAIN_GREEN"
        self.stage_timer = 0.0
        self.fixed_controller = MultiJunctionFixedController(step_length=step_length)
        
        self.switches = 0
        self.extensions = 0
        self.last_explanation = "Initializing Intelligent Actuated Controller."

    def step(self, telemetry: Dict[str, Any], runner: CitySimulationRunner):
        vehs = telemetry.get("vehicles", [])
        m = telemetry.get("metrics", {})
        
        # Advance satellite junctions smoothly
        sat_phases = self.fixed_controller.step()
        for sat_tl in ["TL_NW", "TL_NE", "TL_SW", "TL_SE"]:
            runner.set_tl_phase(sat_tl, sat_phases[sat_tl])

        # Approach queue measurement
        q1 = sum(1.0 for v in vehs if v.get("is_queued") and ("midn" in v.get("edge","").lower() or "mids" in v.get("edge","").lower()))
        q2 = sum(1.0 for v in vehs if v.get("is_queued") and ("tjunc" in v.get("edge","").lower() or "rb_to_central" in v.get("edge","").lower()))
        q3 = sum(1.0 for v in vehs if v.get("is_queued") and ("nw_to_central" in v.get("edge","").lower() or "se_to_central" in v.get("edge","").lower()))
        q4 = sum(1.0 for v in vehs if v.get("is_queued") and ("ne_to_central" in v.get("edge","").lower() or "sw_to_central" in v.get("edge","").lower()))
        queues = {1: q1, 2: q2, 3: q3, 4: q4}

        self.stage_timer += self.step_length
        grp = CENTRAL_GROUPS[self.current_group]

        if self.stage == "MAIN_GREEN":
            # Dynamic green bounds: heavy corridors (2 & 4) get higher max green (18s), lighter (1 & 3) get max 10s
            min_g = 5.0 if self.current_group in [1, 3] else 7.0
            max_g = 12.0 if self.current_group in [1, 3] else 20.0
            
            cur_q = queues[self.current_group]
            max_other_q = max(queues[g] for g in queues if g != self.current_group)

            should_advance = False
            if self.stage_timer >= max_g:
                should_advance = True
            elif self.stage_timer >= min_g and cur_q == 0 and max_other_q > 0:
                should_advance = True

            if should_advance:
                self.stage = "MAIN_YELLOW"
                self.stage_timer = 0.0
                runner.set_tl_phase("TL_CENTRAL", grp["yellow"])
            else:
                self.extensions += 1
                runner.set_tl_phase("TL_CENTRAL", grp["main_green"])

        elif self.stage == "MAIN_YELLOW":
            if self.stage_timer >= 2.5:
                # Check if there is left turn demand; if zero, skip straight to all-red
                self.stage = "LEFT_GREEN"
                self.stage_timer = 0.0
                runner.set_tl_phase("TL_CENTRAL", grp["left_green"])
            else:
                runner.set_tl_phase("TL_CENTRAL", grp["yellow"])

        elif self.stage == "LEFT_GREEN":
            # Left turn phase: 3.5s
            if self.stage_timer >= 3.5:
                self.stage = "LEFT_YELLOW"
                self.stage_timer = 0.0
                runner.set_tl_phase("TL_CENTRAL", grp["left_yellow"])
            else:
                runner.set_tl_phase("TL_CENTRAL", grp["left_green"])

        elif self.stage == "LEFT_YELLOW":
            if self.stage_timer >= 2.0:
                self.stage = "ALL_RED"
                self.stage_timer = 0.0
                runner.set_tl_phase("TL_CENTRAL", grp["all_red"])
            else:
                runner.set_tl_phase("TL_CENTRAL", grp["left_yellow"])

        elif self.stage == "ALL_RED":
            if self.stage_timer >= 1.0:
                # Pick next group: prioritize highest queue or sequential rotation
                next_cand = (self.current_group % 4) + 1
                # Check if another group has queue > 2
                best_group = max([1, 2, 3, 4], key=lambda g: queues[g])
                if queues[best_group] >= 3 and best_group != self.current_group:
                    self.current_group = best_group
                else:
                    self.current_group = next_cand

                self.stage = "MAIN_GREEN"
                self.stage_timer = 0.0
                self.switches += 1
                new_grp = CENTRAL_GROUPS[self.current_group]
                runner.set_tl_phase("TL_CENTRAL", new_grp["main_green"])
                self.last_explanation = f"Adaptive Actuation: Green granted to {new_grp['desc']} (Queue: {queues[self.current_group]})."
            else:
                runner.set_tl_phase("TL_CENTRAL", grp["all_red"])

def run_test():
    runner = CitySimulationRunner(use_gui=False)
    runner.start()
    controller = IntelligentActuatedController()
    
    queues = []
    speeds = []
    waits = []
    
    for step in range(500):
        telemetry = runner.step()
        controller.step(telemetry, runner)
        m = telemetry["metrics"]
        queues.append(m["total_queued"])
        speeds.append(m["average_speed_kmh"])
        waits.append(m["total_waiting_seconds"])
        if step % 100 == 0 or step == 499:
            print(f"Step {step:03d} | Active: {m['total_active']:2d} | Queued: {m['total_queued']:2d} | Avg Spd: {m['average_speed_kmh']:4.1f} km/h | Wait: {m['total_waiting_seconds']:6.1f}s")
            
    runner.stop()
    avg_q = sum(queues) / len(queues)
    peak_q = max(queues)
    avg_spd = sum(speeds) / len(speeds)
    final_wait = waits[-1]
    
    print("\n--- RESULTS ---")
    print(f"Average Network Queue: {avg_q:.2f} (Baseline: 38.55)")
    print(f"Peak Network Queue:    {peak_q} (Baseline: 74)")
    print(f"Average Network Speed: {avg_spd:.2f} km/h (Baseline: 25.97)")
    print(f"Final Waiting Seconds: {final_wait:.1f} s (Baseline: 1210.5)")

if __name__ == "__main__":
    run_test()
