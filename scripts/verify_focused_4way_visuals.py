import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as patches
import numpy as np

fig, ax = plt.subplots(figsize=(12, 10), dpi=150)
fig.patch.set_facecolor('#f8fafc')
ax.set_facecolor('#f8fafc')

cx, cy = 760.0, 440.0
half_w = 90.0
half_h = 75.0
road_w = 28.0 # Total width of each approach corridor

# 1. Subtle Cartographic Grid
for gx in np.arange(cx - half_w, cx + half_w + 10, 20):
    ax.axvline(gx, color='#e2e8f0', lw=0.8, zorder=1)
for gy in np.arange(cy - half_h, cy + half_h + 10, 20):
    ax.axhline(gy, color='#e2e8f0', lw=0.8, zorder=1)

# 2. Road Curbs / Sidewalks (Slate border)
curb_w = road_w + 6.0
# North-South Curb
ax.fill_between([cx - curb_w/2, cx + curb_w/2], cy - half_h, cy + half_h, color='#94a3b8', zorder=2)
# East-West Curb
ax.fill_between([cx - half_w, cx + half_w], cy - curb_w/2, cy + curb_w/2, color='#94a3b8', zorder=2)

# 3. Clean Dark Asphalt Roadbeds (NO distracting white lane stripes, NO zebra crossings)
# North-South Asphalt
ax.fill_between([cx - road_w/2, cx + road_w/2], cy - half_h, cy + half_h, color='#1e293b', zorder=3)
# East-West Asphalt
ax.fill_between([cx - half_w, cx + half_w], cy - road_w/2, cy + road_w/2, color='#1e293b', zorder=3)

# 4. Double Yellow Median Centerlines (Clean separation of opposing flows)
# North Leg Median
ax.plot([cx, cx], [cy + road_w/2 + 2, cy + half_h], color='#facc15', lw=2.0, zorder=4)
# South Leg Median
ax.plot([cx, cx], [cy - half_h, cy - road_w/2 - 2], color='#facc15', lw=2.0, zorder=4)
# East Leg Median
ax.plot([cx + road_w/2 + 2, cx + half_w], [cy, cy], color='#facc15', lw=2.0, zorder=4)
# West Leg Median
ax.plot([cx - half_w, cx - road_w/2 - 2], [cy, cy], color='#facc15', lw=2.0, zorder=4)

# 5. Clean Yellow Stop Bars at Junction Entrances (Neat 2.5px line, no clutter)
# North Stop Line (Entering Southbound)
ax.plot([cx - road_w/2, cx], [cy + road_w/2 + 2, cy + road_w/2 + 2], color='#facc15', lw=2.8, zorder=5)
# South Stop Line (Entering Northbound)
ax.plot([cx, cx + road_w/2], [cy - road_w/2 - 2, cy - road_w/2 - 2], color='#facc15', lw=2.8, zorder=5)
# East Stop Line (Entering Westbound)
ax.plot([cx + road_w/2 + 2, cx + road_w/2 + 2], [cy, cy + road_w/2], color='#facc15', lw=2.8, zorder=5)
# West Stop Line (Entering Eastbound)
ax.plot([cx - road_w/2 - 2, cx - road_w/2 - 2], [cy - road_w/2, cy], color='#facc15', lw=2.8, zorder=5)

# 6. Miniature 3-Aspect Traffic Signal Heads (Placed on Corner Sidewalks, Not Blocking Lanes)
# North Signal Mast (Green) placed safely on corner sidewalk
sig_box_n = patches.FancyBboxPatch((cx + road_w/2 + 3, cy + road_w/2 + 6), 3.5, 9, boxstyle="round,pad=0.5", fc="#0f172a", ec="#64748b", lw=1.0, zorder=7)
ax.add_patch(sig_box_n)
ax.plot(cx + road_w/2 + 4.8, cy + road_w/2 + 13.5, 'o', color='#450a0a', markersize=3.5, zorder=8)
ax.plot(cx + road_w/2 + 4.8, cy + road_w/2 + 10.5, 'o', color='#451a03', markersize=3.5, zorder=8)
ax.plot(cx + road_w/2 + 4.8, cy + road_w/2 + 7.5, 'o', color='#10b981', markersize=4.5, zorder=8) # Active Green
ax.plot(cx + road_w/2 + 4.8, cy + road_w/2 + 7.5, 'o', color='#10b981', markersize=10, alpha=0.35, zorder=7) # Subtle glow

