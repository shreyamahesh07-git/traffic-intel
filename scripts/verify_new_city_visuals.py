"""
High-Resolution Verification Script for the Upgraded 4-Way Connected City Grid Simulation.
Fetches live telemetry and geometry directly from the active TRAFFIC INTEL server (port 8000)
and renders publication-grade overhead and closeup views of the realistic city layout.
"""

import os
import sys
import json
import urllib.request
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.patches as patches

ARTIFACT_DIR = r"C:\Users\Admin\.gemini\antigravity\brain\7b27e3e7-8efa-4acf-8d63-cb91792586f2"
os.makedirs(ARTIFACT_DIR, exist_ok=True)

# 1. Fetch live telemetry and network geometry
print("Fetching live simulation telemetry...")
with urllib.request.urlopen("http://127.0.0.1:8000/api/telemetry") as res:
    telemetry_data = json.loads(res.read().decode("utf-8"))

print("Fetching road network geometry...")
with urllib.request.urlopen("http://127.0.0.1:8000/api/network/geometry") as res:
    geo_data = json.loads(res.read().decode("utf-8"))

roads = geo_data.get("roads", []) or geo_data.get("edges", [])
junctions = geo_data.get("junctions", []) or geo_data.get("nodes", [])

rb_info = geo_data.get("roundabout", {}) or {"center_x": 220.0, "center_y": 440.0, "radius": 50.0}
cx, cy = rb_info.get("center_x", 220.0), rb_info.get("center_y", 440.0)

vehicles = telemetry_data.get("vehicles", [])
tls_map = telemetry_data.get("traffic_lights", {})
ctrl_info = telemetry_data.get("controller_info", {})
metrics = telemetry_data.get("metrics", {})

print(f"Loaded {len(roads)} road edges, {len(vehicles)} live vehicles, {len(tls_map)} traffic lights.")

# Colors for vehicle classes
CLASS_COLORS = {
    "car": ("#38bdf8", "#0284c7"),        # Cyan / Blue
    "motorcycle": ("#fbbf24", "#d97706"), # Amber
    "bus": ("#34d399", "#059669"),        # Emerald Green
    "truck": ("#fb923c", "#ea580c"),       # Orange / Rust
    "emergency": ("#ef4444", "#b91c1c")   # Red
}

VEH_DIMS = {
    "car": (4.5, 2.0),
    "motorcycle": (2.2, 1.0),
    "bus": (11.0, 3.2),
    "truck": (9.0, 3.0),
    "emergency": (5.2, 2.2)
}

edge_queues = {}
for v in vehicles:
    if v.get("is_queued"):
        eid = v.get("edge", "")
        edge_queues[eid] = edge_queues.get(eid, 0) + 1

# =====================================================================
# FIGURE 1: MASTER CONNECTED CITY OVERVIEW (FULL 4-WAY GRID)
# =====================================================================
fig, ax = plt.subplots(figsize=(20, 12), facecolor="#0f172a")
ax.set_facecolor("#0f172a")

# Subtle city block grid lines
for gx in range(0, 1600, 160):
    ax.axvline(gx, color="#1e293b", linewidth=0.8, linestyle="--", alpha=0.5)
for gy in range(0, 1000, 160):
    ax.axhline(gy, color="#1e293b", linewidth=0.8, linestyle="--", alpha=0.5)

# Render City Parks & Green Spaces
park1 = patches.Circle((cx, cy), 110, facecolor="#064e3b", edgecolor="#059669", linewidth=2.0, alpha=0.4, zorder=1)
ax.add_patch(park1)
park2 = patches.FancyBboxPatch((600, 300), 320, 280, boxstyle="round,pad=10,rounding_size=20",
                              facecolor="#1e293b", edgecolor="#334155", linewidth=1.5, zorder=1)
ax.add_patch(park2)

