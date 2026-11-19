import urllib.request
import json

url = "http://127.0.0.1:8000/api/telemetry"
req = urllib.request.Request(url)
with urllib.request.urlopen(req) as resp:
    data = json.loads(resp.read().decode('utf-8'))

print("Top-level keys:", list(data.keys()))
if "telemetry" in data:
    telem = data["telemetry"]
    print("Keys in data['telemetry']:", list(telem.keys()))
    if "intersection_4way" in telem:
        int4 = telem["intersection_4way"]
        print("\n=== INTERSECTION_4WAY in telemetry ===")
        print("ID:", int4.get("id"))
        print("Name:", int4.get("name"))
        print("Active Phase:", int4.get("active_phase"), int4.get("phase_description"))
        print("Scenario:", int4.get("active_scenario"))
        print("Total 4-Way Queued:", int4.get("total_intersection_queue"))
        print("Total 4-Way Active:", int4.get("total_intersection_active"))
        for k, v in int4.get("approaches", {}).items():
            print(f"  [{k.upper():5s}] Queued: {v.get('queued_count')} | Active: {v.get('approaching_count')} | Speed: {v.get('avg_speed_kmh')} km/h | Signal: {v.get('signal_color')}")
if "metrics" in data:
    print("\nMetrics total_active:", data["metrics"].get("total_active"))
    print("Metrics total_queued:", data["metrics"].get("total_queued"))
    print("Metrics average_speed_kmh:", data["metrics"].get("average_speed_kmh"))
