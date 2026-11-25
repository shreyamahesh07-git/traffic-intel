"""
Independent Multi-Intersection Adaptive & Coordinated Traffic Controller.
Uses a shared PyTorch Dueling Double-DQN policy (state_dim=32, action_dim=4)
combined with per-intersection fairness constraints (Min Green, Max Green,
Max Red starvation prevention), queue + waiting-time scoring, safe 4-phase
SUMO transitions, and Green-Wave platoon coordination.
"""

import os
import sys
from typing import Dict, Any, Optional, List, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from backend.config import (
    DQN_MODEL_PATH,
    SIMULATION_STEP_LENGTH,
    MIN_GREEN_DURATION,
    MAX_GREEN_DURATION,
    MAX_RED_DURATION,
    YELLOW_PHASE_DURATION,
)
from backend.rlagent.city_dqn_agent import CityDQNAgent

CLASS_WEIGHTS = {"car": 1.0, "motorcycle": 0.6, "bus": 2.5, "truck": 1.8, "emergency": 4.0}

# Exact phase-to-edge mapping verified from city.net.xml <tlLogic> definitions.
# Every signalized junction in city.net.xml uses 4 phases:
#   0: Corridor 0 Green, 1: Corridor 0 Yellow, 2: Corridor 1 Green, 3: Corridor 1 Yellow.
INTERSECTION_SPECS: Dict[str, Dict[str, Any]] = {
    "TL_CENTRAL": {
        "name": "Central Plaza Crossroads",
        "center": [760.0, 440.0],
        "corridors": {
            0: {"green": 0, "yellow": 1, "desc": "North-South Boulevard", "edges": ["midN_to_central", "midS_to_central"]},
            1: {"green": 2, "yellow": 3, "desc": "East-West Arterial", "edges": ["rb_to_central", "tjunc_to_central"]},
        },
        "upstream_links": {
            0: [("GATE_MID_N", "midN_to_central", 240.0), ("GATE_MID_S", "midS_to_central", 240.0)],
            1: [("RB_E", "rb_to_central", 490.0), ("TJUNC_EAST", "tjunc_to_central", 480.0)],
        },
        "neighbors": ["TL_NW", "TL_NE", "TL_SW", "TL_SE"],
    },
    "TL_NW": {
        "name": "Northwest Commercial (TL_NW)",
        "center": [440.0, 680.0],
        "corridors": {
            0: {"green": 0, "yellow": 1, "desc": "North-South Parkway", "edges": ["gateNW_to_nw", "sw_to_nw"]},
            1: {"green": 2, "yellow": 3, "desc": "East-West Avenue", "edges": ["midN_to_nw", "rb_to_nw"]},
        },
        "upstream_links": {
            0: [("TL_SW", "sw_to_nw", 480.0)],
            1: [("GATE_MID_N", "midN_to_nw", 320.0), ("RB_N", "rb_to_nw", 290.0)],
        },
        "neighbors": ["TL_CENTRAL", "GATE_MID_N", "TL_SW", "TL_NE"],
    },
    "TL_NE": {
        "name": "Northeast Corporate (TL_NE)",
        "center": [1080.0, 680.0],
        "corridors": {
            0: {"green": 0, "yellow": 1, "desc": "North-East Highway", "edges": ["gateNE_to_ne", "tjunc_to_ne"]},
            1: {"green": 2, "yellow": 3, "desc": "Westbound Avenue", "edges": ["midN_to_ne"]},
        },
        "upstream_links": {
            0: [("TJUNC_EAST", "tjunc_to_ne", 288.0)],
            1: [("GATE_MID_N", "midN_to_ne", 320.0)],
        },
        "neighbors": ["TL_CENTRAL", "GATE_MID_N", "TL_SE", "TL_NW"],
    },
    "TL_SW": {
        "name": "Southwest Arterial (TL_SW)",
        "center": [440.0, 200.0],
        "corridors": {
            0: {"green": 0, "yellow": 1, "desc": "North-South Parkway", "edges": ["gateSW_to_sw", "nw_to_sw"]},
            1: {"green": 2, "yellow": 3, "desc": "East-West Avenue", "edges": ["midS_to_sw", "rb_to_sw"]},
        },
        "upstream_links": {
            0: [("TL_NW", "nw_to_sw", 480.0)],
            1: [("GATE_MID_S", "midS_to_sw", 320.0), ("RB_S", "rb_to_sw", 290.0)],
        },
        "neighbors": ["TL_CENTRAL", "GATE_MID_S", "TL_NW", "TL_SE"],
    },
    "TL_SE": {
        "name": "Southeast Logistics (TL_SE)",
        "center": [1080.0, 200.0],
        "corridors": {
            0: {"green": 0, "yellow": 1, "desc": "South-East Highway", "edges": ["gateSE_to_se", "tjunc_to_se"]},
            1: {"green": 2, "yellow": 3, "desc": "Westbound Avenue", "edges": ["midS_to_se"]},
        },
        "upstream_links": {
            0: [("TJUNC_EAST", "tjunc_to_se", 288.0)],
            1: [("GATE_MID_S", "midS_to_se", 320.0)],
        },
        "neighbors": ["TL_CENTRAL", "GATE_MID_S", "TL_NE", "TL_SW"],
    },
    "GATE_MID_N": {
        "name": "Mid-North Crossing",
        "center": [760.0, 680.0],
        "corridors": {
            0: {"green": 0, "yellow": 1, "desc": "North-South Spine", "edges": ["central_to_midN", "gateTop_to_midN"]},
            1: {"green": 2, "yellow": 3, "desc": "North Crosstown", "edges": ["ne_to_midN", "nw_to_midN"]},
        },
        "upstream_links": {
            0: [("TL_CENTRAL", "central_to_midN", 240.0)],
            1: [("TL_NE", "ne_to_midN", 320.0), ("TL_NW", "nw_to_midN", 320.0)],
        },
        "neighbors": ["TL_CENTRAL", "TL_NW", "TL_NE", "GATE_MID_S"],
    },
    "GATE_MID_S": {
        "name": "Mid-South Crossing",
        "center": [760.0, 200.0],
        "corridors": {
            0: {"green": 0, "yellow": 1, "desc": "North-South Spine", "edges": ["central_to_midS", "gateBot_to_midS"]},
            1: {"green": 2, "yellow": 3, "desc": "South Crosstown", "edges": ["se_to_midS", "sw_to_midS"]},
        },
        "upstream_links": {
            0: [("TL_CENTRAL", "central_to_midS", 240.0)],
            1: [("TL_SE", "se_to_midS", 320.0), ("TL_SW", "sw_to_midS", 320.0)],
        },
        "neighbors": ["TL_CENTRAL", "TL_SW", "TL_SE", "GATE_MID_N"],
    },
}