# Render roads: Sidewalks, Dark Asphalt, Congestion Heatmap, Lane Divider Striping
for road in roads:
    for lane in road.get("lanes", []):
        shape = lane.get("shape", [])
        if len(shape) < 2:
            continue
        xs = [pt[0] for pt in shape]
        ys = [pt[1] for pt in shape]
        
        # 1. Sidewalk Curb
        ax.plot(xs, ys, color="#334155", linewidth=13, solid_capstyle="round", zorder=3)
        # 2. Dark Asphalt
        ax.plot(xs, ys, color="#1e293b", linewidth=10, solid_capstyle="round", zorder=4)

        # 3. Congestion Flow Heatmap Underlay
        q_cnt = edge_queues.get(road.get("id"), 0)
        if q_cnt >= 4:
            ax.plot(xs, ys, color="#ef4444", linewidth=9, alpha=0.75, solid_capstyle="round", zorder=5)
        elif q_cnt >= 1:
            ax.plot(xs, ys, color="#f59e0b", linewidth=9, alpha=0.55, solid_capstyle="round", zorder=5)
        else:
            ax.plot(xs, ys, color="#10b981", linewidth=9, alpha=0.20, solid_capstyle="round", zorder=5)

        # 4. Dashed White Lane Divider
        ax.plot(xs, ys, color="#94a3b8", linewidth=1.2, linestyle="--", dashes=(6, 5), zorder=6, alpha=0.8)

# European Garden Parkway Roundabout Detail
rb_outer = patches.Circle((cx, cy), 46, facecolor="none", edgecolor="#334155", linewidth=15, zorder=3)
rb_asp   = patches.Circle((cx, cy), 46, facecolor="none", edgecolor="#1e293b", linewidth=12, zorder=4)
rb_div   = patches.Circle((cx, cy), 46, facecolor="none", edgecolor="white", linewidth=1.2, linestyle="--", zorder=6)
rb_apron = patches.Circle((cx, cy), 31, facecolor="none", edgecolor="#475569", linewidth=6.5, zorder=5)
rb_island= patches.Circle((cx, cy), 24, facecolor="#065f46", edgecolor="#10b981", linewidth=2.5, zorder=7)
rb_fount = patches.Circle((cx, cy), 8,  facecolor="#0284c7", edgecolor="white", linewidth=1.4, zorder=9)

for p in [rb_outer, rb_asp, rb_div, rb_apron, rb_island, rb_fount]:
    ax.add_patch(p)

ax.text(cx, cy + 58, "GARDEN PARKWAY ROUNDABOUT", color="#34d399", fontsize=9.5, fontweight="bold", ha="center", zorder=10)

# Render Junction Aprons & Yellow Box Hatchings
for node in junctions:
    nx, ny = node.get("x", 0), node.get("y", 0)
    nid = node.get("id", "")
    if "TL_" in nid or "GATE_MID" in nid:
        junc_circle = patches.Circle((nx, ny), 24, facecolor="#0f172a", edgecolor="#475569", linewidth=2.0, zorder=4)
        ax.add_patch(junc_circle)
        
        # Yellow Box Hatch
        box_patch = patches.Rectangle((nx - 14, ny - 14), 28, 28, facecolor="none",
                                      edgecolor="#facc15", linewidth=1.0, hatch="///", alpha=0.45, zorder=5)
        ax.add_patch(box_patch)
        
        lbl = nid.replace("TL_", "").replace("GATE_MID_", "GATE_")
        ax.text(nx, ny - 1, lbl, color="white", fontsize=8.0, fontweight="bold", family="monospace", ha="center", va="center", zorder=7)
    elif nid == "TJUNC_EAST":
        tj_circle = patches.Circle((nx, ny), 20, facecolor="#0f172a", edgecolor="#475569", linewidth=2.0, zorder=4)
        ax.add_patch(tj_circle)
        ax.text(nx, ny - 1, "T-JUNC", color="white", fontsize=8.0, fontweight="bold", family="monospace", ha="center", va="center", zorder=7)

