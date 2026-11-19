"""
Adaptive Traffic Controller using Trained Deep Q-Network (DQN).
Monitors all 5 city junctions, feeds multi-junction state vectors into the neural network,
actuates signal phases for 4 Central Plaza corridors and satellite crossroads,
and outputs explainable AI diagnostics for live streaming.
"""

import os
import sys
import torch
from typing import Dict, Any, Optional, List

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from backend.config import DQN_MODEL_PATH, SIMULATION_STEP_LENGTH
from backend.rlagent.city_dqn_agent import CityDQNAgent
from backend.controllers.multi_junction_fixed import MultiJunctionFixedController

# 4 Central Plaza Corridors exactly matching city.net.xml (20 total phases)
CENTRAL_CORRIDORS = {
    0: {"main_green": 0,  "yellow": 1,  "left_green": 2,  "left_yellow": 3,  "all_red": 4,  "desc": "North-South Corridor"},
    1: {"main_green": 5,  "yellow": 6,  "left_green": 7,  "left_yellow": 8,  "all_red": 9,  "desc": "East-West Arterial"},
    2: {"main_green": 10, "yellow": 11, "left_green": 12, "left_yellow": 13, "all_red": 14, "desc": "NW-SE Diagonal Avenue"},
    3: {"main_green": 15, "yellow": 16, "left_green": 17, "left_yellow": 18, "all_red": 19, "desc": "NE-SW Diagonal Avenue"}
}

CLASS_WEIGHTS = {"car": 1.0, "motorcycle": 0.6, "bus": 2.5, "truck": 1.8}

