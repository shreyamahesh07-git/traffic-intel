import os
import sys
import time
import json
import pandas as pd
import matplotlib
matplotlib.use("Agg")  # Non-interactive backend
import matplotlib.pyplot as plt
from typing import Dict, Any, List, Tuple

# Load backend configuration
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from backend.config import DATA_DIR
from backend.simulation.sim_runner import SumoSimulationRunner
from backend.density.density_estimator import TrafficDensityEstimator
from backend.controllers.fixed_controller import FixedTimeController
from backend.controllers.adaptive_controller import AdaptiveDQNController

def run_evaluation_trial(controller_type: str, total_steps: int = 200) -> Dict[str, Any]:
    """
    Executes a benchmark simulation trial under a specific traffic signal controller.
    Records step-by-step queues, waiting times, and throughput.
    """
    print(f"Running evaluation trial: {controller_type} for {total_steps} steps...")
    runner = SumoSimulationRunner(use_gui=False)
    runner.start()
    
    density_estimator = TrafficDensityEstimator()
    if controller_type == "AI_ADAPTIVE":
        controller = AdaptiveDQNController()
    else:
        controller = FixedTimeController()

    step_history = []
    total_queue_sum = 0
    max_queue_observed = 0

    for step in range(total_steps):
        telemetry = runner.step()
        density_info = density_estimator.compute_density(telemetry)
        dqn_state = density_info["dqn_state"]

        # Apply controller decision
        if controller_type == "AI_ADAPTIVE":
            target_phase = controller.step(dqn_state)
        else:
            target_phase = controller.step()

        runner.set_phase(target_phase)

        tot_q = density_info["total_intersection_queue"]
        tot_wait = density_info["total_intersection_wait_sec"]
        total_queue_sum += tot_q
        max_queue_observed = max(max_queue_observed, tot_q)

        step_history.append({
            "step": step + 1,
            "sim_time": telemetry["simulation_time_sec"],
            "queue": tot_q,
            "wait_time": tot_wait,
            "cumulative_wait": runner.cumulative_waiting_time,
            "active_vehicles": telemetry["metrics"]["active_vehicles"],
            "arrived": runner.total_arrived
        })

    runner.close()

    avg_queue = round(total_queue_sum / total_steps, 2)
    final_wait = round(runner.cumulative_waiting_time, 1)
    throughput = runner.total_arrived
    avg_delay_per_veh = round(final_wait / max(1, runner.total_departed), 2)

    return {
        "controller": controller_type,
        "total_steps": total_steps,
        "total_waiting_time_sec": final_wait,
        "average_queue_length": avg_queue,
        "max_queue_observed": max_queue_observed,
        "total_throughput_vehicles": throughput,
        "average_delay_per_vehicle_sec": avg_delay_per_veh,
        "history": step_history
    }

