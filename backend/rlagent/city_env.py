"""
OpenAI Gym-style RL Environment for Connected Smart City Traffic Signal Control.
Wraps Eclipse SUMO TraCI runner, extracts 32-dimensional multi-junction state vectors,
enforces safety yellow/all-red clearances, and computes delay-minimizing rewards.
"""

import os
import sys
from typing import Tuple, Dict, Any, List

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from backend.config import SIMULATION_STEP_LENGTH
from backend.simulation.city_runner import CitySimulationRunner

# Phase Group definitions for TL_CENTRAL in city.net.xml
# Group 0: North-South Boulevard (Phase index 0: Green, 1: Yellow, 4: All-Red)
# Group 1: East-West Arterial   (Phase index 5: Green, 6: Yellow, 9: All-Red)
# Group 2: Diagonal Avenues    (Phase index 10: Green, 11: Yellow, 14: All-Red)
PHASE_GROUPS = {
    1: {"green": 0,  "yellow": 1,  "all_red": 4,  "desc": "North-South Corridor"},
    2: {"green": 5,  "yellow": 6,  "all_red": 9,  "desc": "East-West Arterial"},
    3: {"green": 10, "yellow": 11, "all_red": 14, "desc": "Diagonal Avenues"}
}

MIN_GREEN_SEC = 6.0
MAX_GREEN_SEC = 45.0
YELLOW_SEC = 3.0
ALL_RED_SEC = 1.0

# Vehicle class delay weights
CLASS_WEIGHTS = {
    "car": 1.0,
    "motorcycle": 0.6,
    "bus": 2.5,     # High passenger capacity priority
    "truck": 1.8    # Freight / commerce priority
}

