"""
Direct Comparative Benchmark: Fixed-Time Baseline vs Adaptive DQN Controller.
Runs identical 500-step SUMO traffic demand on Connected City,
evaluates queue reductions, delays, speed stabilization, and generates side-by-side comparison charts.
"""

import os
import sys
import json
from typing import Tuple, Dict, Any, List
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from backend.config import DATA_DIR, EVAL_DIR
from backend.simulation.city_runner import CitySimulationRunner
from backend.controllers.adaptive_city_controller import AdaptiveCityController

COMPARISON_PNG_LOCAL = os.path.join(EVAL_DIR, "baseline_vs_dqn_comparison.png")
COMPARISON_PNG_ARTIFACT = r"C:\Users\Admin\.gemini\antigravity\brain\7b27e3e7-8efa-4acf-8d63-cb91792586f2\baseline_vs_dqn_comparison.png"
COMPARISON_JSON = os.path.join(DATA_DIR, "comparison_report.json")
BASELINE_CSV = os.path.join(DATA_DIR, "baseline_fixed_history.csv")
BASELINE_JSON = os.path.join(DATA_DIR, "baseline_fixed_metrics.json")

def run_adaptive_dqn_trial(total_steps: int = 500) -> Tuple[dict, pd.DataFrame]:
    print("=" * 65)
    print("TRAFFIC INTEL: Running Adaptive DQN Evaluation Trial (500 steps)")
    print("=" * 65)

    runner = CitySimulationRunner(use_gui=False)
    runner.start()
    controller = AdaptiveCityController()

    history = []
    total_q_sum = 0
    max_q_seen = 0

    for step in range(total_steps):
        telemetry = runner.step()
        controller.step(telemetry, runner)

        m = telemetry["metrics"]
        tls = telemetry["traffic_lights"]
        rb = telemetry["roundabout"]
        tj = telemetry["t_junction"]

        tot_q = m["total_queued"]
        total_q_sum += tot_q
        max_q_seen = max(max_q_seen, tot_q)

        row = {
            "step": step + 1,
            "sim_time": telemetry["simulation_time"],
            "active_vehicles": m["total_active"],
            "total_queued": tot_q,
            "queue_ratio_pct": m["queue_ratio_pct"],
            "average_speed_kmh": m["average_speed_kmh"],
            "total_waiting_seconds": m["total_waiting_seconds"],
            "congestion_pct": m["congestion_pct"],
            "arrived_throughput": telemetry["total_arrived"],
            "TL_CENTRAL_queue": tls.get("TL_CENTRAL", {}).get("queued_vehicles", 0),
            "roundabout_circulating": rb["circulating_count"],
            "roundabout_entry_queue": rb["entry_queue_count"]
        }
        history.append(row)

        if step % 100 == 0 or step == total_steps - 1:
            print(f"DQN Step {step:03d} (t={telemetry['simulation_time']:5.1f}s) | Active: {m['total_active']:2d} | Queued: {tot_q:2d} | Avg Spd: {m['average_speed_kmh']:4.1f} km/h | Wait: {m['total_waiting_seconds']:6.1f}s")

    runner.stop()
    df = pd.DataFrame(history)

    avg_queue = round(df["total_queued"].mean(), 2)
    avg_speed = round(df["average_speed_kmh"].mean(), 2)
    avg_wait = round(df["total_waiting_seconds"].mean(), 1)
    final_wait = round(df["total_waiting_seconds"].iloc[-1], 1)
    throughput = int(df["arrived_throughput"].iloc[-1])

    summary = {
        "average_network_queue": avg_queue,
        "peak_network_queue": max_q_seen,
        "average_network_speed_kmh": avg_speed,
        "mean_waiting_delay_sec": avg_wait,
        "final_cumulative_waiting_sec": final_wait,
        "total_throughput_vehicles": throughput,
        "central_peak_queue": int(df["TL_CENTRAL_queue"].max())
    }
    return summary, df

