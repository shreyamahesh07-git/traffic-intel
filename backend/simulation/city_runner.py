"""
City Simulation Runner for TRAFFIC INTEL.
Controls Eclipse SUMO execution over city.sumocfg via TraCI.
Extracts multi-junction traffic light states, vehicle dynamics,
queue telemetry, and provides network geometry for frontend canvas rendering.
"""

import os
import sys
import math
import time
import threading
from typing import Dict, List, Any, Optional

import sumolib
import traci

# Ensure project root in sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from backend.config import (
    CITY_NET_FILE,
    CITY_SUMOCFG_FILE,
    SUMO_BIN,
    SUMO_GUI_BIN,
    SIMULATION_STEP_LENGTH
)

# Predefined Camera Zones across the Connected Smart City
CAMERA_ZONES = {
    "CITY_OVERVIEW": {
        "id": "CITY_OVERVIEW",
        "name": "City Overview (Full Grid)",
        "center": [740.0, 440.0],
        "zoom": 0.65,
        "description": "Full connected urban network with 7 signalized junctions, roundabout, and expressways."
    },
    "CITY_SQUARE": {
        "id": "CITY_SQUARE",
        "name": "City Square (Central Plaza)",
        "center": [760.0, 440.0],
        "zoom": 2.8,
        "description": "Realistic 4-way central crossroads TL_CENTRAL with dedicated turning bays."
    },
    "GARDEN_PARKWAY": {
        "id": "GARDEN_PARKWAY",
        "name": "Garden Parkway (Roundabout)",
        "center": [220.0, 440.0],
        "zoom": 2.8,
        "description": "Continuous priority circular roundabout circulating between expressway and inner grid."
    },
    "HIGHWAY_CORRIDOR": {
        "id": "HIGHWAY_CORRIDOR",
        "name": "West Expressway Corridor",
        "center": [100.0, 440.0],
        "zoom": 2.4,
        "description": "60 km/h perimeter expressway gateway entering the western city sector."
    },
    "EASTERN_BLVD": {
        "id": "EASTERN_BLVD",
        "name": "Eastern Boulevard (T-Junction)",
        "center": [1240.0, 440.0],
        "zoom": 2.8,
        "description": "3-way priority T-junction TJUNC_EAST linking central boulevard and eastern highway."
    },
    "NORTHWEST_DISTRICT": {
        "id": "NORTHWEST_DISTRICT",
        "name": "Northwest Commercial (TL_NW)",
        "center": [440.0, 680.0],
        "zoom": 2.8,
        "description": "Signalized crossroads connecting North Gate and Western Boulevard."
    },
    "NORTHEAST_DISTRICT": {
        "id": "NORTHEAST_DISTRICT",
        "name": "Northeast Corporate Crossing (TL_NE)",
        "center": [1080.0, 680.0],
        "zoom": 2.8,
        "description": "Corporate district 4-way intersection connecting North Gate and East Highway."
    },
    "SOUTHWEST_DISTRICT": {
        "id": "SOUTHWEST_DISTRICT",
        "name": "Southwest Arterial Hub (TL_SW)",
        "center": [440.0, 200.0],
        "zoom": 2.8,
        "description": "Industrial arterial junction linking South Gate and Western Parkway."
    },
    "SOUTHEAST_DISTRICT": {
        "id": "SOUTHEAST_DISTRICT",
        "name": "Southeast Logistics Hub (TL_SE)",
        "center": [1080.0, 200.0],
        "zoom": 2.8,
        "description": "Signalized crossroads directing heavy freight and arterial flows to South Gate."
    }
}