# East Signal Mast (Red) placed safely on corner sidewalk
sig_box_e = patches.FancyBboxPatch((cx + road_w/2 + 6, cy - road_w/2 - 12), 9, 3.5, boxstyle="round,pad=0.5", fc="#0f172a", ec="#64748b", lw=1.0, zorder=7)
ax.add_patch(sig_box_e)
ax.plot(cx + road_w/2 + 7.5, cy - road_w/2 - 10.2, 'o', color='#ef4444', markersize=4.5, zorder=8) # Active Red
ax.plot(cx + road_w/2 + 7.5, cy - road_w/2 - 10.2, 'o', color='#ef4444', markersize=10, alpha=0.35, zorder=7) # Subtle glow
ax.plot(cx + road_w/2 + 10.5, cy - road_w/2 - 10.2, 'o', color='#451a03', markersize=3.5, zorder=8)
ax.plot(cx + road_w/2 + 13.5, cy - road_w/2 - 10.2, 'o', color='#022c22', markersize=3.5, zorder=8)

# 7. Render Realistic Vehicles with Maximum Visual Contrast against Pure Asphalt
def draw_vehicle(x, y, heading_deg, vclass, speed_kmh, vid):
    rad = np.radians(heading_deg)
    is_stopped = speed_kmh < 2.5
    
    if vclass == 'bus':
        length, width = 12.0, 2.8
        color = '#f59e0b' # Vivid Transit Amber
    elif vclass == 'truck':
        length, width = 9.5, 2.6
        color = '#cbd5e1' # High-contrast Silver Logistics
    elif vclass == 'motorcycle':
        length, width = 2.4, 1.0
        color = '#06b6d4' # Vibrant Cyan Bike
    else:
        length, width = 4.8, 2.1
        color = '#38bdf8' # Bright Sky Blue Sedan

    # Transform box
    corners = np.array([
        [-width/2, -length/2],
        [width/2, -length/2],
        [width/2, length/2],
        [-width/2, length/2]
    ])
    rot_mat = np.array([[np.cos(rad), -np.sin(rad)], [np.sin(rad), np.cos(rad)]])
    rot_corners = np.dot(corners, rot_mat.T) + np.array([x, y])

    veh_poly = patches.Polygon(rot_corners, closed=True, facecolor=color, edgecolor='#0f172a', linewidth=1.2, zorder=6)
    ax.add_patch(veh_poly)

    # Cabin / Windshield
    cab_len = length * 0.45
    cab_wid = width * 0.75
    cab_corners = np.array([
        [-cab_wid/2, -cab_len/2],
        [cab_wid/2, -cab_len/2],
        [cab_wid/2, cab_len/2],
        [-cab_wid/2, cab_len/2]
    ])
    rot_cab = np.dot(cab_corners, rot_mat.T) + np.array([x, y])
    cab_poly = patches.Polygon(rot_cab, closed=True, facecolor='#0f172a', edgecolor='none', zorder=7)
    ax.add_patch(cab_poly)

    # Headlights & Taillights
    front_center = np.array([x, y]) + np.dot(np.array([0, length/2]), rot_mat.T)
    rear_center = np.array([x, y]) + np.dot(np.array([0, -length/2]), rot_mat.T)
    
    # Headlight Beams (forward subtle illumination)
    cone_l = np.array([x, y]) + np.dot(np.array([-width*0.8, length/2 + 12]), rot_mat.T)
    cone_r = np.array([x, y]) + np.dot(np.array([width*0.8, length/2 + 12]), rot_mat.T)
    beam_poly = patches.Polygon([front_center, cone_l, cone_r], closed=True, facecolor='#fef08a', alpha=0.18, edgecolor='none', zorder=4)
    ax.add_patch(beam_poly)

    # Brake lights (Rear glowing red)
    brake_color = '#ef4444' if is_stopped else '#991b1b'
    ax.plot(rear_center[0], rear_center[1], 'o', color=brake_color, markersize=4.5 if not is_stopped else 7, zorder=8)
    if is_stopped:
        ax.plot(rear_center[0], rear_center[1], 'o', color=brake_color, markersize=12, alpha=0.35, zorder=7)

    # Speed tag
    ax.text(x, y - length/2 - 3.5, f"{speed_kmh:.0f} km/h", color='#ffffff', fontsize=7.5, fontweight='bold',
            bbox=dict(boxstyle='round,pad=0.2', facecolor='#ef4444' if is_stopped else '#0f172a', edgecolor='none', alpha=0.9),
            ha='center', va='top', zorder=9)