# Primary 4-corner intersections + central hub
CENTRAL_CORRIDORS = INTERSECTION_SPECS["TL_CENTRAL"]["corridors"]


class LocalIntersectionNode:
    """
    Independent local adaptive signal controller for a single intersection.
    Combines shared DQN Q-values with queue + waiting-time priority,
    Min-Green, Max-Green, Max-Red starvation prevention, and optional Green-Wave coordination.
    """

    def __init__(self, tl_id: str, spec: Dict[str, Any], initial_corridor: int = 0):
        self.tl_id = tl_id
        self.spec = spec
        self.name = spec["name"]
        self.corridors = spec["corridors"]

        self.current_corridor = initial_corridor
        self.target_corridor = initial_corridor
        self.stage = "MAIN_GREEN"  # "MAIN_GREEN" or "MAIN_YELLOW"
        self.stage_timer = 0.0
        self.red_timers = {0: 0.0 if initial_corridor == 0 else 5.0, 1: 0.0 if initial_corridor == 1 else 5.0}

        self.last_action = initial_corridor
        self.dqn_recommended = initial_corridor
        self.fairness_override = False
        self.switches_count = 0
        self.extensions_count = 0
        self.starvation_overrides = 0
        self.green_wave_holds = 0
        self.fairness_status = "BALANCED"
        self.last_explanation = f"{self.name}: Initialized adaptive monitoring."
        self.last_corridor_metrics: Dict[int, Dict[str, float]] = {
            0: {"queue": 0.0, "wait_avg": 0.0, "wait_max": 0.0, "demand": 0, "score": 0.0, "red_sec": 0.0},
            1: {"queue": 0.0, "wait_avg": 0.0, "wait_max": 0.0, "demand": 0, "score": 0.0, "red_sec": 0.0},
        }

    def reset(self, initial_corridor: int = 0):
        self.current_corridor = initial_corridor
        self.target_corridor = initial_corridor
        self.stage = "MAIN_GREEN"
        self.stage_timer = 0.0
        self.red_timers = {0: 0.0, 1: 0.0}
        self.last_action = initial_corridor
        self.dqn_recommended = initial_corridor
        self.fairness_override = False
        self.switches_count = 0
        self.extensions_count = 0
        self.starvation_overrides = 0
        self.green_wave_holds = 0
        self.fairness_status = "BALANCED"
        self.last_explanation = f"{self.name}: Reset to balanced adaptive monitoring."

    def _compute_corridor_metrics(self, vehs: List[Dict[str, Any]]) -> Dict[int, Dict[str, float]]:
        out: Dict[int, Dict[str, float]] = {}
        for cid in (0, 1):
            edges = set(self.corridors[cid]["edges"])
            c_vehs = [v for v in vehs if v.get("edge") in edges]
            q_weighted = sum(
                CLASS_WEIGHTS.get(v.get("class", "car"), 1.0)
                for v in c_vehs
                if v.get("is_queued", False)
            )
            q_raw = sum(1 for v in c_vehs if v.get("is_queued", False))
            waits = [float(v.get("waiting_time", 0.0)) for v in c_vehs]
            wait_max = max(waits) if waits else 0.0
            wait_avg = (sum(waits) / len(waits)) if waits else 0.0
            demand = len(c_vehs)
            red_sec = self.red_timers[cid]

            # Combined queue + waiting-time + demand + fairness priority score
            # Ensures a low-volume direction that waited 60s beats a newly arrived large queue
            starvation_boost = 0.0
            if demand > 0 and red_sec >= MAX_RED_DURATION:
                starvation_boost = 100.0 + (red_sec - MAX_RED_DURATION) * 2.0
            elif demand > 0 and wait_max >= MAX_RED_DURATION:
                starvation_boost = 80.0 + (wait_max - MAX_RED_DURATION) * 1.5

            score = (
                1.0 * q_weighted
                + 0.14 * wait_max
                + 0.06 * wait_avg
                + 0.35 * demand
                + starvation_boost
            )
            out[cid] = {
                "queue": round(q_weighted, 2),
                "queue_raw": q_raw,
                "wait_avg": round(wait_avg, 1),
                "wait_max": round(wait_max, 1),
                "demand": demand,
                "red_sec": round(red_sec, 1),
                "score": round(score, 2),
            }
        return out

    def _detect_incoming_platoon(self, vehs: List[Dict[str, Any]], corridor_id: int) -> Tuple[bool, int]:
        """
        Checks if a moving platoon (>=2 vehicles) on upstream edges is arriving
        within a 2.5s - 10.0s green-wave window.
        """
        links = self.spec.get("upstream_links", {}).get(corridor_id, [])
        if not links:
            return False, 0

        approaching_edges = {edge for _, edge, _ in links}
        moving_platoon = [
            v for v in vehs
            if v.get("edge") in approaching_edges
            and not v.get("is_queued", False)
            and v.get("speed_ms", 0.0) >= 3.5
        ]
        return (len(moving_platoon) >= 2), len(moving_platoon)

    def _build_local_state(
        self,
        telemetry: Dict[str, Any],
        cm: Dict[int, Dict[str, float]],
    ) -> List[float]:
        """
        Builds a 32-dim normalized state vector centered on THIS intersection,
        matching the exact input schema expected by CityDQNAgent (state_dim=32).
        """
        vehs = telemetry.get("vehicles", [])
        tls = telemetry.get("traffic_lights", {})
        rb = telemetry.get("roundabout", {})
        tj = telemetry.get("t_junction", {})
        metrics = telemetry.get("metrics", {})

        c0_edges = self.corridors[0]["edges"]
        c1_edges = self.corridors[1]["edges"]

        def _edge_q(edge_name: str) -> float:
            return sum(
                CLASS_WEIGHTS.get(v.get("class", "car"), 1.0)
                for v in vehs
                if v.get("is_queued", False) and v.get("edge") == edge_name
            )

        q0 = _edge_q(c0_edges[0]) if len(c0_edges) > 0 else 0.0
        q1 = _edge_q(c0_edges[1]) if len(c0_edges) > 1 else 0.0
        q2 = _edge_q(c1_edges[0]) if len(c1_edges) > 0 else 0.0
        q3 = _edge_q(c1_edges[1]) if len(c1_edges) > 1 else 0.0

        neighbors = self.spec.get("neighbors", ["TL_NW", "TL_NE", "TL_SW", "TL_SE"])
        state = [
            min(1.0, q0 / 35.0),
            min(1.0, q1 / 35.0),
            min(1.0, q2 / 35.0),
            min(1.0, q3 / 35.0),
            float(self.current_corridor) / 3.0,
            min(1.0, self.stage_timer / 25.0),
            1.0 if self.stage == "MAIN_YELLOW" else 0.0,
            min(1.0, tls.get(neighbors[0], {}).get("queued_vehicles", 0) / 25.0),
            min(1.0, tls.get(neighbors[1], {}).get("queued_vehicles", 0) / 25.0),
            min(1.0, tls.get(neighbors[2], {}).get("queued_vehicles", 0) / 25.0),
            min(1.0, tls.get(neighbors[3], {}).get("queued_vehicles", 0) / 25.0),
            1.0 if tls.get(neighbors[0], {}).get("primary_color") == "GREEN" else 0.0,
            1.0 if tls.get(neighbors[1], {}).get("primary_color") == "GREEN" else 0.0,
            1.0 if tls.get(neighbors[2], {}).get("primary_color") == "GREEN" else 0.0,
            1.0 if tls.get(neighbors[3], {}).get("primary_color") == "GREEN" else 0.0,
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
            min(1.0, max(cm[0]["wait_max"], cm[1]["wait_max"]) / 120.0),
            min(1.0, metrics.get("class_counts", {}).get("bus", 0) / 10.0),
            min(1.0, metrics.get("class_counts", {}).get("truck", 0) / 10.0),
            min(1.0, metrics.get("class_counts", {}).get("motorcycle", 0) / 25.0),
            min(1.0, metrics.get("class_counts", {}).get("car", 0) / 150.0),
            min(1.0, telemetry.get("total_arrived", 0) / 100.0),
            min(1.0, telemetry.get("total_departed", 0) / 300.0),
        ]
        return state[:32]

    def step(
        self,
        telemetry: Dict[str, Any],
        agent: CityDQNAgent,
        step_length: float,
        min_green: float,
        max_green: float,
        max_red: float,
        yellow_dur: float,
        green_wave_enabled: bool = False,
    ) -> int:
        vehs = telemetry.get("vehicles", [])
        cm = self._compute_corridor_metrics(vehs)
        self.last_corridor_metrics = cm

        self.stage_timer += step_length
        other_corridor = 1 if self.current_corridor == 0 else 0

        # Update red timers: active green corridor has 0 red wait; opposing accumulates red time
        if self.stage == "MAIN_GREEN":
            self.red_timers[self.current_corridor] = 0.0
            if cm[other_corridor]["demand"] > 0:
                self.red_timers[other_corridor] += step_length
            else:
                self.red_timers[other_corridor] = max(0.0, self.red_timers[other_corridor] - step_length * 0.5)
        else:
            # During yellow clearance, opposing still waits
            if cm[other_corridor]["demand"] > 0:
                self.red_timers[other_corridor] += step_length

        grp = self.corridors[self.current_corridor]
        other_grp = self.corridors[other_corridor]

        if self.stage == "MAIN_GREEN":
            local_state = self._build_local_state(telemetry, cm)
            action = agent.select_action(local_state, eval_mode=True)
            self.last_action = action
            self.dqn_recommended = action % 2
            self.fairness_override = False

            cur_m = cm[self.current_corridor]
            oth_m = cm[other_corridor]
            should_switch = False
            reason = ""
            status = "BALANCED"

            platoon_arriving, platoon_size = (
                self._detect_incoming_platoon(vehs, self.current_corridor)
                if green_wave_enabled
                else (False, 0)
            )
            opp_platoon, opp_platoon_size = (
                self._detect_incoming_platoon(vehs, other_corridor)
                if green_wave_enabled
                else (False, 0)
            )

            # 1. Minimum Green Enforcement
            if self.stage_timer < min_green:
                should_switch = False
                status = "MIN_GREEN_LOCK"
                reason = (
                    f"{self.name}: Holding {grp['desc']} green ({self.stage_timer:.1f}s / {min_green:.0f}s min green)."
                )
            # 2. Maximum Red / Starvation Prevention
            elif self.red_timers[other_corridor] >= max_red and (oth_m["demand"] > 0 or oth_m["queue_raw"] > 0):
                should_switch = True
                self.starvation_overrides += 1
                self.fairness_override = True
                status = "STARVATION_PREVENTION"
                reason = (
                    f"{self.name}: {other_grp['desc']} reached Max-Red ({self.red_timers[other_corridor]:.1f}s >= {max_red:.0f}s). "
                    f"Fairness priority applied -> transitioning safely."
                )
            # 3. Maximum Green Gate
            elif self.stage_timer >= max_green and (oth_m["demand"] > 0 or oth_m["queue_raw"] > 0):
                should_switch = True
                self.fairness_override = True
                status = "MAX_GREEN_SWITCH"
                reason = (
                    f"{self.name}: Maximum green ({max_green:.0f}s) reached on {grp['desc']}. "
                    f"Stopping extension -> transitioning to {other_grp['desc']}."
                )
            # 4. Dynamic Queue Depletion (current green empty, opposing waiting)
            elif cur_m["queue_raw"] == 0 and cur_m["demand"] <= 1 and oth_m["queue_raw"] > 0 and not platoon_arriving:
                should_switch = True
                status = "QUEUE_DEPLETION"
                reason = (
                    f"{self.name}: {grp['desc']} cleared (0 queued) -> Switching early to {other_grp['desc']} ({oth_m['queue_raw']} queued)."
                )
            # 5. Green-Wave Platoon Hold (if enabled & safe)
            elif green_wave_enabled and platoon_arriving and self.stage_timer < (max_green - 4.0) and self.red_timers[other_corridor] < (max_red - 5.0):
                should_switch = False
                self.green_wave_holds += 1
                status = "GREEN_WAVE_HOLD"
                reason = (
                    f"{self.name}: Green-Wave holding {grp['desc']} for incoming {platoon_size}-vehicle platoon."
                )
            # 6. Fair Queue + Wait-Time + DQN Policy Decision
            elif (action == other_corridor and oth_m["score"] >= cur_m["score"] * 0.85 and oth_m["demand"] > 0) or (
                oth_m["score"] > cur_m["score"] * 1.25 and oth_m["demand"] > 0
            ):
                should_switch = True
                status = "DQN_FAIR_SWITCH"
                reason = (
                    f"{self.name}: Priority switch to {other_grp['desc']} "
                    f"(score {oth_m['score']:.1f} vs {cur_m['score']:.1f}; max wait {oth_m['wait_max']:.0f}s)."
                )
            # 7. Green-Wave early switch for opposing approaching platoon when current is light
            elif green_wave_enabled and opp_platoon and cur_m["queue_raw"] <= 1 and oth_m["score"] >= cur_m["score"] * 0.7:
                should_switch = True
                status = "GREEN_WAVE_COORDINATED"
                reason = (
                    f"{self.name}: Green-Wave coordinating {other_grp['desc']} for {opp_platoon_size}-vehicle upstream platoon."
                )
            else:
                status = "BALANCED"
                reason = (
                    f"{self.name}: Serving {grp['desc']} ({self.stage_timer:.1f}s elapsed, "
                    f"Q={cur_m['queue_raw']}, wait={cur_m['wait_max']:.0f}s | Cross Q={oth_m['queue_raw']}, red={self.red_timers[other_corridor]:.0f}s)."
                )

            self.fairness_status = status
            if should_switch:
                self.target_corridor = other_corridor
                self.stage = "MAIN_YELLOW"
                self.stage_timer = 0.0
                self.last_explanation = reason
                return grp["yellow"]
            else:
                self.extensions_count += 1
                self.last_explanation = reason
                return grp["green"]

        else:  # MAIN_YELLOW
            if self.stage_timer >= yellow_dur:
                self.current_corridor = self.target_corridor
                self.stage = "MAIN_GREEN"
                self.stage_timer = 0.0
                self.red_timers[self.current_corridor] = 0.0
                self.switches_count += 1
                new_grp = self.corridors[self.current_corridor]
                self.last_explanation = f"{self.name}: Yellow complete -> {new_grp['desc']} GREEN."
                return new_grp["green"]
            return grp["yellow"]

    def get_snapshot(self, min_green: float, max_green: float, max_red: float) -> Dict[str, Any]:
        grp = self.corridors[self.current_corridor]
        rem_green = max(0.0, round(max_green - self.stage_timer, 1)) if self.stage == "MAIN_GREEN" else 0.0
        return {
            "id": self.tl_id,
            "name": self.name,
            "active_corridor": self.current_corridor,
            "phase_index": grp["green"] if self.stage == "MAIN_GREEN" else grp["yellow"],
            "phase_description": grp["desc"],
            "stage": self.stage,
            "stage_elapsed_sec": round(self.stage_timer, 1),
            "remaining_max_green_sec": rem_green,
            "min_green_sec": min_green,
            "max_green_sec": max_green,
            "max_red_sec": max_red,
            "red_timers": {str(k): round(v, 1) for k, v in self.red_timers.items()},
            "corridor_metrics": self.last_corridor_metrics,
            "fairness_status": self.fairness_status,
            "switches_count": self.switches_count,
            "starvation_overrides": self.starvation_overrides,
            "green_wave_holds": self.green_wave_holds,
            "last_action": self.last_action,
            "dqn_recommended_corridor": self.dqn_recommended,
            "dqn_recommended_desc": self.corridors[self.dqn_recommended]["desc"],
            "fairness_override": self.fairness_override,
            "safety_validation": "SAFE_4PHASE_OK",
            "explanation": self.last_explanation,
        }