class CitySimulationRunner:
    """
    Connected Multi-Junction Smart City Simulation Runner.
    Manages TraCI connection to city.sumocfg, extracts live vehicle poses,
    and monitors 5 traffic light controllers and priority intersections.
    """
    def __init__(self, use_gui: bool = False, step_length: float = SIMULATION_STEP_LENGTH):
        self.use_gui = use_gui
        self.step_length = step_length
        self.sumo_bin = SUMO_GUI_BIN if use_gui else SUMO_BIN
        self.is_running = False
        self.step_count = 0
        self.current_time = 0.0
        self.lock = threading.RLock()

        # Traffic light IDs (7 Signalized Junctions across the Connected City)
        self.tl_ids = ["TL_CENTRAL", "TL_NW", "TL_NE", "TL_SW", "TL_SE", "GATE_MID_N", "GATE_MID_S"]

        # Vehicle ID mapping for clean integer identification
        self.vehicle_id_map: Dict[str, int] = {}
        self.next_vid_num = 1
        self.total_departed = 0
        self.total_arrived = 0

        # Scenario & Surge State
        self.active_scenario = "NORMAL"
        self.pending_surge: List[Dict[str, Any]] = []
        self.surge_counter = 0

        # Geometry cache
        self._cached_geometry: Optional[Dict[str, Any]] = None

    def get_network_geometry(self) -> Dict[str, Any]:
        """
        Extracts road geometry, lane paths, junction polygons, and roundabout boundaries
        from city.net.xml for frontend canvas rendering. Cached after first load.
        """
        if self._cached_geometry is not None:
            return self._cached_geometry

        print("CitySimulationRunner: Parsing city.net.xml road geometry...")
        net = sumolib.net.readNet(CITY_NET_FILE)
        
        # Bounding box
        bbox = net.getBBoxXY()
        min_x, min_y = bbox[0]
        max_x, max_y = bbox[1]

        roads = []
        for edge in net.getEdges():
            # Skip internal junction connectors for clean road rendering
            if edge.isSpecial():
                continue
            
            lanes_data = []
            for lane in edge.getLanes():
                lanes_data.append({
                    "id": lane.getID(),
                    "speed": lane.getSpeed(),
                    "width": lane.getWidth(),
                    "shape": [[round(pt[0], 2), round(pt[1], 2)] for pt in lane.getShape()]
                })
            
            from_node = edge.getFromNode().getID()
            to_node = edge.getToNode().getID()
            roads.append({
                "id": edge.getID(),
                "from": from_node,
                "to": to_node,
                "lanes": lanes_data,
                "priority": edge.getPriority()
            })

        junctions = []
        for node in net.getNodes():
            shape = node.getShape()
            junctions.append({
                "id": node.getID(),
                "x": round(node.getCoord()[0], 2),
                "y": round(node.getCoord()[1], 2),
                "type": node.getType(),
                "shape": [[round(pt[0], 2), round(pt[1], 2)] for pt in shape] if shape else []
            })

        # Roundabout info
        roundabouts = []
        for rb in net.getRoundabouts():
            rb_nodes = rb.getNodes()
            coords = [net.getNode(n).getCoord() for n in rb_nodes if net.hasNode(n)]
            if coords:
                cx = sum(c[0] for c in coords) / len(coords)
                cy = sum(c[1] for c in coords) / len(coords)
                roundabouts.append({
                    "center": [round(cx, 2), round(cy, 2)],
                    "center_x": round(cx, 2),
                    "center_y": round(cy, 2),
                    "radius": 50.0,
                    "nodes": list(rb_nodes),
                    "edges": list(rb.getEdges())
                })

        self._cached_geometry = {
            "bounds": {
                "min_x": round(min_x, 2),
                "min_y": round(min_y, 2),
                "max_x": round(max_x, 2),
                "max_y": round(max_y, 2),
                "width": round(max_x - min_x, 2),
                "height": round(max_y - min_y, 2)
            },
            "roads": roads,
            "edges": roads,
            "junctions": junctions,
            "nodes": junctions,
            "roundabouts": roundabouts,
            "roundabout": roundabouts[0] if roundabouts else {
                "center": [220.0, 440.0],
                "center_x": 220.0,
                "center_y": 440.0,
                "radius": 50.0,
                "nodes": ["RB_W", "RB_E", "RB_N", "RB_S"]
            },
            "camera_zones": CAMERA_ZONES
        }
        return self._cached_geometry

    def start(self):
        """Starts TraCI simulation session with city.sumocfg."""
        with self.lock:
            if self.is_running:
                return

            cmd = [
                self.sumo_bin,
                "-c", CITY_SUMOCFG_FILE,
                "--step-length", str(self.step_length),
                "--no-warnings", "true",
                "--collision.action", "warn"
            ]
            if self.use_gui:
                cmd.extend(["--start", "true", "--quit-on-end", "true"])

            print(f"CitySimulationRunner: Launching TraCI with {CITY_SUMOCFG_FILE}...")
            traci.start(cmd)
            self.is_running = True
            self.step_count = 0
            self.current_time = 0.0

    def step(self) -> Dict[str, Any]:
        """Advances simulation by one step and extracts complete city telemetry."""
        with self.lock:
            if not self.is_running:
                self.start()

            traci.simulationStep()
            self.step_count += 1
            self.current_time = round(self.step_count * self.step_length, 2)

            # Smoothly inject pending surge vehicles (1 vehicle every 3 steps = 1.5s)
            if self.pending_surge and (self.step_count % 3 == 0):
                item = self.pending_surge.pop(0)
                try:
                    traci.vehicle.add(
                        veh_id=item["vid"],
                        routeID=item["route"],
                        typeID=item["type"],
                        departLane="best",
                        departSpeed="max"
                    )
                    self.vehicle_id_map[item["vid"]] = self.next_vid_num
                    self.next_vid_num += 1
                except Exception as e:
                    pass

            self.total_departed += traci.simulation.getDepartedNumber()
            self.total_arrived += traci.simulation.getArrivedNumber()

            return self.get_telemetry_snapshot()

    def get_telemetry_snapshot(self) -> Dict[str, Any]:
        """Extracts complete multi-junction state, vehicles, and analytics."""
        veh_ids = traci.vehicle.getIDList()

        vehicles = []
        class_counts = {"car": 0, "motorcycle": 0, "bus": 0, "truck": 0}
        total_waiting = 0.0
        total_speed = 0.0
        total_queued = 0

        # Roundabout specific edge tracking
        rb_edges = {"rb_W2S", "rb_S2E", "rb_E2N", "rb_N2W"}
        rb_vehicles = []
        rb_speed_sum = 0.0
        rb_entry_queues = 0

        for vid in veh_ids:
            try:
                x, y = traci.vehicle.getPosition(vid)
                spd = traci.vehicle.getSpeed(vid)
                angle = traci.vehicle.getAngle(vid)
                vtype = traci.vehicle.getTypeID(vid).lower()
                edge_id = traci.vehicle.getRoadID(vid)
                lane_id = traci.vehicle.getLaneID(vid)
                wait_time = traci.vehicle.getWaitingTime(vid)

                # Class categorization
                cls_name = "car"
                cls_code = "CAR"
                if "bus" in vtype:
                    cls_name = "bus"
                    cls_code = "BUS"
                elif "truck" in vtype:
                    cls_name = "truck"
                    cls_code = "TRU"
                elif "motor" in vtype:
                    cls_name = "motorcycle"
                    cls_code = "MOT"

                class_counts[cls_name] += 1
                total_speed += spd
                total_waiting += wait_time

                is_queued = spd < 0.3
                if is_queued:
                    total_queued += 1

                # Stable integer ID
                if vid not in self.vehicle_id_map:
                    self.vehicle_id_map[vid] = self.next_vid_num
                    self.next_vid_num += 1
                clean_id = self.vehicle_id_map[vid]

                conf = round(0.91 + ((clean_id * 7 + 13) % 8) * 0.01, 2)
                tag_label = f"#{clean_id} {cls_code} {conf:.2f}"

                v_obj = {
                    "id": vid,
                    "num_id": clean_id,
                    "class": cls_name,
                    "class_code": cls_code,
                    "confidence": conf,
                    "tag": tag_label,
                    "x": round(x, 2),
                    "y": round(y, 2),
                    "speed_ms": round(spd, 2),
                    "speed_kmh": round(spd * 3.6, 1),
                    "angle": round(angle, 1),
                    "edge": edge_id,
                    "lane": lane_id,
                    "waiting_time": round(wait_time, 1),
                    "is_queued": is_queued
                }
                vehicles.append(v_obj)

                # Roundabout metrics
                if edge_id in rb_edges:
                    rb_vehicles.append(v_obj)
                    rb_speed_sum += spd
                elif edge_id in {"gateW_to_rb", "central_to_rb", "sw_to_rb", "nw_to_rb"} and is_queued:
                    rb_entry_queues += 1

            except traci.TraCIException:
                continue

        # Extract Traffic Light States
        tl_states = {}
        for tlid in self.tl_ids:
            try:
                state_str = traci.trafficlight.getRedYellowGreenState(tlid)
                phase_idx = traci.trafficlight.getPhase(tlid)
                logics = traci.trafficlight.getAllProgramLogics(tlid)
                num_phases = len(logics[0].phases) if logics else 1

                # Approach queues
                # Count queued vehicles whose edge leads into this junction
                queued_at_tl = sum(1 for v in vehicles if v["is_queued"] and tlid.lower().replace("tl_", "") in v["edge"].lower())

                # Determine dominant active color for badge
                green_count = state_str.count('G') + state_str.count('g')
                yellow_count = state_str.count('y') + state_str.count('Y')
                red_count = state_str.count('r') + state_str.count('R')
                primary = "GREEN" if green_count > red_count else ("YELLOW" if yellow_count > 0 else "RED")

                tl_states[tlid] = {
                    "id": tlid,
                    "phase_index": phase_idx,
                    "total_phases": num_phases,
                    "state_string": state_str,
                    "green_signals": green_count,
                    "red_signals": red_count,
                    "primary_color": primary,
                    "queued_vehicles": queued_at_tl
                }
            except traci.TraCIException:
                tl_states[tlid] = {"id": tlid, "phase_index": 0, "state_string": "", "primary_color": "RED", "queued_vehicles": 0}

        num_active = len(vehicles)
        avg_speed = round((total_speed / num_active) * 3.6, 1) if num_active > 0 else 0.0
        queue_ratio = round((total_queued / num_active) * 100, 1) if num_active > 0 else 0.0

        # Congestion Index formula based on queue ratio and waiting time
        congestion_pct = min(100.0, round(queue_ratio * 1.5 + min(30.0, total_waiting * 0.1), 1))
        congestion_status = "SMOOTH" if congestion_pct < 25 else ("MODERATE" if congestion_pct < 60 else "CONGESTED")

        # -------------------------------------------------------------
        # 4-WAY FOCUSED INTERSECTION TELEMETRY (TL_CENTRAL Focus)
        # -------------------------------------------------------------
        central_phase = tl_states.get("TL_CENTRAL", {}).get("phase_index", 0)
        
        # Approaches leading directly into TL_CENTRAL
        north_vehs = [v for v in vehicles if v["edge"] == "midN_to_central"]
        south_vehs = [v for v in vehicles if v["edge"] == "midS_to_central"]
        east_vehs  = [v for v in vehicles if v["edge"] == "tjunc_to_central"]
        west_vehs  = [v for v in vehicles if v["edge"] == "rb_to_central"]

        def _calc_approach(v_list, is_ns: bool):
            q_cnt = sum(1 for v in v_list if v["is_queued"])
            avg_s = round(sum(v["speed_kmh"] for v in v_list) / len(v_list), 1) if v_list else 0.0
            avg_w = round(sum(v["waiting_time"] for v in v_list) / len(v_list), 1) if v_list else 0.0
            if is_ns:
                sig = "GREEN" if central_phase == 0 else ("YELLOW" if central_phase == 1 else "RED")
            else:
                sig = "GREEN" if central_phase == 2 else ("YELLOW" if central_phase == 3 else "RED")
            return {
                "queued_count": q_cnt,
                "approaching_count": len(v_list),
                "avg_speed_kmh": avg_s,
                "avg_waiting_sec": avg_w,
                "signal_color": sig,
                "vehicles": v_list
            }

        intersection_4way = {
            "id": "TL_CENTRAL",
            "name": "Central 4-Way Crossroads",
            "center": [760.0, 440.0],
            "active_phase": central_phase,
            "phase_description": "North-South Grand Boulevard" if central_phase in (0, 1) else "East-West Grand Arterial",
            "signal_state": "GREEN_NS" if central_phase == 0 else ("YELLOW_NS" if central_phase == 1 else ("GREEN_EW" if central_phase == 2 else "YELLOW_EW")),
            "active_scenario": self.active_scenario,
            "pending_surge_count": len(self.pending_surge),
            "approaches": {
                "north": _calc_approach(north_vehs, is_ns=True),
                "south": _calc_approach(south_vehs, is_ns=True),
                "east":  _calc_approach(east_vehs,  is_ns=False),
                "west":  _calc_approach(west_vehs,  is_ns=False)
            },
            "total_intersection_queue": sum(1 for v in north_vehs + south_vehs + east_vehs + west_vehs if v["is_queued"]),
            "total_intersection_active": len(north_vehs + south_vehs + east_vehs + west_vehs)
        }

        return {
            "simulation_time": self.current_time,
            "step_count": self.step_count,
            "active_vehicles_count": num_active,
            "total_departed": self.total_departed,
            "total_arrived": self.total_arrived,
            "vehicles": vehicles,
            "traffic_lights": tl_states,
            "intersection_4way": intersection_4way,
            "roundabout": {
                "name": "Garden Parkway Roundabout",
                "center": [220.0, 440.0],
                "circulating_count": len(rb_vehicles),
                "avg_speed_kmh": round((rb_speed_sum / len(rb_vehicles)) * 3.6, 1) if rb_vehicles else 0.0,
                "entry_queue_count": rb_entry_queues
            },
            "t_junction": {
                "name": "Eastern Boulevard T-Junction",
                "center": [1240.0, 440.0],
                "active_count": sum(1 for v in vehicles if "tjunc" in v["edge"]),
                "queue_count": sum(1 for v in vehicles if "tjunc" in v["edge"] and v["is_queued"])
            },
            "metrics": {
                "total_active": num_active,
                "total_queued": total_queued,
                "queue_ratio_pct": queue_ratio,
                "average_speed_kmh": avg_speed,
                "total_waiting_seconds": round(total_waiting, 1),
                "congestion_level": congestion_status,
                "congestion_pct": congestion_pct,
                "class_counts": class_counts
            }
        }

    def set_tl_phase(self, tl_id: str, phase_index: int):
        """Set phase on a specific traffic light."""
        with self.lock:
            if not self.is_running:
                return
            try:
                traci.trafficlight.setPhase(tl_id, phase_index)
            except traci.TraCIException as e:
                print(f"CitySimulationRunner set_tl_phase error on {tl_id}: {e}")

    def set_traffic_scale(self, scale: float) -> bool:
        """Dynamically scale traffic insertion demand (e.g. 0.5x, 1.0x, 2.0x, 3.5x)."""
        with self.lock:
            if self.is_running:
                try:
                    traci.simulation.setScale(float(scale))
                    print(f"CitySimulationRunner: Traffic demand scaled to {scale}x")
                    return True
                except Exception as e:
                    print(f"Error setting traffic scale: {e}")
            return False

    def spawn_emergency_vehicle(self, route_id: str = "r_W_to_E_arterial") -> str:
        """Dynamically inject an emergency vehicle (Ambulance/Police) with siren priority."""
        with self.lock:
            if not self.is_running:
                return ""
            try:
                vid = f"emergency_{int(time.time()*1000)%100000}"
                traci.vehicle.add(vid, routeID=route_id, typeID="emergency", departLane="best", departSpeed="max")
                traci.vehicle.setColor(vid, (255, 30, 30, 255))
                traci.vehicle.setSpeedMode(vid, 31)
                self.vehicle_id_map[vid] = 999
                print(f"CitySimulationRunner: Dispatched Emergency Vehicle {vid} on route {route_id}")
                return vid
            except Exception as e:
                print(f"Error spawning emergency vehicle: {e}")
                return ""

    def create_traffic_surge(self, approach: str = "north", count: int = 8) -> int:
        """
        Injects a surge of real SUMO vehicles on the selected 4-way approach.
        Vehicles enter naturally, follow routes, stop at red, and form a queue.
        """
        route_map = {
            "north": "r_surge_north",
            "south": "r_surge_south",
            "east":  "r_surge_east",
            "west":  "r_surge_west"
        }
        route_id = route_map.get(approach.lower(), "r_surge_north")
        classes = ["car", "car", "car", "motorcycle", "car", "truck", "car", "bus", "car", "car"]
        
        with self.lock:
            for i in range(count):
                self.surge_counter += 1
                vid = f"surge_{approach.lower()}_{self.surge_counter}_{i}"
                vtype = classes[i % len(classes)]
                self.pending_surge.append({
                    "vid": vid,
                    "route": route_id,
                    "type": vtype,
                    "approach": approach.lower()
                })
            print(f"CitySimulationRunner: Queued surge of {count} vehicles on {approach.upper()} approach")
            return count

    def set_scenario(self, scenario_name: str) -> str:
        """
        Configures experimental traffic scenarios:
        - NORMAL: Balanced moderate traffic (~25-35 vehicles)
        - SURGE_NORTH: Concentrated heavy demand surge on North approach
        - UNEVEN: North heavy, South moderate, East/West sparse
        """
        scenario = scenario_name.upper()
        with self.lock:
            self.active_scenario = scenario
            self.pending_surge.clear()
            if scenario == "SURGE_NORTH":
                self.create_traffic_surge(approach="north", count=10)
            elif scenario == "UNEVEN":
                self.create_traffic_surge(approach="north", count=8)
                self.create_traffic_surge(approach="south", count=3)
            elif scenario == "NORMAL":
                pass
            print(f"CitySimulationRunner: Switched scenario to {scenario}")
            return scenario

    def reset_scenario(self) -> str:
        """Resets simulation scenario back to balanced Normal state."""
        with self.lock:
            self.active_scenario = "NORMAL"
            self.pending_surge.clear()
            print("CitySimulationRunner: Scenario reset to NORMAL")
            return "NORMAL"

    def restart(self):
        """Restarts the simulation."""
        self.stop()
        self.start()

    def stop(self):
        """Terminates TraCI session."""
        with self.lock:
            if self.is_running:
                try:
                    traci.close()
                except Exception:
                    pass
                self.is_running = False
                self.step_count = 0
                self.current_time = 0.0
                self.vehicle_id_map.clear()
                self.next_vid_num = 1
                self.total_departed = 0
                self.total_arrived = 0

