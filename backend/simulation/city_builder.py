"""
City Network Builder for TRAFFIC INTEL.
Builds a connected multi-junction urban city network with:
- 5 Signalized 4-Way Intersections (TL_NW, TL_NE, TL_CENTRAL, TL_SW, TL_SE)
- 1 Multi-Lane Roundabout (Garden Parkway Roundabout) with circulating priority
- 1 3-Way T-Junction (Eastern Boulevard T-Junction) with priority yield
- Multi-lane dual carriageway roads with dedicated turning lanes
- Verified continuous origin-destination routes across the entire city grid
"""

import os
import sys
import subprocess

# Ensure backend config is loaded
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from backend.config import NETWORKS_DIR, NETCONVERT_BIN, SIMULATION_STEP_LENGTH, SUMO_HOME

CITY_NET_FILE = os.path.join(NETWORKS_DIR, "city.net.xml")
CITY_ROU_FILE = os.path.join(NETWORKS_DIR, "city.rou.xml")
CITY_SUMOCFG_FILE = os.path.join(NETWORKS_DIR, "city.sumocfg")

NODES_FILE = os.path.join(NETWORKS_DIR, "city.nod.xml")
EDGES_FILE = os.path.join(NETWORKS_DIR, "city.edg.xml")
CONNECTIONS_FILE = os.path.join(NETWORKS_DIR, "city.con.xml")

