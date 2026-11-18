"""
Multi-Junction Fixed-Time Traffic Signal Controller for TRAFFIC INTEL.
Controls all 5 signalized crossroads (TL_CENTRAL, TL_NW, TL_NE, TL_SW, TL_SE)
using static, predetermined green/yellow/red timing intervals.
Does not react to real-time queues, vehicle classes, or traffic density.
Serves as the rigorous benchmark baseline for evaluating Reinforcement Learning (DQN).
"""

import os
import sys
from typing import Dict, List, Any, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from backend.config import SIMULATION_STEP_LENGTH

class MultiJunctionFixedController:
    """
    Conventional Pre-timed Static Signal Controller for all 5 city intersections.
    Each junction executes its standard static phase schedule independently on fixed timers.
    """
    def __init__(self, step_length: float = SIMULATION_STEP_LENGTH):
        self.step_length = step_length
        self.tl_ids = ["TL_CENTRAL", "TL_NW", "TL_NE", "TL_SW", "TL_SE"]
        
        # Standard static phase plans exactly matching city.net.xml tlLogics
        self.phase_plans = {
            "TL_CENTRAL": [
                (8.0, "North-South Main Corridor Green"),
                (3.0, "North-South Yellow"),
                (6.0, "North-South Left-Turn Green"),
                (3.0, "North-South Left-Turn Yellow"),
                (1.0, "All-Red Clearance"),
                (10.0, "East-West Main Corridor Green"),
                (3.0, "East-West Yellow"),
                (6.0, "East-West Left-Turn Green"),
                (3.0, "East-West Left-Turn Yellow"),
                (1.0, "All-Red Clearance"),
                (10.0, "NW-SE Diagonal Avenue Green"),
                (3.0, "NW-SE Yellow"),
                (6.0, "NW-SE Left-Turn Green"),
                (3.0, "NW-SE Left-Turn Yellow"),
                (1.0, "All-Red Clearance"),
                (10.0, "NE-SW Diagonal Avenue Green"),
                (3.0, "NE-SW Yellow"),
                (6.0, "NE-SW Left-Turn Green"),
                (3.0, "NE-SW Left-Turn Yellow"),
                (1.0, "All-Red Clearance"),
            ],
            "TL_NE": [
                (38.0, "North Gate Approach Green"),
                (3.0, "North Gate Yellow"),
                (37.0, "Central Corridor Green"),
                (3.0, "Central Corridor Yellow"),
                (6.0, "Left-Turn Movement Green"),
                (3.0, "Left-Turn Movement Yellow")
            ],
            "TL_NW": [
                (20.0, "North Gate Inbound Green"),
                (3.0, "North Gate Yellow"),
                (6.0, "Left Turn Green"),
                (3.0, "Left Turn Yellow"),
                (21.0, "West Corridor Inbound Green"),
                (3.0, "West Corridor Yellow"),
                (6.0, "Left Turn Green"),
                (3.0, "Left Turn Yellow"),
                (21.0, "Central Connector Green"),
                (3.0, "Central Connector Yellow"),
                (1.0, "All-Red Clearance")
            ],
            "TL_SE": [
                (42.0, "South Gate Inbound Green"),
                (3.0, "South Gate Yellow"),
                (42.0, "Central Boulevard Inbound Green"),
                (3.0, "Central Boulevard Yellow")
            ],
            "TL_SW": [
                (20.0, "South Gate Inbound Green"),
                (3.0, "South Gate Yellow"),
                (6.0, "Left Turn Green"),
                (3.0, "Left Turn Yellow"),
                (1.0, "All-Red Clearance"),
                (21.0, "West Corridor Inbound Green"),
                (3.0, "West Corridor Yellow"),
                (6.0, "Left Turn Green"),
                (3.0, "Left Turn Yellow"),
                (21.0, "Central Connector Green"),
                (3.0, "Central Connector Yellow")
            ]
        }

        # Dynamic state per junction
        self.junction_states = {}
        self.reset()

    def reset(self):
        """Reset all junction timers and cycle pointers."""
        for tlid in self.tl_ids:
            plan = self.phase_plans[tlid]
            self.junction_states[tlid] = {
                "phase_idx": 0,
                "elapsed_sec": 0.0,
                "target_dur": plan[0][0],
                "description": plan[0][1],
                "completed_cycles": 0
            }

    def step(self, telemetry: Optional[Dict[str, Any]] = None) -> Dict[str, int]:
        """
        Advance one simulation step on all 5 junctions.
        Returns a dict mapping junction ID -> target phase index.
        """
        target_phases = {}

        for tlid in self.tl_ids:
            state = self.junction_states[tlid]
            plan = self.phase_plans[tlid]
            state["elapsed_sec"] += self.step_length

            # Check if static timer expired
            if state["elapsed_sec"] >= state["target_dur"]:
                state["elapsed_sec"] = 0.0
                state["phase_idx"] = (state["phase_idx"] + 1) % len(plan)
                dur, desc = plan[state["phase_idx"]]
                state["target_dur"] = dur
                state["description"] = desc
                if state["phase_idx"] == 0:
                    state["completed_cycles"] += 1

            target_phases[tlid] = state["phase_idx"]

        return target_phases

    def get_info(self) -> Dict[str, Any]:
        """Returns diagnostic and explanation metadata for UI and logging."""
        central = self.junction_states.get("TL_CENTRAL", {})
        rem = max(0.0, round(central.get("target_dur", 10.0) - central.get("elapsed_sec", 0.0), 1))
        
        return {
            "mode": "FIXED_TIME",
            "name": "Multi-Junction Fixed-Time Baseline Controller",
            "active_intersections": len(self.tl_ids),
            "central_phase": central.get("phase_idx", 0),
            "central_elapsed_sec": round(central.get("elapsed_sec", 0.0), 1),
            "central_duration": central.get("target_dur", 10.0),
            "explanation": (
                f"Fixed-Time Baseline: Operating strict sequential pre-timed cycles across all 5 junctions. "
                f"Central Plaza at Phase #{central.get('phase_idx', 0)} ({central.get('description', '')}). "
                f"Next scheduled switch in {rem}s regardless of incoming vehicle density or queues."
            ),
            "junction_states": {
                tl: {
                    "phase": self.junction_states[tl]["phase_idx"],
                    "elapsed": round(self.junction_states[tl]["elapsed_sec"], 1),
                    "duration": self.junction_states[tl]["target_dur"],
                    "desc": self.junction_states[tl]["description"]
                }
                for tl in self.tl_ids
            }
        }
