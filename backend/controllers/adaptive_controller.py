import os
import sys
from typing import Dict, Any, List, Optional

# Load backend configuration
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from backend.config import (
    DQN_MODEL_PATH,
    YELLOW_PHASE_DURATION,
    ALL_RED_PHASE_DURATION,
    MIN_GREEN_DURATION,
    MAX_GREEN_DURATION,
    SIMULATION_STEP_LENGTH
)
from backend.simulation.sim_runner import (
    PHASE_NS_GREEN,
    PHASE_NS_YELLOW,
    PHASE_ALL_RED_NS,
    PHASE_EW_GREEN,
    PHASE_EW_YELLOW,
    PHASE_ALL_RED_EW
)
from backend.rlagent.dqn_agent import DQNAgent

class AdaptiveDQNController:
    """
    AI-Driven Adaptive Traffic Signal Controller powered by Deep Q-Network (DQN).
    Analyzes real-time directional density, queue lengths, and waiting delays to dynamically
    optimize signal timing and minimize intersection congestion.
    """
    def __init__(self, model_path: str = DQN_MODEL_PATH):
        self.model_path = model_path
        self.agent = DQNAgent(state_dim=16, action_dim=2)
        
        # Load pre-trained weights if available
        if os.path.exists(model_path):
            try:
                self.agent.load(model_path)
                print(f"AdaptiveController: Loaded DQN model from {model_path}")
            except Exception as e:
                print(f"AdaptiveController: Could not load weights from {model_path} ({e}), using initialized agent.")
        else:
            print(f"AdaptiveController: No weights file at {model_path}, using initialized agent.")

        # State and phase variables
        self.current_phase = PHASE_NS_GREEN
        self.current_green_phase = PHASE_NS_GREEN
        self.green_elapsed_sec = 0.0
        
        # Clearance transition state
        self.is_in_transition = False
        self.transition_timer = 0.0
        self.target_green_phase = PHASE_EW_GREEN
        
        # Telemetry stats
        self.total_switches = 0
        self.last_action = 0
        self.last_explanation = "Initializing AI Adaptive Controller..."

    def reset(self):
        """Reset controller state."""
        self.current_phase = PHASE_NS_GREEN
        self.current_green_phase = PHASE_NS_GREEN
        self.green_elapsed_sec = 0.0
        self.is_in_transition = False
        self.transition_timer = 0.0
        self.total_switches = 0
        self.last_action = 0
        self.last_explanation = "AI Controller reset to North-South Green."

    def step(self, dqn_state: List[float], telemetry: Optional[Dict[str, Any]] = None, step_length: float = SIMULATION_STEP_LENGTH) -> int:
        """
        Observes real-time state vector, decides action via DQN,
        enforces safety clearance intervals, updates human explanation, and returns active phase index.
        """
        # Directional queue analysis for factual explanations
        ns_q = 0
        ew_q = 0
        if telemetry and "directional" in telemetry:
            d = telemetry["directional"]
            ns_q = d.get("NORTH", {}).get("queue_count", 0) + d.get("SOUTH", {}).get("queue_count", 0)
            ew_q = d.get("EAST", {}).get("queue_count", 0) + d.get("WEST", {}).get("queue_count", 0)

        # If currently executing yellow/all-red clearance, progress transition
        if self.is_in_transition:
            self.transition_timer += step_length
            
            if self.transition_timer < YELLOW_PHASE_DURATION:
                self.last_explanation = f"Safety Clearance: Yellow signal active ({round(YELLOW_PHASE_DURATION - self.transition_timer, 1)}s remaining) before phase switch."
            elif self.transition_timer < (YELLOW_PHASE_DURATION + ALL_RED_PHASE_DURATION):
                # Shift to all-red
                all_red = PHASE_ALL_RED_NS if self.target_green_phase == PHASE_EW_GREEN else PHASE_ALL_RED_EW
                self.current_phase = all_red
                self.last_explanation = "All-Red Clearance: Intersection clearing to avoid conflicting turning collisions."
            else:
                # Transition complete: activate target green phase
                self.current_green_phase = self.target_green_phase
                self.current_phase = self.current_green_phase
                self.is_in_transition = False
                self.transition_timer = 0.0
                self.green_elapsed_sec = 0.0
                target_name = "East-West" if self.current_green_phase == PHASE_EW_GREEN else "North-South"
                self.last_explanation = f"Green signal granted to {target_name}. Clearing waiting queues."

            return self.current_phase

        # Normal Green Phase Progression
        self.green_elapsed_sec += step_length

        # Consult DQN policy: 0 = Keep Green, 1 = Switch Phase
        action = self.agent.select_action(dqn_state, eval_mode=True)
        self.last_action = action

        # Enforce Minimum and Maximum Green constraints
        should_switch = False
        active_corridor = "North-South" if self.current_green_phase == PHASE_NS_GREEN else "East-West"
        opposing_corridor = "East-West" if self.current_green_phase == PHASE_NS_GREEN else "North-South"
        active_q = ns_q if self.current_green_phase == PHASE_NS_GREEN else ew_q
        opp_q = ew_q if self.current_green_phase == PHASE_NS_GREEN else ns_q

        if action == 1 and self.green_elapsed_sec >= MIN_GREEN_DURATION:
            should_switch = True
            self.last_explanation = f"{opposing_corridor} queue ({opp_q} veh) is demanding service. DQN Agent action: SWITCH_PHASE. Switching green from {active_corridor}."
        elif self.green_elapsed_sec >= MAX_GREEN_DURATION:
            should_switch = True
            self.last_explanation = f"Maximum green time ({MAX_GREEN_DURATION}s) reached for {active_corridor}. Mandatory cycle switch to prevent starvation of {opposing_corridor}."
        elif action == 1 and self.green_elapsed_sec < MIN_GREEN_DURATION:
            remaining_min = round(MIN_GREEN_DURATION - self.green_elapsed_sec, 1)
            self.last_explanation = f"DQN recommends switch, but holding {active_corridor} green for safety minimum ({remaining_min}s remaining)."
        else:
            # Action == 0 (Keep Green)
            self.last_explanation = f"{active_corridor} queue ({active_q} veh) heavier than {opposing_corridor} ({opp_q} veh). DQN Agent action: EXTEND_GREEN. Flow maintained."

        if should_switch:
            self._trigger_phase_switch()

        return self.current_phase

    def _trigger_phase_switch(self):
        """Initiate transition to conflicting green phase with yellow clearance."""
        self.is_in_transition = True
        self.transition_timer = 0.0
        self.total_switches += 1

        if self.current_green_phase == PHASE_NS_GREEN:
            self.current_phase = PHASE_NS_YELLOW
            self.target_green_phase = PHASE_EW_GREEN
        else:
            self.current_phase = PHASE_EW_YELLOW
            self.target_green_phase = PHASE_NS_GREEN

    def get_info(self) -> Dict[str, Any]:
        return {
            "mode": "AI_ADAPTIVE_DQN",
            "current_phase": self.current_phase,
            "green_elapsed_sec": round(self.green_elapsed_sec, 1),
            "is_in_transition": self.is_in_transition,
            "last_action": "SWITCH" if self.last_action == 1 else "KEEP",
            "total_switches": self.total_switches,
            "explanation": self.last_explanation
        }
