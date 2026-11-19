import urllib.request
import urllib.parse
import json
import time

base = "http://127.0.0.1:8000"

print("1. Activating Scenario B: North Surge...")
data = urllib.parse.urlencode({"scenario": "SURGE_NORTH"}).encode()
req = urllib.request.Request(f"{base}/api/simulation/scenario", data=data)
with urllib.request.urlopen(req) as resp:
    res = json.loads(resp.read().decode())
    print("Scenario response:", res)

print("\n2. Triggering Traffic Surge of 8 vehicles on North approach...")
data_surge = urllib.parse.urlencode({"approach": "north", "count": "8"}).encode()
req_surge = urllib.request.Request(f"{base}/api/simulation/surge", data=data_surge)
with urllib.request.urlopen(req_surge) as resp:
    res_surge = json.loads(resp.read().decode())
    print("Surge response:", res_surge)

print("\n3. Monitoring 4-Way Intersection over 15 seconds as vehicles approach and DQN responds...")
for step in range(8):
    time.sleep(2.0)
    with urllib.request.urlopen(f"{base}/api/telemetry") as resp:
        snap = json.loads(resp.read().decode())
        ctrl = snap.get("controller_info", {})
        int4 = snap.get("intersection_4way", {})
        app = int4.get("approaches", {})
        north = app.get("north", {})
        south = app.get("south", {})
        east = app.get("east", {})
        west = app.get("west", {})
        print(f"T+{(step+1)*2}s | Active Phase: {int4.get('phase_description')} [{north.get('signal_color')}] | North Q: {north.get('queued_count')}, Act: {north.get('approaching_count')} | East Q: {east.get('queued_count')} | Tot Fleet: {snap.get('metrics', {}).get('total_active')}")
        print(f"     XAI Reasoning: {ctrl.get('explanation')}")

print("\n4. Resetting Scenario back to NORMAL...")
req_reset = urllib.request.Request(f"{base}/api/simulation/reset_scenario", data=b"")
with urllib.request.urlopen(req_reset) as resp:
    print("Reset response:", json.loads(resp.read().decode()))