# Draw Sample Fleet on Clean Asphalt
# North Approach (Southbound entering, angle 180): Clear high-visibility vehicles
draw_vehicle(cx - road_w/4, cy + road_w/2 + 6, 180, 'car', 0.0, 'v1')
draw_vehicle(cx - road_w/4, cy + road_w/2 + 17, 180, 'truck', 0.0, 'v2')
draw_vehicle(cx - road_w/4, cy + road_w/2 + 30, 180, 'car', 0.0, 'v3')
draw_vehicle(cx - road_w/4, cy + road_w/2 + 42, 180, 'bus', 0.0, 'v4')

# South Approach (Northbound entering, angle 0): Discharging freely through green
draw_vehicle(cx + road_w/4, cy - road_w/2 + 10, 0, 'car', 42.0, 'v5')
draw_vehicle(cx + road_w/4, cy - road_w/2 - 16, 0, 'motorcycle', 46.0, 'v6')

# East Approach (Westbound entering, angle 270): Stopped at RED
draw_vehicle(cx + road_w/2 + 8, cy + road_w/4, 270, 'car', 0.0, 'v7')
draw_vehicle(cx + road_w/2 + 20, cy + road_w/4, 270, 'bus', 0.0, 'v8')

# West Approach (Eastbound entering, angle 90): Approaching RED
draw_vehicle(cx - road_w/2 - 25, cy - road_w/4, 90, 'car', 34.0, 'v9')

# 8. Approach HUD Tags
ax.text(cx, cy + half_h - 4, "⬆️ NORTH APPROACH\nQueue: 4 | Flow: 0 km/h (Stopped)", color='#ef4444', fontsize=9.5, fontweight='bold',
        bbox=dict(boxstyle='round,pad=0.4', facecolor='#ffffff', edgecolor='#ef4444', lw=1.2, alpha=0.95), ha='center', va='top', zorder=10)

ax.text(cx, cy - half_h + 4, "⬇️ SOUTH APPROACH\nQueue: 0 | Flow: 44 km/h (Discharging)", color='#10b981', fontsize=9.5, fontweight='bold',
        bbox=dict(boxstyle='round,pad=0.4', facecolor='#ffffff', edgecolor='#10b981', lw=1.2, alpha=0.95), ha='center', va='bottom', zorder=10)

ax.text(cx + half_w - 4, cy, "➡️ EAST APPROACH\nQueue: 2 | Flow: 0 km/h [RED]", color='#ef4444', fontsize=9.0, fontweight='bold',
        bbox=dict(boxstyle='round,pad=0.4', facecolor='#ffffff', edgecolor='#ef4444', lw=1.2, alpha=0.95), ha='right', va='center', zorder=10)

ax.text(cx - half_w + 4, cy, "⬅️ WEST APPROACH\nQueue: 0 | Flow: 34 km/h [RED]", color='#0284c7', fontsize=9.0, fontweight='bold',
        bbox=dict(boxstyle='round,pad=0.4', facecolor='#ffffff', edgecolor='#0284c7', lw=1.2, alpha=0.95), ha='left', va='center', zorder=10)

# Title and Status
ax.text(cx, cy + half_h + 8, "CLEAN HIGH-CONTRAST 4-WAY INTERSECTION (TL_CENTRAL)", color='#0f172a', fontsize=13, fontweight='heavy', ha='center', va='bottom')
ax.text(cx, cy + half_h + 3.5, "White lines & zebra stripes removed | Miniature corner signals | Calm pace (18s-45s green)", color='#0284c7', fontsize=9.5, fontweight='bold', ha='center', va='bottom')

ax.set_xlim(cx - half_w, cx + half_w)
ax.set_ylim(cy - half_h, cy + half_h + 12)
ax.set_aspect('equal')
ax.axis('off')

out_path = r"C:\Users\Admin\.gemini\antigravity\brain\7b27e3e7-8efa-4acf-8d63-cb91792586f2\focused_4way_clean_visuals.png"
plt.tight_layout()
plt.savefig(out_path, dpi=150, bbox_inches='tight', facecolor=fig.get_facecolor(), edgecolor='none')
plt.close()
print("Saved clean 4-way intersection verification image to:", out_path)