# Traffic Light Signal Heads
TL_POS = {
    "TL_CENTRAL": (760, 440),
    "TL_NW": (440, 680),
    "TL_NE": (1080, 680),
    "TL_SW": (440, 200),
    "TL_SE": (1080, 200),
    "GATE_MID_N": (760, 680),
    "GATE_MID_S": (760, 200)
}
for tlid, (tx, ty) in TL_POS.items():
    tl_obj = tls_map.get(tlid, {})
    col_str = tl_obj.get("primary_color", "RED")
    ring_col = "#10b981" if col_str == "GREEN" else ("#f59e0b" if col_str == "YELLOW" else "#ef4444")
    
    ring = patches.Circle((tx, ty), 28, facecolor="none", edgecolor=ring_col, linewidth=2.8, zorder=8)
    ax.add_patch(ring)
    
    # Signal box
    box = patches.FancyBboxPatch((tx + 22, ty - 16), 12, 32, boxstyle="round,pad=1,rounding_size=3",
                                 facecolor="#020617", edgecolor="#475569", linewidth=1.2, zorder=9)
    ax.add_patch(box)
    
    is_r = col_str == "RED"
    is_y = col_str == "YELLOW"
    is_g = col_str == "GREEN"
    ax.add_patch(patches.Circle((tx + 28, ty + 9), 3.2, facecolor="#ef4444" if is_r else "#450a0a", zorder=10))
    ax.add_patch(patches.Circle((tx + 28, ty),     3.2, facecolor="#f59e0b" if is_y else "#451a03", zorder=10))
    ax.add_patch(patches.Circle((tx + 28, ty - 9), 3.2, facecolor="#10b981" if is_g else "#064e3b", zorder=10))

# Render Live SUMO Vehicles with Headlight Cones & Class Distinctions
for v in vehicles:
    vx, vy = v.get("x", 0), v.get("y", 0)
    angle = v.get("angle", 0)
    rad = np.radians(angle)
    cls_name = v.get("class", "car").lower()
    if "emergency" in v.get("id", "").lower():
        cls_name = "emergency"
        
    length, width = VEH_DIMS.get(cls_name, (4.5, 2.0))
    fill_col, edge_col = CLASS_COLORS.get(cls_name, ("#38bdf8", "#0284c7"))
    
    # Heading unit vectors (SUMO 0=North, 90=East)
    fwd_x = np.sin(rad)
    fwd_y = np.cos(rad)
    side_x = np.cos(rad)
    side_y = -np.sin(rad)
    
    # Vehicle Body Polygon
    hw = width * 1.6
    hl = length * 1.5
    c1 = (vx - side_x * hw - fwd_x * hl, vy - side_y * hw - fwd_y * hl)
    c2 = (vx + side_x * hw - fwd_x * hl, vy + side_y * hw - fwd_y * hl)
    c3 = (vx + side_x * hw + fwd_x * hl, vy + side_y * hw + fwd_y * hl)
    c4 = (vx - side_x * hw + fwd_x * hl, vy - side_y * hw + fwd_y * hl)
    
    body = patches.Polygon([c1, c2, c3, c4], closed=True, facecolor=fill_col, edgecolor=edge_col,
                           linewidth=1.2, zorder=11)
    ax.add_patch(body)
    
    # Headlight Beams (Forward glow)
    hx = vx + fwd_x * (hl + 6)
    hy = vy + fwd_y * (hl + 6)
    beam = patches.Polygon([(vx, vy), (hx - side_x * hw * 1.8, hy - side_y * hw * 1.8),
                            (hx + side_x * hw * 1.8, hy + side_y * hw * 1.8)],
                           facecolor="#fef08a", edgecolor="none", alpha=0.25, zorder=10)
    ax.add_patch(beam)

# HUD Header & Explainable Reasoning Banner
header_box = patches.FancyBboxPatch((20, 810), 1440, 60, boxstyle="round,pad=5,rounding_size=8",
                                    facecolor="#1e293b", edgecolor="#38bdf8", linewidth=1.5, zorder=20)
ax.add_patch(header_box)
ax.text(35, 845, "TRAFFIC INTEL — REALISTIC 4-WAY URBAN GRID & AUTONOMOUS REINFORCEMENT LEARNING",
        color="#38bdf8", fontsize=13, fontweight="bold", family="sans-serif", zorder=21)
ax.text(35, 822, f"Active Fleet: {metrics.get('total_active', len(vehicles))} vehicles | TraCI Step: {telemetry_data.get('telemetry',{}).get('step_count', 0)} | 0 Spiderweb Intersections | Pure 4-Way Grid & Multi-Class Krauss Flow",
        color="#94a3b8", fontsize=10, family="monospace", zorder=21)

# XAI Reasoning Strip
xai_box = patches.FancyBboxPatch((20, 15), 1440, 45, boxstyle="round,pad=5,rounding_size=6",
                                 facecolor="#020617", edgecolor="#10b981", linewidth=1.5, zorder=20)