class AdaptiveCityController:
    """
    Coordinated Multi-Intersection Adaptive Traffic Controller.
    Operates independent LocalIntersectionNode controllers for all signalized
    junctions using the shared pre-trained CityDQNAgent, enforcing fairness,
    starvation prevention, safe 4-phase transitions, and optional Green-Wave coordination.
    """

    def __init__(self, step_length: float = SIMULATION_STEP_LENGTH):
        self.step_length = step_length
        self.min_green = float(MIN_GREEN_DURATION)
        self.max_green = float(MAX_GREEN_DURATION)
        self.max_red = float(MAX_RED_DURATION)
        self.yellow_dur = float(YELLOW_PHASE_DURATION)
        self.green_wave_enabled = False

        self.agent = CityDQNAgent(state_dim=32, action_dim=4)
        if os.path.exists(DQN_MODEL_PATH):
            try:
                self.agent.load(DQN_MODEL_PATH)
                self.model_loaded = True
            except Exception as e:
                print(f"AdaptiveCityController: Error loading weights from {DQN_MODEL_PATH}: {e}")
                self.model_loaded = False
        else:
            self.model_loaded = False

        # Independent controller node for every signalized junction in city.net.xml
        # Stagger initial corridors for natural arterial offset
        initial_offsets = {
            "TL_CENTRAL": 1,
            "TL_NW": 0,
            "TL_NE": 1,
            "TL_SW": 1,
            "TL_SE": 0,
            "GATE_MID_N": 0,
            "GATE_MID_S": 0,
        }
        self.nodes: Dict[str, LocalIntersectionNode] = {
            tl_id: LocalIntersectionNode(tl_id, spec, initial_corridor=initial_offsets.get(tl_id, 0))
            for tl_id, spec in INTERSECTION_SPECS.items()
        }

        self.last_explanation = "Independent Multi-Intersection Adaptive Controller initialized."

    def reset(self):
        initial_offsets = {
            "TL_CENTRAL": 1,
            "TL_NW": 0,
            "TL_NE": 1,
            "TL_SW": 1,
            "TL_SE": 0,
            "GATE_MID_N": 0,
            "GATE_MID_S": 0,
        }
        for tl_id, node in self.nodes.items():
            node.reset(initial_corridor=initial_offsets.get(tl_id, 0))
        self.last_explanation = "All intersections reset to balanced adaptive monitoring."

    def configure_timings(
        self,
        min_green: Optional[float] = None,
        max_green: Optional[float] = None,
        max_red: Optional[float] = None,
        yellow_dur: Optional[float] = None,
        green_wave: Optional[bool] = None,
    ):
        if min_green is not None:
            self.min_green = max(5.0, min(30.0, float(min_green)))
        if max_green is not None:
            self.max_green = max(self.min_green + 5.0, min(90.0, float(max_green)))
        if max_red is not None:
            self.max_red = max(self.min_green + 10.0, min(120.0, float(max_red)))
        if yellow_dur is not None:
            # Never allow yellow clearance below safe 3.0s defined in city.net.xml
            self.yellow_dur = max(3.0, min(6.0, float(yellow_dur)))
        if green_wave is not None:
            self.green_wave_enabled = bool(green_wave)

    def step(self, telemetry: Dict[str, Any], city_runner: Any, green_wave: Optional[bool] = None) -> Dict[str, int]:
        """
        Evaluates every signalized intersection independently and applies safe phase transitions.
        """
        gw = self.green_wave_enabled if green_wave is None else bool(green_wave)
        target_phases: Dict[str, int] = {}

        for tl_id, node in self.nodes.items():
            phase_idx = node.step(
                telemetry=telemetry,
                agent=self.agent,
                step_length=self.step_length,
                min_green=self.min_green,
                max_green=self.max_green,
                max_red=self.max_red,
                yellow_dur=self.yellow_dur,
                green_wave_enabled=gw,
            )
            city_runner.set_tl_phase(tl_id, phase_idx)
            target_phases[tl_id] = phase_idx

        central_node = self.nodes["TL_CENTRAL"]
        self.last_explanation = central_node.last_explanation
        return target_phases

    def force_corridor(self, tl_id: str, corridor_id: int):
        node = self.nodes.get(tl_id)
        if not node:
            return
        if corridor_id in (0, 1) and node.current_corridor != corridor_id:
            node.target_corridor = corridor_id
            node.stage = "MAIN_YELLOW"
            node.stage_timer = 0.0
            node.last_explanation = f"{node.name}: Operator requested safe transition to {node.corridors[corridor_id]['desc']}."
            self.last_explanation = node.last_explanation

    def get_heaviest_corridor(self, tl_id: str = "TL_CENTRAL") -> int:
        node = self.nodes.get(tl_id)
        if not node:
            return 0
        m = node.last_corridor_metrics
        return 0 if m[0]["score"] >= m[1]["score"] else 1

    def get_info(self) -> Dict[str, Any]:
        central = self.nodes["TL_CENTRAL"]
        grp = central.corridors[central.current_corridor]
        total_switches = sum(n.switches_count for n in self.nodes.values())
        total_starvation = sum(n.starvation_overrides for n in self.nodes.values())
        total_gw = sum(n.green_wave_holds for n in self.nodes.values())

        return {
            "mode": "GREEN_WAVE" if self.green_wave_enabled else "AI_ADAPTIVE",
            "name": "Coordinated Multi-Intersection DQN Controller",
            "model_status": "ONLINE" if self.model_loaded else "HEURISTIC_BACKUP",
            "green_wave_enabled": self.green_wave_enabled,
            "active_phase_group": central.current_corridor,
            "phase_description": grp["desc"],
            "stage": central.stage,
            "stage_elapsed_sec": round(central.stage_timer, 1),
            "remaining_max_green_sec": max(0.0, round(self.max_green - central.stage_timer, 1)) if central.stage == "MAIN_GREEN" else 0.0,
            "is_transitioning": central.stage == "MAIN_YELLOW",
            "last_action_code": central.last_action,
            "total_phase_switches": total_switches,
            "total_starvation_overrides": total_starvation,
            "total_green_wave_holds": total_gw,
            "timings": {
                "min_green_sec": self.min_green,
                "max_green_sec": self.max_green,
                "max_red_sec": self.max_red,
                "yellow_sec": self.yellow_dur,
            },
            "explanation": self.last_explanation,
            "intersections": {
                tl_id: node.get_snapshot(self.min_green, self.max_green, self.max_red)
                for tl_id, node in self.nodes.items()
            },
        }
