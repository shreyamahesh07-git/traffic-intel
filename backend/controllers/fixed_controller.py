import os
import sys
from typing import Dict, Any, Optional

# Load backend configuration
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from backend.config import (
    DEFAULT_FIXED_GREEN,
    YELLOW_PHASE_DURATION,
    ALL_RED_PHASE_DURATION,
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

class FixedTimeController:
    """
    Conventional Fixed-Time Traffic Signal Controller.
    Cycles through predetermined static signal timing intervals regardless of real-time queues.
    Standard cycle:
      - North-South Green: 30s
      - North-South Yellow: 3s
      - Clearance All-Red: 2s
      - East-West Green: 30s
      - East-West Yellow: 3s
      - Clearance All-Red: 2s
    """
    def __init__(self, green_duration: float = DEFAULT_FIXED_GREEN):
        self.green_duration = green_duration
        self.yellow_duration = YELLOW_PHASE_DURATION
        self.all_red_duration = ALL_RED_PHASE_DURATION
        
        self.current_phase = PHASE_NS_GREEN
        self.phase_elapsed_sec = 0.0
        self.last_explanation = "Fixed-Time Controller: North-South Green cycle active (30s static timer)."

    def reset(self):
        """Reset controller to initial cycle state."""
        self.current_phase = PHASE_NS_GREEN
        self.phase_elapsed_sec = 0.0
        self.last_explanation = "Fixed-Time Controller reset to North-South Green."

    def step(self, telemetry: Optional[Dict[str, Any]] = None, step_length: float = SIMULATION_STEP_LENGTH) -> int:
        """
        Advance one simulation step and return the target phase index.
        Executes strict sequential fixed timing cycles without responding to traffic density.
        """
        self.phase_elapsed_sec += step_length

        if self.current_phase == PHASE_NS_GREEN:
            rem = max(0.0, round(self.green_duration - self.phase_elapsed_sec, 1))
            self.last_explanation = f"Fixed-Time: North-South Green ({round(self.phase_elapsed_sec, 1)}s / {int(self.green_duration)}s). Next scheduled switch in {rem}s regardless of queue distribution."
            if self.phase_elapsed_sec >= self.green_duration:
                self.current_phase = PHASE_NS_YELLOW
                self.phase_elapsed_sec = 0.0
                self.last_explanation = "Fixed-Time: Static timer reached 30s limit. Switching North-South to Yellow."

        elif self.current_phase == PHASE_NS_YELLOW:
            self.last_explanation = f"Fixed-Time: North-South Yellow clearance ({round(self.phase_elapsed_sec, 1)}s / {int(self.yellow_duration)}s)."
            if self.phase_elapsed_sec >= self.yellow_duration:
                self.current_phase = PHASE_ALL_RED_NS
                self.phase_elapsed_sec = 0.0

        elif self.current_phase == PHASE_ALL_RED_NS:
            self.last_explanation = "Fixed-Time: All-Red safety interval."
            if self.phase_elapsed_sec >= self.all_red_duration:
                self.current_phase = PHASE_EW_GREEN
                self.phase_elapsed_sec = 0.0
                self.last_explanation = "Fixed-Time: East-West Green cycle started (30s static timer)."

        elif self.current_phase == PHASE_EW_GREEN:
            rem = max(0.0, round(self.green_duration - self.phase_elapsed_sec, 1))
            self.last_explanation = f"Fixed-Time: East-West Green ({round(self.phase_elapsed_sec, 1)}s / {int(self.green_duration)}s). Next scheduled switch in {rem}s regardless of queue distribution."
            if self.phase_elapsed_sec >= self.green_duration:
                self.current_phase = PHASE_EW_YELLOW
                self.phase_elapsed_sec = 0.0
                self.last_explanation = "Fixed-Time: Static timer reached 30s limit. Switching East-West to Yellow."

        elif self.current_phase == PHASE_EW_YELLOW:
            self.last_explanation = f"Fixed-Time: East-West Yellow clearance ({round(self.phase_elapsed_sec, 1)}s / {int(self.yellow_duration)}s)."
            if self.phase_elapsed_sec >= self.yellow_duration:
                self.current_phase = PHASE_ALL_RED_EW
                self.phase_elapsed_sec = 0.0

        elif self.current_phase == PHASE_ALL_RED_EW:
            self.last_explanation = "Fixed-Time: All-Red safety interval."
            if self.phase_elapsed_sec >= self.all_red_duration:
                self.current_phase = PHASE_NS_GREEN
                self.phase_elapsed_sec = 0.0
                self.last_explanation = "Fixed-Time: North-South Green cycle started (30s static timer)."

        return self.current_phase

    def get_info(self) -> Dict[str, Any]:
        return {
            "mode": "FIXED_TIME",
            "current_phase": self.current_phase,
            "phase_elapsed_sec": round(self.phase_elapsed_sec, 1),
            "green_duration": self.green_duration,
            "explanation": self.last_explanation
        }