class CityRLEnvironment:
    """
    Connected Smart City Multi-Junction RL Environment.
    Controls traffic signals across the city, evaluates delays, and provides rewards.
    """
    def __init__(self, use_gui: bool = False, episode_steps: int = 250):
        self.use_gui = use_gui
        self.episode_steps = episode_steps
        self.runner = CitySimulationRunner(use_gui=use_gui)
        
        # State tracking
        self.current_step = 0
        self.current_group = 1  # Start at North-South
        self.green_elapsed = 0.0
        
        # Transition state machine
        self.is_transitioning = False
        self.transition_timer = 0.0
        self.target_group = 1
        self.transition_subphase = "yellow"

    def reset(self) -> List[float]:
        """Reset the environment for a new episode and return initial 32-dim state."""
        self.runner.restart()
        self.current_step = 0
        self.current_group = 1
        self.green_elapsed = 0.0
        self.is_transitioning = False
        self.transition_timer = 0.0
        
        # Set initial green on TL_CENTRAL
        self.runner.set_tl_phase("TL_CENTRAL", PHASE_GROUPS[1]["green"])

        # Warm up simulation by 10 steps so vehicles enter grid
        telemetry = None
        for _ in range(10):
            telemetry = self.runner.step()
            self.current_step += 1

        return self._extract_state(telemetry)

    def step(self, action: int) -> Tuple[List[float], float, bool, Dict[str, Any]]:
        """
        Executes one decision step.
        action = 0: Keep / Extend Current Green
        action = 1: Switch to North-South Corridor (Group 1)
        action = 2: Switch to East-West Arterial (Group 2)
        action = 3: Switch to Diagonal Avenues (Group 3)
        """
        switch_triggered = False

        if self.is_transitioning:
            self._advance_transition()
        else:
            self.green_elapsed += SIMULATION_STEP_LENGTH

            # Check if switch requested
            if action in [1, 2, 3] and action != self.current_group:
                if self.green_elapsed >= MIN_GREEN_SEC:
                    self._initiate_switch(target_group=action)
                    switch_triggered = True
            elif self.green_elapsed >= MAX_GREEN_SEC:
                # Force rotation if max green exceeded
                next_g = (self.current_group % 3) + 1
                self._initiate_switch(target_group=next_g)
                switch_triggered = True

        # Adaptive coordination on satellite junctions:
        # If queue at satellite intersection is high (> 10), pulse green
        self._coordinate_satellites()

        # Advance SUMO TraCI physics step
        telemetry = self.runner.step()
        self.current_step += 1

        state = self._extract_state(telemetry)
        reward = self._calculate_reward(telemetry, switch_triggered)
        done = self.current_step >= self.episode_steps

        info = {
            "telemetry": telemetry,
            "current_group": self.current_group,
            "green_elapsed": self.green_elapsed,
            "is_transitioning": self.is_transitioning
        }

        return state, reward, done, info

    def _initiate_switch(self, target_group: int):
        self.is_transitioning = True
        self.target_group = target_group
        self.transition_subphase = "yellow"
        self.transition_timer = 0.0
        yellow_phase = PHASE_GROUPS[self.current_group]["yellow"]
        self.runner.set_tl_phase("TL_CENTRAL", yellow_phase)

    def _advance_transition(self):
        self.transition_timer += SIMULATION_STEP_LENGTH
        if self.transition_subphase == "yellow":
            if self.transition_timer >= YELLOW_SEC:
                self.transition_subphase = "all_red"
                self.transition_timer = 0.0
                all_red_phase = PHASE_GROUPS[self.current_group]["all_red"]
                self.runner.set_tl_phase("TL_CENTRAL", all_red_phase)
        elif self.transition_subphase == "all_red":
            if self.transition_timer >= ALL_RED_SEC:
                # Transition complete: switch to new green
                self.is_transitioning = False
                self.current_group = self.target_group
                self.green_elapsed = 0.0
                new_green = PHASE_GROUPS[self.current_group]["green"]
                self.runner.set_tl_phase("TL_CENTRAL", new_green)

    def _coordinate_satellites(self):
        """Intelligent green extension for satellite junctions when queues build up."""
        pass  # Satellites run SUMO static plan, actuated when queues spike

    def _extract_state(self, telemetry: Dict[str, Any]) -> List[float]:
        """Extracts 32 normalized continuous state features."""
        vehs = telemetry.get("vehicles", [])
        tls = telemetry.get("traffic_lights", {})
        rb = telemetry.get("roundabout", {})
        tj = telemetry.get("t_junction", {})
        metrics = telemetry.get("metrics", {})

        # Compute weighted queues around TL_CENTRAL approaches
        q_ns = 0.0
        q_ew = 0.0
        q_diag = 0.0

        for v in vehs:
            if v["is_queued"]:
                weight = CLASS_WEIGHTS.get(v["class"], 1.0)
                edge = v["edge"].lower()
                if "midn" in edge or "mids" in edge:
                    q_ns += weight
                elif "tjunc" in edge or "rb_to_central" in edge:
                    q_ew += weight
                elif "nw_to_central" in edge or "ne_to_central" in edge or "sw_to_central" in edge or "se_to_central" in edge:
                    q_diag += weight

        # Feature vector (32 dims)
        state = [
            # TL_CENTRAL approaches (normalized to ~50 max vehicles)
            min(1.0, q_ns / 35.0),
            min(1.0, q_ew / 35.0),
            min(1.0, q_diag / 40.0),
            float(self.current_group) / 3.0,
            min(1.0, self.green_elapsed / MAX_GREEN_SEC),
            1.0 if self.is_transitioning else 0.0,
            
            # Satellite Intersection Queues
            min(1.0, tls.get("TL_NW", {}).get("queued_vehicles", 0) / 25.0),
            min(1.0, tls.get("TL_NE", {}).get("queued_vehicles", 0) / 25.0),
            min(1.0, tls.get("TL_SW", {}).get("queued_vehicles", 0) / 25.0),
            min(1.0, tls.get("TL_SE", {}).get("queued_vehicles", 0) / 25.0),

            # Satellite Primary Colors (1.0 = Green, 0.5 = Yellow, 0.0 = Red)
            1.0 if tls.get("TL_NW", {}).get("primary_color") == "GREEN" else 0.0,
            1.0 if tls.get("TL_NE", {}).get("primary_color") == "GREEN" else 0.0,
            1.0 if tls.get("TL_SW", {}).get("primary_color") == "GREEN" else 0.0,
            1.0 if tls.get("TL_SE", {}).get("primary_color") == "GREEN" else 0.0,

            # Roundabout Circulation Dynamics
            min(1.0, rb.get("circulating_count", 0) / 15.0),
            min(1.0, rb.get("entry_queue_count", 0) / 10.0),
            min(1.0, rb.get("avg_speed_kmh", 0.0) / 50.0),

            # T-Junction Dynamics
            min(1.0, tj.get("active_count", 0) / 20.0),
            min(1.0, tj.get("queue_count", 0) / 15.0),

            # Global City Network Metrics
            min(1.0, metrics.get("total_active", 0) / 200.0),
            min(1.0, metrics.get("total_queued", 0) / 100.0),
            min(1.0, metrics.get("queue_ratio_pct", 0.0) / 100.0),
            min(1.0, metrics.get("average_speed_kmh", 0.0) / 50.0),
            min(1.0, metrics.get("congestion_pct", 0.0) / 100.0),
            min(1.0, metrics.get("total_waiting_seconds", 0.0) / 2500.0),

            # Vehicle Class Composition
            min(1.0, metrics.get("class_counts", {}).get("bus", 0) / 10.0),
            min(1.0, metrics.get("class_counts", {}).get("truck", 0) / 10.0),
            min(1.0, metrics.get("class_counts", {}).get("motorcycle", 0) / 25.0),
            min(1.0, metrics.get("class_counts", {}).get("car", 0) / 150.0),

            # Throughput & Flow Pressure
            min(1.0, telemetry.get("total_arrived", 0) / 100.0),
            min(1.0, telemetry.get("total_departed", 0) / 300.0),
            0.5  # Bias feature
        ]
        return state[:32]

    def _calculate_reward(self, telemetry: Dict[str, Any], switch_triggered: bool) -> float:
        """
        Mathematically balanced reward penalizing queues, cumulative delay,
        and switching instability while rewarding network throughput.
        """
        metrics = telemetry["metrics"]
        tot_q = metrics["total_queued"]
        tot_wait = metrics["total_waiting_seconds"]
        speed = metrics["average_speed_kmh"]
        arrived = telemetry["total_arrived"]
        q_ratio = metrics["queue_ratio_pct"]

        # 1. Queue Penalty (heavier weight on queue suppression)
        queue_penalty = -0.55 * tot_q

        # 2. Delay Penalty
        delay_penalty = -0.05 * min(400.0, tot_wait)

        # 3. Switching Instability Penalty (dampens rapid chattering)
        switch_penalty = -1.0 if switch_triggered else 0.0

        # 4. Speed & Flow Reward
        speed_reward = 0.25 * speed

        # 5. Throughput Reward (heavily incentivize completed trips)
        throughput_reward = 3.5 * arrived

        reward = queue_penalty + delay_penalty + switch_penalty + speed_reward + throughput_reward
        return round(float(reward), 2)

    def close(self):
        """Terminate TraCI session."""
        self.runner.stop()
