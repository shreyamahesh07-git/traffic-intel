"""
Benchmark Evaluation for Multi-Junction Fixed-Time Baseline Controller.
Runs Eclipse SUMO over city.sumocfg under static pre-timed signal timing plans.
Extracts empirical queue lengths, delays, average speeds, and throughput.
Saves CSV, JSON metrics, and performance comparison charts.
"""

import os
import sys
import time
import json
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from backend.config import DATA_DIR, EVAL_DIR
from backend.simulation.city_runner import CitySimulationRunner
from backend.controllers.multi_junction_fixed import MultiJunctionFixedController

OUTPUT_PNG_LOCAL = os.path.join(EVAL_DIR, "baseline_fixed_performance.png")
OUTPUT_PNG_ARTIFACT = r"C:\Users\Admin\.gemini\antigravity\brain\7b27e3e7-8efa-4acf-8d63-cb91792586f2\baseline_fixed_performance.png"
OUTPUT_JSON = os.path.join(DATA_DIR, "baseline_fixed_metrics.json")
OUTPUT_CSV = os.path.join(DATA_DIR, "baseline_fixed_history.csv")

def run_fixed_baseline_benchmark(total_steps: int = 500) -> dict:
    print("=" * 65)
    print("TRAFFIC INTEL: Running Fixed-Time Baseline Benchmark")
    print(f"Network: Connected Smart City (5 TLS, Roundabout, T-Junction)")
    print(f"Duration: {total_steps} simulation steps ({total_steps * 0.5:.1f}s simulated)")
    print("=" * 65)

    runner = CitySimulationRunner(use_gui=False)
    runner.start()
    controller = MultiJunctionFixedController()

    history = []
    total_queue_sum = 0
    max_queue_seen = 0

    for step in range(total_steps):
        # 1. Controller decisions for all 5 junctions
        target_phases = controller.step()
        for tlid, phase_idx in target_phases.items():
            runner.set_tl_phase(tlid, phase_idx)

        # 2. Advance TraCI step
        telemetry = runner.step()

        metrics = telemetry["metrics"]
        tls = telemetry["traffic_lights"]
        rb = telemetry["roundabout"]
        tj = telemetry["t_junction"]

        tot_q = metrics["total_queued"]
        total_queue_sum += tot_q
        max_queue_seen = max(max_queue_seen, tot_q)

        row = {
            "step": step + 1,
            "sim_time": telemetry["simulation_time"],
            "active_vehicles": metrics["total_active"],
            "total_queued": tot_q,
            "queue_ratio_pct": metrics["queue_ratio_pct"],
            "average_speed_kmh": metrics["average_speed_kmh"],
            "total_waiting_seconds": metrics["total_waiting_seconds"],
            "congestion_pct": metrics["congestion_pct"],
            "arrived_throughput": telemetry["total_arrived"],
            "departed_total": telemetry["total_departed"],
            # Per-junction queues
            "TL_CENTRAL_queue": tls.get("TL_CENTRAL", {}).get("queued_vehicles", 0),
            "TL_NW_queue": tls.get("TL_NW", {}).get("queued_vehicles", 0),
            "TL_NE_queue": tls.get("TL_NE", {}).get("queued_vehicles", 0),
            "TL_SW_queue": tls.get("TL_SW", {}).get("queued_vehicles", 0),
            "TL_SE_queue": tls.get("TL_SE", {}).get("queued_vehicles", 0),
            # Roundabout & T-Junction metrics
            "roundabout_circulating": rb["circulating_count"],
            "roundabout_avg_speed": rb["avg_speed_kmh"],
            "roundabout_entry_queue": rb["entry_queue_count"],
            "t_junction_active": tj["active_count"],
            "t_junction_queue": tj["queue_count"]
        }
        history.append(row)

        if step % 100 == 0 or step == total_steps - 1:
            print(f"Step {step:03d} (t={telemetry['simulation_time']:5.1f}s) | Active: {metrics['total_active']:2d} | Queued: {tot_q:2d} | Avg Spd: {metrics['average_speed_kmh']:4.1f} km/h | Wait: {metrics['total_waiting_seconds']:6.1f}s")

    runner.stop()

    # Compute Summary Statistics
    df = pd.DataFrame(history)
    avg_queue = round(df["total_queued"].mean(), 2)
    avg_speed = round(df["average_speed_kmh"].mean(), 2)
    final_waiting = round(df["total_waiting_seconds"].iloc[-1], 1)
    total_throughput = int(df["arrived_throughput"].iloc[-1])
    total_departed = int(df["departed_total"].iloc[-1])
    avg_delay_per_veh = round(final_waiting / max(1, total_departed), 2)

    summary = {
        "benchmark_type": "MULTI_JUNCTION_FIXED_TIME_BASELINE",
        "total_steps": total_steps,
        "simulated_duration_sec": total_steps * 0.5,
        "average_network_queue": avg_queue,
        "peak_network_queue": max_queue_seen,
        "average_network_speed_kmh": avg_speed,
        "final_cumulative_waiting_sec": final_waiting,
        "total_throughput_vehicles": total_throughput,
        "total_departed_vehicles": total_departed,
        "average_delay_per_vehicle_sec": avg_delay_per_veh,
        "junction_peak_queues": {
            "TL_CENTRAL": int(df["TL_CENTRAL_queue"].max()),
            "TL_NW": int(df["TL_NW_queue"].max()),
            "TL_NE": int(df["TL_NE_queue"].max()),
            "TL_SW": int(df["TL_SW_queue"].max()),
            "TL_SE": int(df["TL_SE_queue"].max())
        },
        "roundabout_peak_entry_queue": int(df["roundabout_entry_queue"].max()),
        "roundabout_avg_speed_kmh": round(df["roundabout_avg_speed"].mean(), 2)
    }

    # Save CSV and JSON
    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(EVAL_DIR, exist_ok=True)
    df.to_csv(OUTPUT_CSV, index=False)
    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    print(f"\n[BENCHMARK RESULTS SUMMARY]")
    print(f"Total Vehicles Serviced (Throughput): {total_throughput}")
    print(f"Average Network Queue Length        : {avg_queue} vehicles")
    print(f"Peak Queue Observed                 : {max_queue_seen} vehicles")
    print(f"Average Network Travel Speed        : {avg_speed} km/h")
    print(f"Cumulative Waiting Time             : {final_waiting} vehicle-seconds")
    print(f"Average Delay per Vehicle           : {avg_delay_per_veh} s/veh")
    print(f"Exported metrics to {OUTPUT_JSON} and {OUTPUT_CSV}")

    # Generate 4-Panel Performance Chart
    fig, axs = plt.subplots(2, 2, figsize=(15, 10), dpi=150)
    fig.patch.set_facecolor('#0f172a')
    for ax in axs.flat:
        ax.set_facecolor('#1e293b')
        ax.tick_params(colors='#94a3b8')
        ax.grid(True, linestyle=':', color='#334155', alpha=0.6)

    # Panel 1: Network Queues Over Time
    ax1 = axs[0, 0]
    ax1.plot(df["sim_time"], df["total_queued"], label="Total Network Queue", color="#ef4444", linewidth=2.5)
    ax1.plot(df["sim_time"], df["TL_CENTRAL_queue"], label="TL_CENTRAL Queue", color="#f59e0b", linestyle="--", linewidth=1.5)
    ax1.plot(df["sim_time"], df["TL_NW_queue"], label="TL_NW Queue", color="#38bdf8", linestyle=":", linewidth=1.2)
    ax1.plot(df["sim_time"], df["TL_NE_queue"], label="TL_NE Queue", color="#a855f7", linestyle=":", linewidth=1.2)
    ax1.set_title("Network & Junction Queues (Fixed-Time Baseline)", color="#f8fafc", fontsize=11, fontweight="bold")
    ax1.set_xlabel("Simulation Time (s)", color="#94a3b8", fontsize=9)
    ax1.set_ylabel("Queued Vehicles (count)", color="#94a3b8", fontsize=9)
    ax1.legend(facecolor='#0f172a', edgecolor='#334155', labelcolor='#e2e8f0', fontsize=8)

    # Panel 2: Average Network Travel Speed Over Time
    ax2 = axs[0, 1]
    ax2.plot(df["sim_time"], df["average_speed_kmh"], label="Network Average Speed", color="#10b981", linewidth=2)
    ax2.axhline(avg_speed, color="#f59e0b", linestyle="--", label=f"Mean Speed ({avg_speed} km/h)")
    ax2.set_title("Average Network Travel Speed (km/h)", color="#f8fafc", fontsize=11, fontweight="bold")
    ax2.set_xlabel("Simulation Time (s)", color="#94a3b8", fontsize=9)
    ax2.set_ylabel("Speed (km/h)", color="#94a3b8", fontsize=9)
    ax2.legend(facecolor='#0f172a', edgecolor='#334155', labelcolor='#e2e8f0', fontsize=8)

    # Panel 3: Cumulative Vehicle Waiting Time Accumulation
    ax3 = axs[1, 0]
    ax3.plot(df["sim_time"], df["total_waiting_seconds"], label="Cumulative Waiting Time", color="#f97316", linewidth=2.5)
    ax3.fill_between(df["sim_time"], df["total_waiting_seconds"], color="#f97316", alpha=0.15)
    ax3.set_title("Cumulative Delay Accumulation (Vehicle-Seconds)", color="#f8fafc", fontsize=11, fontweight="bold")
    ax3.set_xlabel("Simulation Time (s)", color="#94a3b8", fontsize=9)
    ax3.set_ylabel("Vehicle-Seconds", color="#94a3b8", fontsize=9)
    ax3.legend(facecolor='#0f172a', edgecolor='#334155', labelcolor='#e2e8f0', fontsize=8)

    # Panel 4: Roundabout Circulation & Entry Queue Performance
    ax4 = axs[1, 1]
    ax4.plot(df["sim_time"], df["roundabout_circulating"], label="Circulating Inside Roundabout", color="#38bdf8", linewidth=2)
    ax4.plot(df["sim_time"], df["roundabout_entry_queue"], label="Entry Queues at Yield Lines", color="#e11d48", linestyle="--", linewidth=1.8)
    ax4.set_title("Garden Parkway Roundabout Dynamics", color="#f8fafc", fontsize=11, fontweight="bold")
    ax4.set_xlabel("Simulation Time (s)", color="#94a3b8", fontsize=9)
    ax4.set_ylabel("Vehicles (count)", color="#94a3b8", fontsize=9)
    ax4.legend(facecolor='#0f172a', edgecolor='#334155', labelcolor='#e2e8f0', fontsize=8)

    plt.suptitle("TRAFFIC INTEL — Fixed-Time Multi-Junction Baseline Performance Benchmark",
                 color="#f8fafc", fontsize=14, fontweight="bold", y=0.98)
    plt.tight_layout(rect=[0, 0.03, 1, 0.95])

    # Save to both local and artifact directories
    plt.savefig(OUTPUT_PNG_LOCAL, facecolor=fig.get_facecolor(), edgecolor='none', dpi=150)
    os.makedirs(os.path.dirname(OUTPUT_PNG_ARTIFACT), exist_ok=True)
    plt.savefig(OUTPUT_PNG_ARTIFACT, facecolor=fig.get_facecolor(), edgecolor='none', dpi=150)
    plt.close()
    print(f"Saved benchmark performance charts to:\n  - {OUTPUT_PNG_LOCAL}\n  - {OUTPUT_PNG_ARTIFACT}")

    return summary

if __name__ == "__main__":
    run_fixed_baseline_benchmark(total_steps=500)