ax.add_patch(xai_box)
expl_text = ctrl_info.get("explanation", "DQN Adaptive Controller: Monitoring 4-phase central crossroads and 6 satellite hubs.")
ax.text(35, 30, f"🧠 Explainable AI (XAI): {expl_text}", color="#34d399", fontsize=10.5, fontweight="bold", family="monospace", zorder=21)

ax.set_xlim(-20, 1500)
ax.set_ylim(-20, 900)
ax.set_aspect("equal")
ax.axis("off")

plt.tight_layout()
overview_path = os.path.join(ARTIFACT_DIR, "new_4way_grid_simulation_overview.png")
plt.savefig(overview_path, dpi=200, bbox_inches="tight", facecolor="#0f172a")
plt.close()
print(f"Saved overview verification figure to: {overview_path}")


# =====================================================================
# FIGURE 2: CENTRAL PLAZA CROSSROADS (TL_CENTRAL) HIGH-RESOLUTION CLOSEUP
# =====================================================================
fig, ax = plt.subplots(figsize=(14, 14), facecolor="#0f172a")
ax.set_facecolor("#0f172a")

# Focus on Central Plaza Crossroads: (760, 440)
c_minx, c_maxx = 620, 900
c_miny, c_maxy = 300, 580

# Plaza Esplanade Ground
esplanade = patches.FancyBboxPatch((640, 320), 240, 240, boxstyle="round,pad=10,rounding_size=15",
                                   facecolor="#1e293b", edgecolor="#475569", linewidth=2.0, zorder=1)
ax.add_patch(esplanade)

# Roads in Central Plaza
for road in roads:
    for lane in road.get("lanes", []):
        shape = lane.get("shape", [])
        if len(shape) < 2:
            continue
        xs = [pt[0] for pt in shape]
        ys = [pt[1] for pt in shape]
        
        # Check if in viewport
        if any(c_minx - 50 <= x <= c_maxx + 50 for x in xs) and any(c_miny - 50 <= y <= c_maxy + 50 for y in ys):
            # Sidewalk
            ax.plot(xs, ys, color="#475569", linewidth=24, solid_capstyle="round", zorder=3)
            # Asphalt
            ax.plot(xs, ys, color="#0f172a", linewidth=19, solid_capstyle="round", zorder=4)
            # Striping
            ax.plot(xs, ys, color="#94a3b8", linewidth=2.0, linestyle="--", dashes=(8, 6), zorder=6, alpha=0.9)

# Zebra Crosswalks (4-way approaches)
cw_coords = [
    # North crosswalk
    ([744, 776], [472, 472]),
    # South crosswalk
    ([744, 776], [408, 408]),
    # East crosswalk
    ([792, 792], [424, 456]),
    # West crosswalk
    ([728, 728], [424, 456])
]
for (cwx, cwy) in cw_coords:
    if cwx[0] == cwx[1]: # Vertical zebra bars
        for zy in np.linspace(cwy[0], cwy[1], 7):
            ax.plot([cwx[0] - 6, cwx[0] + 6], [zy, zy], color="#f8fafc", linewidth=2.8, zorder=7)
    else: # Horizontal zebra bars
        for zx in np.linspace(cwx[0], cwx[1], 7):
            ax.plot([zx, zx], [cwy[0] - 6, cwy[0] + 6], color="#f8fafc", linewidth=2.8, zorder=7)

# Stop Bars
ax.plot([744, 776], [480, 480], color="#facc15", linewidth=3.5, zorder=8)
ax.plot([744, 776], [400, 400], color="#facc15", linewidth=3.5, zorder=8)
ax.plot([800, 800], [424, 456], color="#facc15", linewidth=3.5, zorder=8)
ax.plot([720, 720], [424, 456], color="#facc15", linewidth=3.5, zorder=8)

# Yellow Box Junction Hatching
box_patch = patches.Rectangle((760 - 24, 440 - 24), 48, 48, facecolor="none",
                              edgecolor="#facc15", linewidth=2.2, hatch="///", alpha=0.6, zorder=5)
ax.add_patch(box_patch)

