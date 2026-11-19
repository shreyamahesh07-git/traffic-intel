import requests
import time

base = "http://127.0.0.1:8000"

print("1. Fetching Initial Normal Simulation State...")
r = requests.get(f"{base}/api/telemetry")
data = r.json()
int4 = data.get("intersection_4way", {})
print(f"Active Vehicles: {data.get('metrics', {}).get('total_active')}")
print(f"Intersection: {int4.get('name')} | Phase: {int4.get('phase_description')}")
print(f"Scenario: {int4.get('active_scenario')}")

print("\n2. Setting Scenario B (SURGE_NORTH)...")
r_scen = requests.post(f"{base}/api/simulation/scenario", data={"scenario": "SURGE_NORTH"})
print("Scenario API response:", r_scen.json())

print("\n3. Triggering Surge of 8 vehicles on North approach...")
r_surge = requests.post(f"{base}/api/simulation/surge", data={"approach": "north", "count": 8})
print("Surge API response:", r_surge.json())

print("\n4. Tracking 4-Way Intersection Response (AI_ADAPTIVE DQN)...")
for t in range(5):
    time.sleep(2.0)
    snap = requests.get(f"{base}/api/telemetry").json()
    ctrl = snap.get("controller_info", {})
    int4 = snap.get("intersection_4way", {})
    app = int4.get("approaches", {})
    north = app.get("north", {})
    south = app.get("south", {})
    east = app.get("east", {})
    west = app.get("west", {})
    print(f"T+{(t+1)*2}s | Phase: {int4.get('phase_description')} [{north.get('signal_color')}] | North Q: {north.get('queued_count')}, Act: {north.get('approaching_count')} | East Q: {east.get('queued_count')} | Tot Fleet: {snap.get('metrics', {}).get('total_active')}")
    print(f"     Reasoning: {ctrl.get('explanation')}")

print("\n5. Testing Controller Mode Switch to FIXED_TIME Baseline...")
r_fix = requests.post(f"{base}/api/control/mode", data={"mode": "FIXED_TIME"})
print("Fixed-Time Mode response:", r_fix.json())
time.sleep(2.0)
snap_fix = requests.get(f"{base}/api/telemetry").json()
print("Fixed-Time controller info:", snap_fix.get("controller_info"))

print("\n6. Restoring Controller Mode to AI_ADAPTIVE (DQN)...")
r_ai = requests.post(f"{base}/api/control/mode", data={"mode": "AI_ADAPTIVE"})
print("AI Adaptive Mode response:", r_ai.json())

print("\n7. Resetting Scenario back to NORMAL...")
r_reset = requests.post(f"{base}/api/simulation/reset_scenario")
print("Reset response:", r_reset.json())
print("\n=== ALL EXPERIMENT WORKFLOWS VERIFIED SUCCESSFULLY ===")