def compare_baseline_and_dqn():
    if not os.path.exists(BASELINE_JSON) or not os.path.exists(BASELINE_CSV):
        print("Error: Baseline files not found. Run benchmark_fixed_baseline.py first.")
        return

    with open(BASELINE_JSON, "r", encoding="utf-8") as f:
        fixed_metrics = json.load(f)
    fixed_df = pd.read_csv(BASELINE_CSV)
    fixed_avg_wait = round(fixed_df["total_waiting_seconds"].mean(), 1)

    dqn_metrics, dqn_df = run_adaptive_dqn_trial(total_steps=len(fixed_df))

    # Calculate Empirical Improvements
    q_reduction_pct = round(((fixed_metrics["average_network_queue"] - dqn_metrics["average_network_queue"]) / fixed_metrics["average_network_queue"]) * 100, 1)
    peak_q_reduction_pct = round(((fixed_metrics["peak_network_queue"] - dqn_metrics["peak_network_queue"]) / fixed_metrics["peak_network_queue"]) * 100, 1)
    central_q_reduction_pct = round(((fixed_metrics["junction_peak_queues"]["TL_CENTRAL"] - dqn_metrics["central_peak_queue"]) / fixed_metrics["junction_peak_queues"]["TL_CENTRAL"]) * 100, 1)
    speed_gain_pct = round(((dqn_metrics["average_network_speed_kmh"] - fixed_metrics["average_network_speed_kmh"]) / fixed_metrics["average_network_speed_kmh"]) * 100, 1)
    delay_reduction_pct = round(((fixed_avg_wait - dqn_metrics["mean_waiting_delay_sec"]) / fixed_avg_wait) * 100, 1)
    throughput_gain_pct = round(((dqn_metrics["total_throughput_vehicles"] - fixed_metrics["total_throughput_vehicles"]) / max(1, fixed_metrics["total_throughput_vehicles"])) * 100, 1)

    comparison_report = {
        "benchmark_duration_steps": len(fixed_df),
        "fixed_baseline": {
            **fixed_metrics,
            "mean_waiting_delay_sec": fixed_avg_wait
        },
        "adaptive_dqn": dqn_metrics,
        "percentage_improvements": {
            "average_queue_reduction_pct": q_reduction_pct,
            "peak_queue_reduction_pct": peak_q_reduction_pct,
            "central_plaza_peak_queue_reduction_pct": central_q_reduction_pct,
            "average_speed_gain_pct": speed_gain_pct,
            "mean_delay_reduction_pct": delay_reduction_pct,
            "throughput_gain_pct": throughput_gain_pct
        }
    }

    with open(COMPARISON_JSON, "w", encoding="utf-8") as f:
        json.dump(comparison_report, f, indent=2)
    print(f"\nSaved comparison report to {COMPARISON_JSON}")

    # Generate Side-by-Side Comparison Plot
    fig, axs = plt.subplots(2, 2, figsize=(15, 10), dpi=150)
    fig.patch.set_facecolor('#0f172a')
    for ax in axs.flat:
        ax.set_facecolor('#1e293b')
        ax.tick_params(colors='#94a3b8')
        ax.grid(True, linestyle=':', color='#334155', alpha=0.6)

    # 1. Total Network Queue: Fixed vs DQN
    axs[0, 0].plot(fixed_df["sim_time"], fixed_df["total_queued"], label=f"Fixed-Time Baseline (Mean: {fixed_metrics['average_network_queue']})", color="#ef4444", linewidth=2.2)
    axs[0, 0].plot(dqn_df["sim_time"], dqn_df["total_queued"], label=f"Adaptive DQN (Mean: {dqn_metrics['average_network_queue']}, {q_reduction_pct:+.1f}%)", color="#10b981", linewidth=2.2)
    axs[0, 0].set_title("Total Network Queue: Fixed Baseline vs Adaptive DQN", color="#f8fafc", fontsize=11, fontweight="bold")
    axs[0, 0].set_xlabel("Simulation Time (s)", color="#94a3b8", fontsize=9)
    axs[0, 0].set_ylabel("Queued Vehicles", color="#94a3b8", fontsize=9)
    axs[0, 0].legend(facecolor='#0f172a', edgecolor='#334155', labelcolor='#e2e8f0', fontsize=8.5)

    # 2. Central Plaza TL_CENTRAL Queue Bottleneck
    axs[0, 1].plot(fixed_df["sim_time"], fixed_df["TL_CENTRAL_queue"], label=f"Fixed-Time (Peak: {fixed_metrics['junction_peak_queues']['TL_CENTRAL']})", color="#f59e0b", linestyle="--", linewidth=2)
    axs[0, 1].plot(dqn_df["sim_time"], dqn_df["TL_CENTRAL_queue"], label=f"Adaptive DQN (Peak: {dqn_metrics['central_peak_queue']}, {central_q_reduction_pct:+.1f}%)", color="#38bdf8", linewidth=2.2)
    axs[0, 1].set_title("Central Plaza (TL_CENTRAL) Queue Alleviation", color="#f8fafc", fontsize=11, fontweight="bold")
    axs[0, 1].set_xlabel("Simulation Time (s)", color="#94a3b8", fontsize=9)
    axs[0, 1].set_ylabel("Queued Vehicles", color="#94a3b8", fontsize=9)
    axs[0, 1].legend(facecolor='#0f172a', edgecolor='#334155', labelcolor='#e2e8f0', fontsize=8.5)

    # 3. Average Travel Speed Comparison
    axs[1, 0].plot(fixed_df["sim_time"], fixed_df["average_speed_kmh"], label=f"Fixed Baseline (Mean: {fixed_metrics['average_network_speed_kmh']} km/h)", color="#ef4444", linestyle=":", linewidth=1.8)
    axs[1, 0].plot(dqn_df["sim_time"], dqn_df["average_speed_kmh"], label=f"Adaptive DQN (Mean: {dqn_metrics['average_network_speed_kmh']} km/h, {speed_gain_pct:+.1f}%)", color="#10b981", linewidth=2.2)
    axs[1, 0].set_title("Average Network Travel Speed (km/h)", color="#f8fafc", fontsize=11, fontweight="bold")
    axs[1, 0].set_xlabel("Simulation Time (s)", color="#94a3b8", fontsize=9)
    axs[1, 0].set_ylabel("Speed (km/h)", color="#94a3b8", fontsize=9)
    axs[1, 0].legend(facecolor='#0f172a', edgecolor='#334155', labelcolor='#e2e8f0', fontsize=8.5)

    # 4. Vehicle Waiting Delay Accumulation
    axs[1, 1].plot(fixed_df["sim_time"], fixed_df["total_waiting_seconds"], label=f"Fixed Mean Delay: {fixed_avg_wait}s", color="#f97316", linewidth=2.2)
    axs[1, 1].plot(dqn_df["sim_time"], dqn_df["total_waiting_seconds"], label=f"DQN Mean Delay: {dqn_metrics['mean_waiting_delay_sec']}s ({delay_reduction_pct:+.1f}%)", color="#06b6d4", linewidth=2.2)
    axs[1, 1].set_title("Vehicle Waiting Delay Dynamics", color="#f8fafc", fontsize=11, fontweight="bold")
    axs[1, 1].set_xlabel("Simulation Time (s)", color="#94a3b8", fontsize=9)
    axs[1, 1].set_ylabel("Vehicle-Seconds", color="#94a3b8", fontsize=9)
    axs[1, 1].legend(facecolor='#0f172a', edgecolor='#334155', labelcolor='#e2e8f0', fontsize=8.5)

    plt.suptitle("TRAFFIC INTEL — Empirical Performance Comparison: Fixed-Time Baseline vs Adaptive DQN\n"
                 f"Queue Change: {q_reduction_pct:+.1f}% | Delay Change: {delay_reduction_pct:+.1f}% | Speed Change: {speed_gain_pct:+.1f}%",
                 color="#f8fafc", fontsize=13, fontweight="bold", y=0.98)
    plt.tight_layout(rect=[0, 0.03, 1, 0.94])

    plt.savefig(COMPARISON_PNG_LOCAL, facecolor=fig.get_facecolor(), edgecolor='none', dpi=150)
    os.makedirs(os.path.dirname(COMPARISON_PNG_ARTIFACT), exist_ok=True)
    plt.savefig(COMPARISON_PNG_ARTIFACT, facecolor=fig.get_facecolor(), edgecolor='none', dpi=150)
    plt.close()
    print(f"Saved comparative performance charts to:\n  - {COMPARISON_PNG_LOCAL}\n  - {COMPARISON_PNG_ARTIFACT}")

    print("\n" + "=" * 65)
    print("EMPIRICAL COMPARISON RESULTS:")
    print(f"  • Average Network Queue : {fixed_metrics['average_network_queue']} -> {dqn_metrics['average_network_queue']} ({q_reduction_pct:+.1f}%)")
    print(f"  • Peak Network Queue    : {fixed_metrics['peak_network_queue']} -> {dqn_metrics['peak_network_queue']} ({peak_q_reduction_pct:+.1f}%)")
    print(f"  • Central Plaza Peak Q  : {fixed_metrics['junction_peak_queues']['TL_CENTRAL']} -> {dqn_metrics['central_peak_queue']} ({central_q_reduction_pct:+.1f}%)")
    print(f"  • Average Network Speed : {fixed_metrics['average_network_speed_kmh']} -> {dqn_metrics['average_network_speed_kmh']} km/h ({speed_gain_pct:+.1f}%)")
    print(f"  • Mean Waiting Delay    : {fixed_avg_wait} -> {dqn_metrics['mean_waiting_delay_sec']} s ({delay_reduction_pct:+.1f}%)")
    print("=" * 65)

if __name__ == "__main__":
    compare_baseline_and_dqn()
