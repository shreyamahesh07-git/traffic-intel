import os
import sys
from typing import Tuple, Dict, Any, List

# Load backend configuration
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from backend.config import (
    SIMULATION_STEP_LENGTH,
    YELLOW_PHASE_DURATION,
    ALL_RED_PHASE_DURATION,
    MIN_GREEN_DURATION,
    MAX_GREEN_DURATION
)
from backend.simulation.sim_runner import (
    SumoSimulationRunner,
    PHASE_NS_GREEN,
    PHASE_NS_YELLOW,
    PHASE_ALL_RED_NS,
    PHASE_EW_GREEN,
    PHASE_EW_YELLOW,
    PHASE_ALL_RED_EW
)
from backend.density.density_estimator import TrafficDensityEstimator

class SumoRLEnvironment:
    """
    OpenAI Gym-style Environment wrapper for SUMO Adaptive Traffic Signal Control.
    Enforces traffic safety rules (yellow & all-red clearance, min/max green times),
    computes 16-dim state vectors, and returns delay-minimizing rewards.
    """
    def __init__(self, use_gui: bool = False, episode_steps: int = 400):
        self.use_gui = use_gui
        self.episode_steps = episode_steps
        self.runner = SumoSimulationRunner(use_gui=use_gui)
        self.density_estimator = TrafficDensityEstimator()
        
        # State and transition management
        self.current_step = 0
        self.is_in_transition = False
        self.transition_timer = 0
        self.transition_target_phase = PHASE_EW_GREEN
        self.current_green_phase = PHASE_NS_GREEN
        self.green_elapsed_sec = 0.0

    def reset(self) -> List[float]:
        """Reset the environment for a new training episode and return initial state vector."""
        self.runner.restart()
        self.current_step = 0
        self.is_in_transition = False
        self.transition_timer = 0
        self.current_green_phase = PHASE_NS_GREEN
        self.green_elapsed_sec = 0.0
        self.runner.set_phase(PHASE_NS_GREEN)

        # Step a few times to let initial vehicles enter
        for _ in range(5):
            telemetry = self.runner.step()
            self.current_step += 1

        density_info = self.density_estimator.compute_density(telemetry)
        return density_info["dqn_state"]

    def step(self, action: int) -> Tuple[List[float], float, bool, Dict[str, Any]]:
        """
        Execute one decision step.
        action = 0: Keep current phase (extend green)
        action = 1: Switch to conflicting phase (triggers yellow -> all-red -> new green)
        """
        # If currently executing yellow/all-red clearance, continue transition
        if self.is_in_transition:
            self._advance_transition()
        else:
            self.green_elapsed_sec += SIMULATION_STEP_LENGTH
            
            # Action 1: Request phase change (only if min green satisfied)
            if action == 1 and self.green_elapsed_sec >= MIN_GREEN_DURATION:
                self._initiate_phase_switch()
            elif self.green_elapsed_sec >= MAX_GREEN_DURATION:
                # Force switch if max green exceeded
                self._initiate_phase_switch()

        # Advance physics simulation by 1 step
        telemetry = self.runner.step()
        self.current_step += 1

        # Compute traffic density and state vector
        density_info = self.density_estimator.compute_density(telemetry)
        state = density_info["dqn_state"]

        # Calculate reward
        reward = self._calculate_reward(density_info, action)

        # Episode termination
        done = self.current_step >= self.episode_steps

        info = {
            "telemetry": telemetry,
            "density": density_info,
            "current_green_phase": self.current_green_phase,
            "green_elapsed_sec": self.green_elapsed_sec,
            "is_in_transition": self.is_in_transition
        }
        return state, reward, done, info

    def _initiate_phase_switch(self):
        """Begin safe yellow clearance phase."""
        self.is_in_transition = True
        self.transition_timer = 0
        
        if self.current_green_phase == PHASE_NS_GREEN:
            # North-South -> East-West
            self.runner.set_phase(PHASE_NS_YELLOW)
            self.transition_target_phase = PHASE_EW_GREEN
        else:
            # East-West -> North-South
            self.runner.set_phase(PHASE_EW_YELLOW)
            self.transition_target_phase = PHASE_NS_GREEN

    def _advance_transition(self):
        """Progress through yellow (3s) and all-red (2s) clearance intervals."""
        self.transition_timer += SIMULATION_STEP_LENGTH
        yellow_steps = YELLOW_PHASE_DURATION
        total_clearance = YELLOW_PHASE_DURATION + ALL_RED_PHASE_DURATION

        if self.transition_timer < yellow_steps:
            pass  # maintain yellow
        elif self.transition_timer < total_clearance:
            # Shift to All-Red clearance
            all_red_phase = PHASE_ALL_RED_NS if self.transition_target_phase == PHASE_EW_GREEN else PHASE_ALL_RED_EW
            self.runner.set_phase(all_red_phase)
        else:
            # Transition complete: activate target green phase
            self.current_green_phase = self.transition_target_phase
            self.runner.set_phase(self.current_green_phase)
            self.is_in_transition = False
            self.transition_timer = 0
            self.green_elapsed_sec = 0.0

    def _calculate_reward(self, density_info: Dict[str, Any], action: int) -> float:
        """
        Multi-objective Reward Function:
        R = - (0.5 * Total_Queue + 0.05 * Total_Wait + 0.2 * Queue_Imbalance) + 2.0 * Arrived_Throughput - 0.5 * Switch_Penalty
        """
        total_queue = density_info["total_intersection_queue"]
        total_wait = density_info["total_intersection_wait_sec"]
        
        # Queue imbalance between NS and EW
        d = density_info["directional"]
        ns_q = d["NORTH"]["queue_count"] + d["SOUTH"]["queue_count"]
        ew_q = d["EAST"]["queue_count"] + d["WEST"]["queue_count"]
        queue_imbalance = abs(ns_q - ew_q)

        # Penalties
        penalty_queue = -0.5 * total_queue
        penalty_wait = -0.05 * min(200.0, total_wait)
        penalty_imbalance = -0.2 * queue_imbalance
        switch_penalty = -0.5 if (action == 1 and not self.is_in_transition) else 0.0

        # Throughput reward for arrived/cleared vehicles
        arrived = self.runner.total_arrived
        throughput_bonus = 1.0 if arrived > 0 else 0.0

        total_reward = penalty_queue + penalty_wait + penalty_imbalance + throughput_bonus + switch_penalty
        return round(total_reward, 3)

    def close(self):
        """Close SUMO environment."""
        self.runner.close()

if __name__ == "__main__":
    print("Testing SumoRLEnvironment reset and 20 steps...")
    env = SumoRLEnvironment(use_gui=False, episode_steps=50)
    state = env.reset()
    print(f"Initial State (len={len(state)}): {state[:8]}...")
    
    total_reward = 0.0
    for step in range(20):
        # Alternate keep (0) and switch (1)
        action = 1 if step == 15 else 0
        next_state, reward, done, info = env.step(action)
        total_reward += reward
        if step % 5 == 0 or step == 19:
            d = info["density"]
            print(f"Step {step:02d}: Action={action}, Reward={reward:6.2f}, Queue={d['total_intersection_queue']}, Phase={info['current_green_phase']}")
            
    env.close()
    print("SumoRLEnvironment verified successfully!")