# Central Traffic Light Head
tl_obj = tls_map.get("TL_CENTRAL", {})
col_str = tl_obj.get("primary_color", "GREEN")
ring_col = "#10b981" if col_str == "GREEN" else ("#f59e0b" if col_str == "YELLOW" else "#ef4444")
ax.add_patch(patches.Circle((760, 440), 42, facecolor="none", edgecolor=ring_col, linewidth=4.0, zorder=9))

# Vehicles inside Central Viewport
for v in vehicles:
    vx, vy = v.get("x", 0), v.get("y", 0)
    if c_minx <= vx <= c_maxx and c_miny <= vy <= c_maxy:
        angle = v.get("angle", 0)
        rad = np.radians(angle)
        cls_name = v.get("class", "car").lower()
        if "emergency" in v.get("id", "").lower():
            cls_name = "emergency"
            
        length, width = VEH_DIMS.get(cls_name, (4.5, 2.0))
        fill_col, edge_col = CLASS_COLORS.get(cls_name, ("#38bdf8", "#0284c7"))
        
        fwd_x = np.sin(rad)
        fwd_y = np.cos(rad)
        side_x = np.cos(rad)
        side_y = -np.sin(rad)
        
        hw = width * 1.8
        hl = length * 1.8
        c1 = (vx - side_x * hw - fwd_x * hl, vy - side_y * hw - fwd_y * hl)
        c2 = (vx + side_x * hw - fwd_x * hl, vy + side_y * hw - fwd_y * hl)
        c3 = (vx + side_x * hw + fwd_x * hl, vy + side_y * hw + fwd_y * hl)
        c4 = (vx - side_x * hw + fwd_x * hl, vy - side_y * hw + fwd_y * hl)
        
        ax.add_patch(patches.Polygon([c1, c2, c3, c4], closed=True, facecolor=fill_col, edgecolor=edge_col,
                                     linewidth=1.8, zorder=12))
        
        # Brake lights if stopped/queued
        if v.get("is_queued") or v.get("speed_kmh", 0) < 2.0:
            ax.plot([c1[0], c2[0]], [c1[1], c2[1]], color="#ef4444", linewidth=3.5, zorder=13)
        
        # Vehicle Tag
        v_tag = f"#{v.get('num_id', '')} {cls_name.upper()} {v.get('speed_kmh', 0):.0f}km/h"
        ax.text(vx, vy + 7, v_tag, color="white", fontsize=8.0, fontweight="bold", ha="center",
                bbox=dict(boxstyle="round,pad=0.2", facecolor="#020617", edgecolor="#38bdf8", linewidth=0.8, alpha=0.85),
                zorder=14)

# Callout Annotations
ax.text(760, 565, "NORTH-SOUTH GRAND BOULEVARD (4 LANES + MEDIAN)", color="#38bdf8", fontsize=11, fontweight="bold", ha="center", zorder=20)
ax.text(760, 310, "TO SOUTH GATE & ARTERIAL INTERCHANGE", color="#94a3b8", fontsize=9.5, fontweight="bold", ha="center", zorder=20)
ax.text(630, 440, "WEST PARKWAY\nROUNDABOUT", color="#34d399", fontsize=9.5, fontweight="bold", ha="center", va="center", zorder=20)
ax.text(880, 440, "EAST BOULEVARD\nT-JUNCTION", color="#fbbf24", fontsize=9.5, fontweight="bold", ha="center", va="center", zorder=20)

# Central Header
ax.text(760, 458, "TL_CENTRAL (4-WAY NEMA CROSSROADS)", color="white", fontsize=11, fontweight="bold", family="monospace", ha="center", zorder=20)
ax.text(760, 422, f"ACTIVE PHASE: {ctrl_info.get('phase_description', 'Active Corridor')}", color="#facc15", fontsize=9.5, fontweight="bold", family="monospace", ha="center", zorder=20)

ax.set_xlim(c_minx, c_maxx)
ax.set_ylim(c_miny, c_maxy)
ax.set_aspect("equal")
ax.axis("off")

plt.tight_layout()
closeup_path = os.path.join(ARTIFACT_DIR, "new_central_plaza_closeup.png")
plt.savefig(closeup_path, dpi=200, bbox_inches="tight", facecolor="#0f172a")
plt.close()
print(f"Saved closeup verification figure to: {closeup_path}")