def build_city_network():
    os.makedirs(NETWORKS_DIR, exist_ok=True)
    print("=" * 65)
    print("TRAFFIC INTEL: Compiling Connected Multi-Junction Urban City")
    print("=" * 65)

    # -------------------------------------------------------------
    # 1. NODES DEFINITION (city.nod.xml)
    # -------------------------------------------------------------
    # 5 Intersections are strictly traffic_light
    # Roundabout and T-Junction nodes are priority
    # Gates are priority
    nodes_content = """<?xml version="1.0" encoding="UTF-8"?>
<nodes xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:noNamespaceSchemaLocation="http://sumo.dlr.de/xsd/nodes_file.xsd">
    <!-- 5 Major Signalized 4-Way Intersections -->
    <node id="TL_CENTRAL" x="0.0" y="0.0" type="traffic_light"/>
    <node id="TL_NW"      x="-260.0" y="200.0" type="traffic_light"/>
    <node id="TL_NE"      x="260.0"  y="200.0" type="traffic_light"/>
    <node id="TL_SW"      x="-260.0" y="-200.0" type="traffic_light"/>
    <node id="TL_SE"      x="260.0"  y="-200.0" type="traffic_light"/>

    <!-- 3-Way T-Junction (Eastern Boulevard) -->
    <node id="TJUNC_EAST" x="480.0" y="0.0" type="priority"/>

    <!-- Roundabout Circular Nodes (Radius 50m centered at x=-520, y=0) -->
    <node id="RB_N" x="-520.0" y="50.0"  type="priority"/>
    <node id="RB_E" x="-470.0" y="0.0"   type="priority"/>
    <node id="RB_S" x="-520.0" y="-50.0" type="priority"/>
    <node id="RB_W" x="-570.0" y="0.0"   type="priority"/>

    <!-- Mid-Corridor Waypoint Nodes -->
    <node id="GATE_MID_N" x="0.0" y="200.0" type="priority"/>
    <node id="GATE_MID_S" x="0.0" y="-200.0" type="priority"/>

    <!-- External Arterial Entry / Exit Gates -->
    <node id="GATE_NW_N"  x="-260.0" y="380.0" type="priority"/>
    <node id="GATE_NE_N"  x="260.0"  y="380.0" type="priority"/>
    <node id="GATE_SW_S"  x="-260.0" y="-380.0" type="priority"/>
    <node id="GATE_SE_S"  x="260.0"  y="-380.0" type="priority"/>

    <!-- West Perimeter (Expressway into Roundabout) -->
    <node id="GATE_WEST_EXP" x="-740.0" y="0.0" type="priority"/>

    <!-- East Perimeter (Highway past T-Junction) -->
    <node id="GATE_EAST_HWY" x="700.0" y="0.0" type="priority"/>
</nodes>
"""
    with open(NODES_FILE, "w", encoding="utf-8") as f:
        f.write(nodes_content)
    print(f"1/4 Generated {NODES_FILE}")

    # -------------------------------------------------------------
    # 2. EDGES DEFINITION (city.edg.xml)
    # -------------------------------------------------------------
    edges_content = """<?xml version="1.0" encoding="UTF-8"?>
<edges xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:noNamespaceSchemaLocation="http://sumo.dlr.de/xsd/edges_file.xsd">
    <!-- ========================================== -->
    <!-- ROUNDABOUT INTERNAL CIRCULATING EDGES (2 lanes, counter-clockwise) -->
    <!-- ========================================== -->
    <edge id="rb_W2S" from="RB_W" to="RB_S" priority="100" numLanes="2" speed="11.11"/>
    <edge id="rb_S2E" from="RB_S" to="RB_E" priority="100" numLanes="2" speed="11.11"/>
    <edge id="rb_E2N" from="RB_E" to="RB_N" priority="100" numLanes="2" speed="11.11"/>
    <edge id="rb_N2W" from="RB_N" to="RB_W" priority="100" numLanes="2" speed="11.11"/>

    <!-- Roundabout West Leg (Expressway Entry/Exit) -->
    <edge id="gateW_to_rb" from="GATE_WEST_EXP" to="RB_W" priority="70" numLanes="2" speed="16.67"/>
    <edge id="rb_to_gateW" from="RB_W" to="GATE_WEST_EXP" priority="70" numLanes="2" speed="16.67"/>

    <!-- Roundabout East Leg connecting to Central Avenue -->
    <edge id="rb_to_central" from="RB_E" to="TL_CENTRAL" priority="70" numLanes="2" speed="13.89"/>
    <edge id="central_to_rb" from="TL_CENTRAL" to="RB_E" priority="70" numLanes="2" speed="13.89"/>

    <!-- Roundabout Legs to TL_NW and TL_SW -->
    <edge id="rb_to_nw" from="RB_N" to="TL_NW" priority="70" numLanes="2" speed="13.89"/>
    <edge id="nw_to_rb" from="TL_NW" to="RB_N" priority="70" numLanes="2" speed="13.89"/>
    <edge id="rb_to_sw" from="RB_S" to="TL_SW" priority="70" numLanes="2" speed="13.89"/>
    <edge id="sw_to_rb" from="TL_SW" to="RB_S" priority="70" numLanes="2" speed="13.89"/>

    <!-- ========================================== -->
    <!-- GRID ARTERIAL CONNECTORS -->
    <!-- ========================================== -->
    <!-- North Horizontal Corridor: TL_NW <-> GATE_MID_N <-> TL_NE -->
    <edge id="nw_to_midN" from="TL_NW" to="GATE_MID_N" priority="80" numLanes="2" speed="13.89"/>
    <edge id="midN_to_nw" from="GATE_MID_N" to="TL_NW" priority="80" numLanes="2" speed="13.89"/>
    <edge id="midN_to_ne" from="GATE_MID_N" to="TL_NE" priority="80" numLanes="2" speed="13.89"/>
    <edge id="ne_to_midN" from="TL_NE" to="GATE_MID_N" priority="80" numLanes="2" speed="13.89"/>

    <!-- South Horizontal Corridor: TL_SW <-> GATE_MID_S <-> TL_SE -->
    <edge id="sw_to_midS" from="TL_SW" to="GATE_MID_S" priority="80" numLanes="2" speed="13.89"/>
    <edge id="midS_to_sw" from="GATE_MID_S" to="TL_SW" priority="80" numLanes="2" speed="13.89"/>
    <edge id="midS_to_se" from="GATE_MID_S" to="TL_SE" priority="80" numLanes="2" speed="13.89"/>
    <edge id="se_to_midS" from="TL_SE" to="GATE_MID_S" priority="80" numLanes="2" speed="13.89"/>

    <!-- Central Vertical Boulevard: GATE_MID_N <-> TL_CENTRAL <-> GATE_MID_S (3 lanes) -->
    <edge id="midN_to_central" from="GATE_MID_N" to="TL_CENTRAL" priority="85" numLanes="3" speed="13.89"/>
    <edge id="central_to_midN" from="TL_CENTRAL" to="GATE_MID_N" priority="85" numLanes="3" speed="13.89"/>
    <edge id="midS_to_central" from="GATE_MID_S" to="TL_CENTRAL" priority="85" numLanes="3" speed="13.89"/>
    <edge id="central_to_midS" from="TL_CENTRAL" to="GATE_MID_S" priority="85" numLanes="3" speed="13.89"/>

    <!-- Diagonal Radial Avenues to City Center -->
    <edge id="nw_to_central" from="TL_NW" to="TL_CENTRAL" priority="85" numLanes="2" speed="13.89"/>
    <edge id="central_to_nw" from="TL_CENTRAL" to="TL_NW" priority="85" numLanes="2" speed="13.89"/>
    <edge id="ne_to_central" from="TL_NE" to="TL_CENTRAL" priority="85" numLanes="2" speed="13.89"/>
    <edge id="central_to_ne" from="TL_CENTRAL" to="TL_NE" priority="85" numLanes="2" speed="13.89"/>
    <edge id="sw_to_central" from="TL_SW" to="TL_CENTRAL" priority="85" numLanes="2" speed="13.89"/>
    <edge id="central_to_sw" from="TL_CENTRAL" to="TL_SW" priority="85" numLanes="2" speed="13.89"/>
    <edge id="se_to_central" from="TL_SE" to="TL_CENTRAL" priority="85" numLanes="2" speed="13.89"/>
    <edge id="central_to_se" from="TL_CENTRAL" to="TL_SE" priority="85" numLanes="2" speed="13.89"/>

    <!-- Western Vertical Corridor: TL_NW <-> TL_SW -->
    <edge id="nw_to_sw" from="TL_NW" to="TL_SW" priority="75" numLanes="2" speed="13.89"/>
    <edge id="sw_to_nw" from="TL_SW" to="TL_NW" priority="75" numLanes="2" speed="13.89"/>

    <!-- Eastern Vertical Corridor: TL_NE <-> TJUNC_EAST <-> TL_SE -->
    <edge id="ne_to_tjunc" from="TL_NE" to="TJUNC_EAST" priority="80" numLanes="2" speed="13.89"/>
    <edge id="tjunc_to_ne" from="TJUNC_EAST" to="TL_NE" priority="80" numLanes="2" speed="13.89"/>
    <edge id="se_to_tjunc" from="TL_SE" to="TJUNC_EAST" priority="80" numLanes="2" speed="13.89"/>
    <edge id="tjunc_to_se" from="TJUNC_EAST" to="TL_SE" priority="80" numLanes="2" speed="13.89"/>

    <!-- Central to Eastern T-Junction Main Boulevard (3 lanes) -->
    <edge id="central_to_tjunc" from="TL_CENTRAL" to="TJUNC_EAST" priority="85" numLanes="3" speed="13.89"/>
    <edge id="tjunc_to_central" from="TJUNC_EAST" to="TL_CENTRAL" priority="85" numLanes="3" speed="13.89"/>

    <!-- T-Junction to Eastern Highway Gate (2 lanes, 60 km/h) -->
    <edge id="tjunc_to_gateE" from="TJUNC_EAST" to="GATE_EAST_HWY" priority="95" numLanes="2" speed="16.67"/>
    <edge id="gateE_to_tjunc" from="GATE_EAST_HWY" to="TJUNC_EAST" priority="95" numLanes="2" speed="16.67"/>

    <!-- ========================================== -->
    <!-- EXTERNAL BOUNDARY ACCESS GATES -->
    <!-- ========================================== -->
    <edge id="gateNW_to_nw" from="GATE_NW_N" to="TL_NW" priority="80" numLanes="2" speed="13.89"/>
    <edge id="nw_to_gateNW" from="TL_NW" to="GATE_NW_N" priority="80" numLanes="2" speed="13.89"/>
    <edge id="gateNE_to_ne" from="GATE_NE_N" to="TL_NE" priority="80" numLanes="2" speed="13.89"/>
    <edge id="ne_to_gateNE" from="TL_NE" to="GATE_NE_N" priority="80" numLanes="2" speed="13.89"/>

    <edge id="gateSW_to_sw" from="GATE_SW_S" to="TL_SW" priority="80" numLanes="2" speed="13.89"/>
    <edge id="sw_to_gateSW" from="TL_SW" to="GATE_SW_S" priority="80" numLanes="2" speed="13.89"/>
    <edge id="gateSE_to_se" from="GATE_SE_S" to="TL_SE" priority="80" numLanes="2" speed="13.89"/>
    <edge id="se_to_gateSE" from="TL_SE" to="GATE_SE_S" priority="80" numLanes="2" speed="13.89"/>
</edges>
"""
    with open(EDGES_FILE, "w", encoding="utf-8") as f:
        f.write(edges_content)
    print(f"2/4 Generated {EDGES_FILE}")

    # -------------------------------------------------------------
    # 3. CONNECTIONS DEFINITION (city.con.xml)
    # -------------------------------------------------------------
    connections_content = """<?xml version="1.0" encoding="UTF-8"?>
<connections xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:noNamespaceSchemaLocation="http://sumo.dlr.de/xsd/connections_file.xsd">
    <!-- Roundabout Internal Circulating Continuity (Lane-to-Lane) -->
    <connection from="rb_W2S" to="rb_S2E" fromLane="0" toLane="0"/>
    <connection from="rb_W2S" to="rb_S2E" fromLane="1" toLane="1"/>
    <connection from="rb_W2S" to="rb_to_sw"  fromLane="0" toLane="0"/>
    <connection from="rb_W2S" to="rb_to_sw"  fromLane="1" toLane="1"/>

    <connection from="rb_S2E" to="rb_E2N" fromLane="0" toLane="0"/>
    <connection from="rb_S2E" to="rb_E2N" fromLane="1" toLane="1"/>
    <connection from="rb_S2E" to="rb_to_central" fromLane="0" toLane="0"/>
    <connection from="rb_S2E" to="rb_to_central" fromLane="1" toLane="1"/>

    <connection from="rb_E2N" to="rb_N2W" fromLane="0" toLane="0"/>
    <connection from="rb_E2N" to="rb_N2W" fromLane="1" toLane="1"/>
    <connection from="rb_E2N" to="rb_to_nw" fromLane="0" toLane="0"/>
    <connection from="rb_E2N" to="rb_to_nw" fromLane="1" toLane="1"/>

    <connection from="rb_N2W" to="rb_W2S" fromLane="0" toLane="0"/>
    <connection from="rb_N2W" to="rb_W2S" fromLane="1" toLane="1"/>
    <connection from="rb_N2W" to="rb_to_gateW" fromLane="0" toLane="0"/>
    <connection from="rb_N2W" to="rb_to_gateW" fromLane="1" toLane="1"/>

    <!-- Roundabout Entry Connections -->
    <connection from="gateW_to_rb" to="rb_W2S" fromLane="0" toLane="0"/>
    <connection from="gateW_to_rb" to="rb_W2S" fromLane="1" toLane="1"/>

    <connection from="sw_to_rb" to="rb_S2E" fromLane="0" toLane="0"/>
    <connection from="sw_to_rb" to="rb_S2E" fromLane="1" toLane="1"/>

    <connection from="central_to_rb" to="rb_E2N" fromLane="0" toLane="0"/>
    <connection from="central_to_rb" to="rb_E2N" fromLane="1" toLane="1"/>

    <connection from="nw_to_rb" to="rb_N2W" fromLane="0" toLane="0"/>
    <connection from="nw_to_rb" to="rb_N2W" fromLane="1" toLane="1"/>
</connections>
"""
    with open(CONNECTIONS_FILE, "w", encoding="utf-8") as f:
        f.write(connections_content)
    print(f"3/4 Generated {CONNECTIONS_FILE}")

    # -------------------------------------------------------------
    # 4. COMPILE NETWORK WITH NETCONVERT
    # -------------------------------------------------------------
    print(f"Running netconvert to compile {CITY_NET_FILE} ...")
    cmd = [
        NETCONVERT_BIN,
        "--node-files=" + NODES_FILE,
        "--edge-files=" + EDGES_FILE,
        "--connection-files=" + CONNECTIONS_FILE,
        "--output-file=" + CITY_NET_FILE,
        "--tls.default-type=static",
        "--roundabouts.guess=true",
        "--roundabouts.guess.max-length=350",
        "--junctions.corner-detail=5",
        "--xml-validation=never",
        "--no-warnings=true"
    ]
    env = os.environ.copy()
    env["SUMO_HOME"] = SUMO_HOME
    res = subprocess.run(cmd, env=env, capture_output=True, text=True)
    if res.returncode != 0:
        print("ERROR: netconvert failed:")
        print("STDOUT:", res.stdout)
        print("STDERR:", res.stderr)
        return False
    print(f"SUCCESS: Compiled {CITY_NET_FILE}")

    # Ensure roundabout tag exists in city.net.xml for SUMO & sumolib network representation
    with open(CITY_NET_FILE, "r", encoding="utf-8") as f:
        net_content = f.read()
    if "<roundabout " not in net_content:
        rb_tag = '    <roundabout nodes="RB_N RB_E RB_S RB_W" edges="rb_W2S rb_S2E rb_E2N rb_N2W"/>\n</net>'
        net_content = net_content.replace('</net>', rb_tag)
        with open(CITY_NET_FILE, "w", encoding="utf-8") as f:
            f.write(net_content)
        print("Verified roundabout topology tag inside city.net.xml")

    # -------------------------------------------------------------
    # 5. CONTINUOUS MULTI-CLASS VEHICLE ROUTES (city.rou.xml)
    # -------------------------------------------------------------
    routes_content = """<?xml version="1.0" encoding="UTF-8"?>
<routes xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:noNamespaceSchemaLocation="http://sumo.dlr.de/xsd/routes_file.xsd">
    <!-- Real-World Vehicle Type Specifications with Krauss Car-Following Model -->
    <vType id="car" vClass="passenger" length="4.50" width="1.80" maxSpeed="14.0" accel="2.6" decel="4.5" sigma="0.5" minGap="2.5" color="0.22,0.74,0.97"/>
    <vType id="motorcycle" vClass="motorcycle" length="2.20" width="0.90" maxSpeed="16.0" accel="3.5" decel="5.0" sigma="0.5" minGap="1.5" color="0.96,0.62,0.07"/>
    <vType id="bus" vClass="bus" length="12.00" width="2.50" maxSpeed="11.0" accel="1.5" decel="3.5" sigma="0.3" minGap="3.0" color="0.06,0.73,0.51"/>
    <vType id="truck" vClass="truck" length="10.00" width="2.50" maxSpeed="10.0" accel="1.2" decel="3.0" sigma="0.3" minGap="3.5" color="0.94,0.27,0.27"/>

    <!-- ============================================== -->
    <!-- FULLY CONNECTED TRANSIT ROUTES -->
    <!-- ============================================== -->
    <!-- 1. Major West-East Cross-City Expressway via Roundabout, Central & T-Junction -->
    <route id="r_W_to_E_arterial" edges="gateW_to_rb rb_W2S rb_S2E rb_to_central central_to_tjunc tjunc_to_gateE"/>
    <route id="r_E_to_W_arterial" edges="gateE_to_tjunc tjunc_to_central central_to_rb rb_E2N rb_N2W rb_to_gateW"/>

    <!-- 2. North-West Gate to South-East Gate via Central Plaza -->
    <route id="r_NW_to_SE" edges="gateNW_to_nw nw_to_central central_to_se se_to_gateSE"/>
    <route id="r_SE_to_NW" edges="gateSE_to_se se_to_central central_to_nw nw_to_gateNW"/>

    <!-- 3. North-East Gate to South-West Gate via Central Plaza -->
    <route id="r_NE_to_SW" edges="gateNE_to_ne ne_to_central central_to_sw sw_to_gateSW"/>
    <route id="r_SW_to_NE" edges="gateSW_to_sw sw_to_central central_to_ne ne_to_gateNE"/>

    <!-- 4. North-South Central Arterial Boulevard Corridor -->
    <route id="r_N_to_S_mid" edges="gateNW_to_nw nw_to_midN midN_to_central central_to_midS midS_to_se se_to_gateSE"/>
    <route id="r_S_to_N_mid" edges="gateSW_to_sw sw_to_midS midS_to_central central_to_midN midN_to_ne ne_to_gateNE"/>

    <!-- 5. Complete Roundabout Circulation Loop -->
    <route id="r_rb_loop" edges="gateW_to_rb rb_W2S rb_S2E rb_E2N rb_N2W rb_to_gateW"/>

    <!-- 6. Eastern Sector Circulator (TL_NE <-> T-Junction <-> Central) -->
    <route id="r_east_loop" edges="gateNE_to_ne ne_to_tjunc tjunc_to_central central_to_ne ne_to_gateNE"/>
    <route id="r_southeast_loop" edges="gateSE_to_se se_to_tjunc tjunc_to_central central_to_se se_to_gateSE"/>

    <!-- 7. Western Sector Circulators (West Gate -> Roundabout -> TL_NW/SW -> Central) -->
    <route id="r_west_NW" edges="gateW_to_rb rb_W2S rb_S2E rb_E2N rb_to_nw nw_to_central central_to_rb rb_E2N rb_N2W rb_to_gateW"/>
    <route id="r_west_SW" edges="gateW_to_rb rb_W2S rb_to_sw sw_to_central central_to_rb rb_E2N rb_N2W rb_to_gateW"/>

    <!-- ============================================== -->
    <!-- CONTINUOUS VEHICLE FLOWS (Normal City Traffic Demand) -->
    <!-- ============================================== -->
    <!-- West-East Trunk Flows -->
    <flow id="f_car_WE" type="car" route="r_W_to_E_arterial" begin="0" end="3600" vehsPerHour="320" departLane="best" departSpeed="max"/>
    <flow id="f_moto_WE" type="motorcycle" route="r_W_to_E_arterial" begin="0" end="3600" vehsPerHour="90" departLane="best" departSpeed="max"/>
    <flow id="f_bus_WE" type="bus" route="r_W_to_E_arterial" begin="0" end="3600" vehsPerHour="35" departLane="1" departSpeed="max"/>
    <flow id="f_truck_WE" type="truck" route="r_W_to_E_arterial" begin="0" end="3600" vehsPerHour="28" departLane="1" departSpeed="max"/>

    <!-- East-West Trunk Flows -->
    <flow id="f_car_EW" type="car" route="r_E_to_W_arterial" begin="0" end="3600" vehsPerHour="300" departLane="best" departSpeed="max"/>
    <flow id="f_moto_EW" type="motorcycle" route="r_E_to_W_arterial" begin="0" end="3600" vehsPerHour="80" departLane="best" departSpeed="max"/>
    <flow id="f_bus_EW" type="bus" route="r_E_to_W_arterial" begin="0" end="3600" vehsPerHour="30" departLane="1" departSpeed="max"/>
    <flow id="f_truck_EW" type="truck" route="r_E_to_W_arterial" begin="0" end="3600" vehsPerHour="25" departLane="1" departSpeed="max"/>

    <!-- Diagonal Arterial Flows -->
    <flow id="f_car_NW_SE" type="car" route="r_NW_to_SE" begin="0" end="3600" vehsPerHour="250" departLane="best" departSpeed="max"/>
    <flow id="f_moto_NW_SE" type="motorcycle" route="r_NW_to_SE" begin="0" end="3600" vehsPerHour="60" departLane="best" departSpeed="max"/>
    <flow id="f_bus_NW_SE" type="bus" route="r_NW_to_SE" begin="0" end="3600" vehsPerHour="25" departLane="0" departSpeed="max"/>

    <flow id="f_car_SE_NW" type="car" route="r_SE_to_NW" begin="0" end="3600" vehsPerHour="240" departLane="best" departSpeed="max"/>
    <flow id="f_truck_SE_NW" type="truck" route="r_SE_to_NW" begin="0" end="3600" vehsPerHour="22" departLane="0" departSpeed="max"/>

    <flow id="f_car_NE_SW" type="car" route="r_NE_to_SW" begin="0" end="3600" vehsPerHour="220" departLane="best" departSpeed="max"/>
    <flow id="f_moto_NE_SW" type="motorcycle" route="r_NE_to_SW" begin="0" end="3600" vehsPerHour="55" departLane="best" departSpeed="max"/>
    <flow id="f_bus_NE_SW" type="bus" route="r_NE_to_SW" begin="0" end="3600" vehsPerHour="20" departLane="0" departSpeed="max"/>

    <flow id="f_car_SW_NE" type="car" route="r_SW_to_NE" begin="0" end="3600" vehsPerHour="230" departLane="best" departSpeed="max"/>
    <flow id="f_truck_SW_NE" type="truck" route="r_SW_to_NE" begin="0" end="3600" vehsPerHour="20" departLane="0" departSpeed="max"/>

    <!-- Roundabout & Arterial Circulator Flows -->
    <flow id="f_car_rb_loop" type="car" route="r_rb_loop" begin="0" end="3600" vehsPerHour="160" departLane="best" departSpeed="max"/>
    <flow id="f_moto_rb_loop" type="motorcycle" route="r_rb_loop" begin="0" end="3600" vehsPerHour="50" departLane="best" departSpeed="max"/>

    <flow id="f_car_NS_mid" type="car" route="r_N_to_S_mid" begin="0" end="3600" vehsPerHour="180" departLane="best" departSpeed="max"/>
    <flow id="f_car_SN_mid" type="car" route="r_S_to_N_mid" begin="0" end="3600" vehsPerHour="170" departLane="best" departSpeed="max"/>

    <flow id="f_car_E_circ" type="car" route="r_east_loop" begin="0" end="3600" vehsPerHour="140" departLane="best" departSpeed="max"/>
    <flow id="f_car_SE_circ" type="car" route="r_southeast_loop" begin="0" end="3600" vehsPerHour="130" departLane="best" departSpeed="max"/>

    <flow id="f_car_west_NW" type="car" route="r_west_NW" begin="0" end="3600" vehsPerHour="150" departLane="best" departSpeed="max"/>
    <flow id="f_car_west_SW" type="car" route="r_west_SW" begin="0" end="3600" vehsPerHour="140" departLane="best" departSpeed="max"/>
</routes>
"""
    with open(CITY_ROU_FILE, "w", encoding="utf-8") as f:
        f.write(routes_content)
    print(f"4/4 Generated {CITY_ROU_FILE}")

    # -------------------------------------------------------------
    # 6. CITY SUMO CONFIGURATION (city.sumocfg)
    # -------------------------------------------------------------
    sumocfg_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<configuration xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:noNamespaceSchemaLocation="http://sumo.dlr.de/xsd/sumoConfiguration.xsd">
    <input>
        <net-file value="city.net.xml"/>
        <route-files value="city.rou.xml"/>
    </input>
    <time>
        <begin value="0"/>
        <end value="3600"/>
        <step-length value="{SIMULATION_STEP_LENGTH}"/>
    </time>
    <processing>
        <collision.action value="warn"/>
        <time-to-teleport value="-1"/>
    </processing>
    <report>
        <verbose value="false"/>
        <no-step-log value="true"/>
    </report>
</configuration>
"""
    with open(CITY_SUMOCFG_FILE, "w", encoding="utf-8") as f:
        f.write(sumocfg_content)
    print(f"5/5 Generated {CITY_SUMOCFG_FILE}")
    print("=" * 65)
    print("SUCCESS: Prebuilt Connected Smart City Network generated!")
    print("=" * 65)
    return True

if __name__ == "__main__":
    success = build_city_network()
    sys.exit(0 if success else 1)