class AdaptiveCityController:
    """
    Trained Reinforcement Learning Traffic Controller for the Connected Smart City.
    Actuates signals adaptively based on real-time vehicle queues, delays, and vehicle class priorities.
    """
    def __init__(self, step_length: float = SIMULATION_STEP_LENGTH):
        self.step_length = step_length
        self.agent = CityDQNAgent(state_dim=32, action_dim=4)
        
        # Load trained model weights
        if os.path.exists(DQN_MODEL_PATH):
            try:
                self.agent.load(DQN_MODEL_PATH)
                self.model_loaded = True
            except Exception as e:
                print(f"AdaptiveCityController: Error loading weights from {DQN_MODEL_PATH}: {e}")
                self.model_loaded = False
        else:
            self.model_loaded = False

        # TL_CENTRAL State Machine
        self.current_corridor = 1  # Start at East-West Arterial (primary trunk)
        self.stage = "MAIN_GREEN"   # MAIN_GREEN, MAIN_YELLOW, LEFT_GREEN, LEFT_YELLOW, ALL_RED
        self.stage_timer = 0.0
        self.target_corridor = 1

        # Synchronized satellite controller
        self.satellite_controller = MultiJunctionFixedController(step_length=step_length)

        self.last_action = 1
        self.last_explanation = "DQN Adaptive Controller initialized. Monitoring connected city traffic."
        self.switches_count = 0
        self.extensions_count = 0

    def reset(self):
        """Reset internal phase timers."""
        self.current_corridor = 1
        self.stage = "MAIN_GREEN"
        self.stage_timer = 0.0
        self.last_action = 1
        self.switches_count = 0
        self.extensions_count = 0
        self.satellite_controller = MultiJunctionFixedController(step_length=self.step_length)

    def step(self, telemetry: Dict[str, Any], city_runner: Any) -> Dict[str, int]:
        """
        Advance one decision step.
        Computes 32-dim state, queries DQN policy, actuates TL_CENTRAL & satellites,
        and generates explainable AI diagnostics.
        """
        state = self._extract_state(telemetry)
        vehs = telemetry.get("vehicles", [])
        m = telemetry.get("metrics", {})
        tot_q = m.get("total_queued", 0)
        target_phases = {}

        # 1. Advance Satellite Crossroads via coordinated cycle
        sat_phases = self.satellite_controller.step()
        for sat_tl in ["TL_NW", "TL_NE", "TL_SW", "TL_SE"]:
            city_runner.set_tl_phase(sat_tl, sat_phases[sat_tl])
            target_phases[sat_tl] = sat_phases[sat_tl]

        # 2. Extract Corridor Queues for Central Plaza
        q0 = sum(CLASS_WEIGHTS.get(v.get("class","car"), 1.0) for v in vehs if v.get("is_queued") and ("midn" in v.get("edge","").lower() or "mids" in v.get("edge","").lower()))
        q1 = sum(CLASS_WEIGHTS.get(v.get("class","car"), 1.0) for v in vehs if v.get("is_queued") and ("tjunc" in v.get("edge","").lower() or "rb_to_central" in v.get("edge","").lower()))
        q2 = sum(CLASS_WEIGHTS.get(v.get("class","car"), 1.0) for v in vehs if v.get("is_queued") and ("nw_to_central" in v.get("edge","").lower() or "se_to_central" in v.get("edge","").lower()))
        q3 = sum(CLASS_WEIGHTS.get(v.get("class","car"), 1.0) for v in vehs if v.get("is_queued") and ("ne_to_central" in v.get("edge","").lower() or "sw_to_central" in v.get("edge","").lower()))
        corridor_queues = {0: q0, 1: q1, 2: q2, 3: q3}
        self.last_corridor_queues = corridor_queues

        self.stage_timer += self.step_length
        grp = CENTRAL_CORRIDORS[self.current_corridor]

        # 3. Central Plaza Signal State Machine
        if self.stage == "MAIN_GREEN":
            # Query DQN agent
            action = self.agent.select_action(state, eval_mode=True)
            self.last_action = action

            # Dynamic Green Duration: if current corridor has heavy queue, allow extended green to flush it
            min_g = 5.0 if self.current_corridor in [0, 2] else 6.0
            cur_q = corridor_queues[self.current_corridor]
            max_g = 26.0 if cur_q >= 6.0 else (12.0 if self.current_corridor in [0, 2] else 18.0)
            
            max_other_q = max(corridor_queues[g] for g in corridor_queues if g != self.current_corridor)
            heaviest_other = max([g for g in [0, 1, 2, 3] if g != self.current_corridor], key=lambda g: corridor_queues[g])

            should_switch = False
            # Check smart queue relief: if opposing corridor has heavy traffic, switch immediately once min_g met
            if self.stage_timer >= min_g and corridor_queues[heaviest_other] >= 6.0 and cur_q < 4.0:
                should_switch = True
                self.target_corridor = heaviest_other
                self.last_explanation = (
                    f"⚡ SMART AUTO-CORRECTION: Heavy traffic detected on {CENTRAL_CORRIDORS[heaviest_other]['desc']} "
                    f"({corridor_queues[heaviest_other]:.0f} queued) → Switching signal to GREEN to clear congestion!"
                )
            # Check maximum green constraint
            elif self.stage_timer >= max_g:
                should_switch = True
                self.target_corridor = heaviest_other
                self.last_explanation = f"DQN Max-Green Gate: {grp['desc']} reached {max_g}s limit. Transitioning to clear cross queues."
            # Check dynamic queue relief (approach cleared)
            elif self.stage_timer >= min_g and cur_q == 0 and max_other_q > 0:
                should_switch = True
                self.target_corridor = heaviest_other
                self.last_explanation = f"DQN Queue Depletion: {grp['desc']} queue cleared; transitioning early to relieve waiting traffic."
            # Check explicit DQN recommendation
            elif self.stage_timer >= min_g and action != self.current_corridor and corridor_queues[action] >= 2.0:
                should_switch = True
                self.target_corridor = action
                self.last_explanation = f"DQN Decision: Priority switch selected for {CENTRAL_CORRIDORS[action]['desc']} ({corridor_queues[action]:.0f} waiting)."

            if should_switch:
                self.stage = "MAIN_YELLOW"
                self.stage_timer = 0.0
                city_runner.set_tl_phase("TL_CENTRAL", grp["yellow"])
                target_phases["TL_CENTRAL"] = grp["yellow"]
            else:
                self.extensions_count += 1
                city_runner.set_tl_phase("TL_CENTRAL", grp["main_green"])
                target_phases["TL_CENTRAL"] = grp["main_green"]
                if not "Max-Green" in self.last_explanation and not "Queue" in self.last_explanation:
                    self.last_explanation = (
                        f"DQN Decision: Holding green on {grp['desc']} (active {round(self.stage_timer, 1)}s). "
                        f"Discharging active traffic stream; {tot_q} vehicles queued across network."
                    )

        elif self.stage == "MAIN_YELLOW":
            if self.stage_timer >= 2.5:
                self.stage = "LEFT_GREEN"
                self.stage_timer = 0.0
                city_runner.set_tl_phase("TL_CENTRAL", grp["left_green"])
                target_phases["TL_CENTRAL"] = grp["left_green"]
            else:
                city_runner.set_tl_phase("TL_CENTRAL", grp["yellow"])
                target_phases["TL_CENTRAL"] = grp["yellow"]

        elif self.stage == "LEFT_GREEN":
            if self.stage_timer >= 3.5:
                self.stage = "LEFT_YELLOW"
                self.stage_timer = 0.0
                city_runner.set_tl_phase("TL_CENTRAL", grp["left_yellow"])
                target_phases["TL_CENTRAL"] = grp["left_yellow"]
            else:
                city_runner.set_tl_phase("TL_CENTRAL", grp["left_green"])
                target_phases["TL_CENTRAL"] = grp["left_green"]

        elif self.stage == "LEFT_YELLOW":
            if self.stage_timer >= 2.0:
                self.stage = "ALL_RED"
                self.stage_timer = 0.0
                city_runner.set_tl_phase("TL_CENTRAL", grp["all_red"])
                target_phases["TL_CENTRAL"] = grp["all_red"]
            else:
                city_runner.set_tl_phase("TL_CENTRAL", grp["left_yellow"])
                target_phases["TL_CENTRAL"] = grp["left_yellow"]

        elif self.stage == "ALL_RED":
            if self.stage_timer >= 1.0:
                # Select target corridor: prioritize highest queue or explicit target corridor
                best_corridor = max([0, 1, 2, 3], key=lambda g: corridor_queues[g])
                if corridor_queues[best_corridor] >= 3.0 and best_corridor != self.current_corridor:
                    self.current_corridor = best_corridor
                elif hasattr(self, 'target_corridor') and self.target_corridor != self.current_corridor:
                    self.current_corridor = self.target_corridor
                else:
                    self.current_corridor = (self.current_corridor + 1) % 4

                self.stage = "MAIN_GREEN"
                self.stage_timer = 0.0
                self.switches_count += 1
                new_grp = CENTRAL_CORRIDORS[self.current_corridor]
                city_runner.set_tl_phase("TL_CENTRAL", new_grp["main_green"])
                target_phases["TL_CENTRAL"] = new_grp["main_green"]
                self.last_explanation = f"⚡ SMART SIGNAL ACTUATION: Priority green granted to {new_grp['desc']} ({corridor_queues[self.current_corridor]:.0f} waiting) to flush congestion."
            else:
                city_runner.set_tl_phase("TL_CENTRAL", grp["all_red"])
                target_phases["TL_CENTRAL"] = grp["all_red"]

        return target_phases

    def _extract_state(self, telemetry: Dict[str, Any]) -> list:
        vehs = telemetry.get("vehicles", [])
        tls = telemetry.get("traffic_lights", {})
        rb = telemetry.get("roundabout", {})
        tj = telemetry.get("t_junction", {})
        metrics = telemetry.get("metrics", {})

        q0 = sum(CLASS_WEIGHTS.get(v.get("class","car"), 1.0) for v in vehs if v.get("is_queued", False) and ("midn" in v.get("edge","").lower() or "mids" in v.get("edge","").lower()))
        q1 = sum(CLASS_WEIGHTS.get(v.get("class","car"), 1.0) for v in vehs if v.get("is_queued", False) and ("tjunc" in v.get("edge","").lower() or "rb_to_central" in v.get("edge","").lower()))
        q2 = sum(CLASS_WEIGHTS.get(v.get("class","car"), 1.0) for v in vehs if v.get("is_queued", False) and ("nw_to_central" in v.get("edge","").lower() or "se_to_central" in v.get("edge","").lower()))
        q3 = sum(CLASS_WEIGHTS.get(v.get("class","car"), 1.0) for v in vehs if v.get("is_queued", False) and ("ne_to_central" in v.get("edge","").lower() or "sw_to_central" in v.get("edge","").lower()))

        state = [
            min(1.0, q0 / 35.0),
            min(1.0, q1 / 35.0),
            min(1.0, q2 / 35.0),
            min(1.0, q3 / 35.0),
            float(self.current_corridor) / 3.0,
            min(1.0, self.stage_timer / 25.0),
            1.0 if self.stage in ["MAIN_YELLOW", "LEFT_YELLOW", "ALL_RED"] else 0.0,
            min(1.0, tls.get("TL_NW", {}).get("queued_vehicles", 0) / 25.0),
            min(1.0, tls.get("TL_NE", {}).get("queued_vehicles", 0) / 25.0),
            min(1.0, tls.get("TL_SW", {}).get("queued_vehicles", 0) / 25.0),
            min(1.0, tls.get("TL_SE", {}).get("queued_vehicles", 0) / 25.0),
            1.0 if tls.get("TL_NW", {}).get("primary_color") == "GREEN" else 0.0,
            1.0 if tls.get("TL_NE", {}).get("primary_color") == "GREEN" else 0.0,
            1.0 if tls.get("TL_SW", {}).get("primary_color") == "GREEN" else 0.0,
            1.0 if tls.get("TL_SE", {}).get("primary_color") == "GREEN" else 0.0,
            min(1.0, rb.get("circulating_count", 0) / 15.0),
            min(1.0, rb.get("entry_queue_count", 0) / 10.0),
            min(1.0, rb.get("avg_speed_kmh", 0.0) / 50.0),
            min(1.0, tj.get("active_count", 0) / 20.0),
            min(1.0, tj.get("queue_count", 0) / 15.0),
            min(1.0, metrics.get("total_active", 0) / 200.0),
            min(1.0, metrics.get("total_queued", 0) / 100.0),
            min(1.0, metrics.get("queue_ratio_pct", 0.0) / 100.0),
            min(1.0, metrics.get("average_speed_kmh", 0.0) / 50.0),
            min(1.0, metrics.get("congestion_pct", 0.0) / 100.0),
            min(1.0, metrics.get("total_waiting_seconds", 0.0) / 2500.0),
            min(1.0, metrics.get("class_counts", {}).get("bus", 0) / 10.0),
            min(1.0, metrics.get("class_counts", {}).get("truck", 0) / 10.0),
            min(1.0, metrics.get("class_counts", {}).get("motorcycle", 0) / 25.0),
            min(1.0, metrics.get("class_counts", {}).get("car", 0) / 150.0),
            min(1.0, telemetry.get("total_arrived", 0) / 100.0),
            min(1.0, telemetry.get("total_departed", 0) / 300.0)
        ]
        return state[:32]

    def get_info(self) -> Dict[str, Any]:
        """Provides rich metadata for the frontend Live AI explanation card."""
        grp = CENTRAL_CORRIDORS.get(self.current_corridor, CENTRAL_CORRIDORS[1])
        return {
            "mode": "AI_ADAPTIVE",
            "name": "DQN Deep Reinforcement Learning Adaptive Controller",
            "model_status": "ONLINE" if self.model_loaded else "HEURISTIC_BACKUP",
            "active_phase_group": self.current_corridor,
            "phase_description": grp["desc"],
            "stage": self.stage,
            "stage_elapsed_sec": round(self.stage_timer, 1),
            "is_transitioning": self.stage in ["MAIN_YELLOW", "LEFT_YELLOW", "ALL_RED"],
            "last_action_code": self.last_action,
            "total_phase_switches": self.switches_count,
            "total_green_extensions": self.extensions_count,
            "explanation": self.last_explanation
        }

    def get_heaviest_corridor(self) -> int:
        """Returns the corridor ID with the largest waiting queue at Central Plaza."""
        if hasattr(self, 'last_corridor_queues') and self.last_corridor_queues:
            return max(self.last_corridor_queues.keys(), key=lambda k: self.last_corridor_queues[k])
        return 0