def run_comparative_benchmark(total_steps: int = 200) -> Dict[str, Any]:
    """
    Executes full comparative evaluation between Fixed-Time Baseline and AI Adaptive DQN.
    Calculates improvements, exports CSV report, and generates high-resolution charts.
    """
    os.makedirs(DATA_DIR, exist_ok=True)
    csv_path = os.path.join(DATA_DIR, "comparison_results.csv")
    chart_path = os.path.join(DATA_DIR, "comparison_chart.png")

    # 1. Run Baseline Trial
    fixed_res = run_evaluation_trial("FIXED_TIME", total_steps=total_steps)
    
    # Small pause to allow socket cleanup
    time.sleep(2)

    # 2. Run AI Adaptive Trial
    ai_res = run_evaluation_trial("AI_ADAPTIVE", total_steps=total_steps)

    # 3. Calculate Improvement Metrics
    wait_imp = round(((fixed_res["total_waiting_time_sec"] - ai_res["total_waiting_time_sec"]) / fixed_res["total_waiting_time_sec"]) * 100.0, 2)
    queue_imp = round(((fixed_res["average_queue_length"] - ai_res["average_queue_length"]) / fixed_res["average_queue_length"]) * 100.0, 2)
    delay_imp = round(((fixed_res["average_delay_per_vehicle_sec"] - ai_res["average_delay_per_vehicle_sec"]) / fixed_res["average_delay_per_vehicle_sec"]) * 100.0, 2)
    throughput_imp = round(((ai_res["total_throughput_vehicles"] - fixed_res["total_throughput_vehicles"]) / max(1, fixed_res["total_throughput_vehicles"])) * 100.0, 2)

    comparison_summary = {
        "fixed_time": fixed_res,
        "ai_adaptive": ai_res,
        "improvements": {
            "waiting_time_reduction_pct": wait_imp,
            "queue_length_reduction_pct": queue_imp,
            "average_delay_reduction_pct": delay_imp,
            "throughput_increase_pct": throughput_imp
        }
    }

    # 4. Save CSV Benchmark Report
    df_compare = pd.DataFrame([
        {
            "Metric": "Total Waiting Time (s)",
            "Fixed-Time Baseline": fixed_res["total_waiting_time_sec"],
            "AI Adaptive (DQN)": ai_res["total_waiting_time_sec"],
            "AI Improvement (%)": f"-{wait_imp}%" if wait_imp > 0 else f"+{abs(wait_imp)}%"
        },
        {
            "Metric": "Average Queue Length (veh)",
            "Fixed-Time Baseline": fixed_res["average_queue_length"],
            "AI Adaptive (DQN)": ai_res["average_queue_length"],
            "AI Improvement (%)": f"-{queue_imp}%" if queue_imp > 0 else f"+{abs(queue_imp)}%"
        },
        {
            "Metric": "Max Queue Observed (veh)",
            "Fixed-Time Baseline": fixed_res["max_queue_observed"],
            "AI Adaptive (DQN)": ai_res["max_queue_observed"],
            "AI Improvement (%)": f"{ai_res['max_queue_observed'] - fixed_res['max_queue_observed']} veh"
        },
        {
            "Metric": "Average Delay / Vehicle (s)",
            "Fixed-Time Baseline": fixed_res["average_delay_per_vehicle_sec"],
            "AI Adaptive (DQN)": ai_res["average_delay_per_vehicle_sec"],
            "AI Improvement (%)": f"-{delay_imp}%" if delay_imp > 0 else f"+{abs(delay_imp)}%"
        },
        {
            "Metric": "Total Throughput (veh)",
            "Fixed-Time Baseline": fixed_res["total_throughput_vehicles"],
            "AI Adaptive (DQN)": ai_res["total_throughput_vehicles"],
            "AI Improvement (%)": f"+{throughput_imp}%"
        }
    ])
    df_compare.to_csv(csv_path, index=False)
    print(f"Saved CSV benchmark report to {csv_path}")

    # 5. Generate Matplotlib Comparative Visualizations
    fig, axs = plt.subplots(2, 2, figsize=(14, 10))
    fig.patch.set_facecolor("#14161b")

    for ax in axs.flat:
        ax.set_facecolor("#1a1d24")
        ax.tick_params(colors="#8e96a8")
        for spine in ax.spines.values():
            spine.set_color("#262a34")

    # Bar 1: Total Waiting Time
    metrics_bars = ["Waiting Time (s)", "Avg Delay/Veh (s)"]
    x = [0, 1]
    w = 0.35
    fixed_vals = [fixed_res["total_waiting_time_sec"], fixed_res["average_delay_per_vehicle_sec"]]
    ai_vals = [ai_res["total_waiting_time_sec"], ai_res["average_delay_per_vehicle_sec"]]
    
    axs[0, 0].bar([i - w/2 for i in x], fixed_vals, width=w, label="Fixed-Time", color="#ff7043")
    axs[0, 0].bar([i + w/2 for i in x], ai_vals, width=w, label="AI Adaptive (DQN)", color="#00e5ff")
    axs[0, 0].set_title("Waiting Time & Delay Comparison", color="#f0f2f5", fontweight="bold")
    axs[0, 0].set_xticks(x)
    axs[0, 0].set_xticklabels(metrics_bars, color="#f0f2f5")
    axs[0, 0].legend(facecolor="#14161b", edgecolor="#262a34", labelcolor="#f0f2f5")
    axs[0, 0].grid(axis="y", linestyle="--", alpha=0.3, color="#5d6577")

    # Bar 2: Queue Lengths
    axs[0, 1].bar([0 - w/2, 1 - w/2], [fixed_res["average_queue_length"], fixed_res["max_queue_observed"]], width=w, label="Fixed-Time", color="#ff7043")
    axs[0, 1].bar([0 + w/2, 1 + w/2], [ai_res["average_queue_length"], ai_res["max_queue_observed"]], width=w, label="AI Adaptive (DQN)", color="#00e5ff")
    axs[0, 1].set_title("Queue Length Metrics (Vehicles)", color="#f0f2f5", fontweight="bold")
    axs[0, 1].set_xticks([0, 1])
    axs[0, 1].set_xticklabels(["Avg Queue Length", "Max Queue Observed"], color="#f0f2f5")
    axs[0, 1].legend(facecolor="#14161b", edgecolor="#262a34", labelcolor="#f0f2f5")
    axs[0, 1].grid(axis="y", linestyle="--", alpha=0.3, color="#5d6577")

    # Plot 3: Step-by-Step Cumulative Waiting Delay Progression
    fixed_hist = fixed_res["history"]
    ai_hist = ai_res["history"]
    times = [h["sim_time"] for h in fixed_hist]
    fixed_cum_wait = [h["cumulative_wait"] for h in fixed_hist]
    ai_cum_wait = [h["cumulative_wait"] for h in ai_hist]

    axs[1, 0].plot(times, fixed_cum_wait, label="Fixed-Time Baseline", color="#ff7043", linewidth=2.5)
    axs[1, 0].plot(times, ai_cum_wait, label="AI Adaptive (DQN)", color="#00e5ff", linewidth=2.5)
    axs[1, 0].set_title("Cumulative Delay Progression Over Time", color="#f0f2f5", fontweight="bold")
    axs[1, 0].set_xlabel("Simulation Time (seconds)", color="#8e96a8")
    axs[1, 0].set_ylabel("Cumulative Delay (seconds)", color="#8e96a8")
    axs[1, 0].legend(facecolor="#14161b", edgecolor="#262a34", labelcolor="#f0f2f5")
    axs[1, 0].grid(True, linestyle="--", alpha=0.3, color="#5d6577")

    # Plot 4: Step-by-Step Active Queue Length
    fixed_q = [h["queue"] for h in fixed_hist]
    ai_q = [h["queue"] for h in ai_hist]

    axs[1, 1].plot(times, fixed_q, label="Fixed-Time Queue", color="#ff7043", alpha=0.7)
    axs[1, 1].plot(times, ai_q, label="AI Adaptive Queue", color="#00e676", linewidth=2)
    axs[1, 1].set_title("Intersection Queue Oscillation Over Time", color="#f0f2f5", fontweight="bold")
    axs[1, 1].set_xlabel("Simulation Time (seconds)", color="#8e96a8")
    axs[1, 1].set_ylabel("Queued Vehicles", color="#8e96a8")
    axs[1, 1].legend(facecolor="#14161b", edgecolor="#262a34", labelcolor="#f0f2f5")
    axs[1, 1].grid(True, linestyle="--", alpha=0.3, color="#5d6577")

    plt.tight_layout()
    plt.savefig(chart_path, dpi=180, facecolor=fig.get_facecolor(), edgecolor="none")
    plt.close()
    print(f"Saved comparative chart to {chart_path}")

    # Print summary table
    print("\n" + "="*70)
    print("      TRAFFIC INTEL: PERFORMANCE BENCHMARK EVALUATION RESULTS")
    print("="*70)
    print(df_compare.to_string(index=False))
    print("="*70)
    print(f"Waiting Time Reduction : {wait_imp}%")
    print(f"Average Queue Reduction: {queue_imp}%")
    print(f"Delay per Vehicle Red. : {delay_imp}%")
    print("="*70)

    return comparison_summary

if __name__ == "__main__":
    run_comparative_benchmark(total_steps=150)

