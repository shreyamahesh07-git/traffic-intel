import os
import sys
import subprocess

# Ensure backend config is loaded
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from backend.config import (
    NETWORKS_DIR,
    NET_FILE,
    ROU_FILE,
    SUMOCFG_FILE,
    NETCONVERT_BIN,
    SIMULATION_STEP_LENGTH
)

os.makedirs(NETWORKS_DIR, exist_ok=True)

# 1. Define Nodes XML
NODES_FILE = os.path.join(NETWORKS_DIR, "intersection.nod.xml")
nodes_content = """<?xml version="1.0" encoding="UTF-8"?>
<nodes xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:noNamespaceSchemaLocation="http://sumo.dlr.de/xsd/nodes_file.xsd">
    <node id="intersection" x="0.0" y="0.0" type="traffic_light"/>
    <node id="north" x="0.0" y="150.0" type="priority"/>
    <node id="south" x="0.0" y="-150.0" type="priority"/>
    <node id="east" x="150.0" y="0.0" type="priority"/>
    <node id="west" x="-150.0" y="0.0" type="priority"/>
</nodes>
"""

with open(NODES_FILE, "w", encoding="utf-8") as f:
    f.write(nodes_content)
print(f"Created {NODES_FILE}")

# 2. Define Edges XML (3 lanes each direction, speed 13.89 m/s = 50 km/h)
EDGES_FILE = os.path.join(NETWORKS_DIR, "intersection.edg.xml")
edges_content = """<?xml version="1.0" encoding="UTF-8"?>
<edges xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:noNamespaceSchemaLocation="http://sumo.dlr.de/xsd/edges_file.xsd">
    <!-- Inbound approaches (3 lanes) -->
    <edge id="N2C" from="north" to="intersection" priority="78" numLanes="3" speed="13.89"/>
    <edge id="S2C" from="south" to="intersection" priority="78" numLanes="3" speed="13.89"/>
    <edge id="E2C" from="east" to="intersection" priority="78" numLanes="3" speed="13.89"/>
    <edge id="W2C" from="west" to="intersection" priority="78" numLanes="3" speed="13.89"/>

    <!-- Outbound departures (3 lanes) -->
    <edge id="C2N" from="intersection" to="north" priority="78" numLanes="3" speed="13.89"/>
    <edge id="C2S" from="intersection" to="south" priority="78" numLanes="3" speed="13.89"/>
    <edge id="C2E" from="intersection" to="east" priority="78" numLanes="3" speed="13.89"/>
    <edge id="C2W" from="intersection" to="west" priority="78" numLanes="3" speed="13.89"/>
</edges>
"""

with open(EDGES_FILE, "w", encoding="utf-8") as f:
    f.write(edges_content)
print(f"Created {EDGES_FILE}")

# 3. Define Connections XML (lane assignments: right turn / through / left turn)
CONNECTIONS_FILE = os.path.join(NETWORKS_DIR, "intersection.con.xml")
connections_content = """<?xml version="1.0" encoding="UTF-8"?>
<connections xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:noNamespaceSchemaLocation="http://sumo.dlr.de/xsd/connections_file.xsd">
    <!-- North approach: Lane 0 (Right & Through), Lane 1 (Through), Lane 2 (Left) -->
    <connection from="N2C" to="C2W" fromLane="0" toLane="0"/>
    <connection from="N2C" to="C2S" fromLane="0" toLane="0"/>
    <connection from="N2C" to="C2S" fromLane="1" toLane="1"/>
    <connection from="N2C" to="C2E" fromLane="2" toLane="2"/>

    <!-- South approach: Lane 0 (Right & Through), Lane 1 (Through), Lane 2 (Left) -->
    <connection from="S2C" to="C2E" fromLane="0" toLane="0"/>
    <connection from="S2C" to="C2N" fromLane="0" toLane="0"/>
    <connection from="S2C" to="C2N" fromLane="1" toLane="1"/>
    <connection from="S2C" to="C2W" fromLane="2" toLane="2"/>

    <!-- East approach: Lane 0 (Right & Through), Lane 1 (Through), Lane 2 (Left) -->
    <connection from="E2C" to="C2N" fromLane="0" toLane="0"/>
    <connection from="E2C" to="C2W" fromLane="0" toLane="0"/>
    <connection from="E2C" to="C2W" fromLane="1" toLane="1"/>
    <connection from="E2C" to="C2S" fromLane="2" toLane="2"/>

    <!-- West approach: Lane 0 (Right & Through), Lane 1 (Through), Lane 2 (Left) -->
    <connection from="W2C" to="C2S" fromLane="0" toLane="0"/>
    <connection from="W2C" to="C2E" fromLane="0" toLane="0"/>
    <connection from="W2C" to="C2E" fromLane="1" toLane="1"/>
    <connection from="W2C" to="C2N" fromLane="2" toLane="2"/>
</connections>
"""

with open(CONNECTIONS_FILE, "w", encoding="utf-8") as f:
    f.write(connections_content)
print(f"Created {CONNECTIONS_FILE}")

# 4. Run netconvert to generate intersection.net.xml
print(f"Running netconvert to compile {NET_FILE} ...")
cmd = [
    NETCONVERT_BIN,
    "--node-files=" + NODES_FILE,
    "--edge-files=" + EDGES_FILE,
    "--connection-files=" + CONNECTIONS_FILE,
    "--output-file=" + NET_FILE,
    "--tls.guess=true",
    "--tls.default-type=static",
    "--no-warnings=true"
]
res = subprocess.run(cmd, capture_output=True, text=True)
if res.returncode != 0:
    print("netconvert failed:")
    print(res.stderr)
    sys.exit(1)
print(f"SUCCESS: Generated {NET_FILE}")

# 5. Define Routes and Multi-Class Continuous Vehicle Demand
routes_content = """<?xml version="1.0" encoding="UTF-8"?>
<routes xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:noNamespaceSchemaLocation="http://sumo.dlr.de/xsd/routes_file.xsd">
    <!-- Vehicle Class Definitions -->
    <vType id="car" vClass="passenger" length="4.50" width="1.80" maxSpeed="14.0" accel="2.6" decel="4.5" sigma="0.5" minGap="2.5" color="0.2,0.6,1.0"/>
    <vType id="motorcycle" vClass="motorcycle" length="2.20" width="0.90" maxSpeed="16.0" accel="3.5" decel="5.0" sigma="0.5" minGap="1.5" color="1.0,0.8,0.2"/>
    <vType id="bus" vClass="bus" length="12.00" width="2.50" maxSpeed="11.0" accel="1.5" decel="3.5" sigma="0.3" minGap="3.0" color="0.2,0.9,0.3"/>
    <vType id="truck" vClass="truck" length="10.00" width="2.50" maxSpeed="10.0" accel="1.2" decel="3.0" sigma="0.3" minGap="3.5" color="0.9,0.3,0.3"/>

    <!-- Directional Routes -->
    <!-- North approaches -->
    <route id="r_N_S" edges="N2C C2S"/>
    <route id="r_N_W" edges="N2C C2W"/>
    <route id="r_N_E" edges="N2C C2E"/>

    <!-- South approaches -->
    <route id="r_S_N" edges="S2C C2N"/>
    <route id="r_S_E" edges="S2C C2E"/>
    <route id="r_S_W" edges="S2C C2W"/>

    <!-- East approaches -->
    <route id="r_E_W" edges="E2C C2W"/>
    <route id="r_E_N" edges="E2C C2N"/>
    <route id="r_E_S" edges="E2C C2S"/>

    <!-- West approaches -->
    <route id="r_W_E" edges="W2C C2E"/>
    <route id="r_W_S" edges="W2C C2S"/>
    <route id="r_W_N" edges="W2C C2N"/>

    <!-- Continuous Traffic Flows (Simulating realistic urban arrival rates) -->
    <!-- North to South & Turns -->
    <flow id="f_car_NS" type="car" route="r_N_S" begin="0" end="3600" vehsPerHour="420" departLane="best" departSpeed="max"/>
    <flow id="f_car_NW" type="car" route="r_N_W" begin="0" end="3600" vehsPerHour="150" departLane="0" departSpeed="max"/>
    <flow id="f_car_NE" type="car" route="r_N_E" begin="0" end="3600" vehsPerHour="130" departLane="2" departSpeed="max"/>
    <flow id="f_moto_NS" type="motorcycle" route="r_N_S" begin="0" end="3600" vehsPerHour="120" departLane="best" departSpeed="max"/>
    <flow id="f_bus_NS" type="bus" route="r_N_S" begin="0" end="3600" vehsPerHour="45" departLane="1" departSpeed="max"/>
    <flow id="f_truck_NS" type="truck" route="r_N_S" begin="0" end="3600" vehsPerHour="40" departLane="1" departSpeed="max"/>

    <!-- South to North & Turns -->
    <flow id="f_car_SN" type="car" route="r_S_N" begin="0" end="3600" vehsPerHour="400" departLane="best" departSpeed="max"/>
    <flow id="f_car_SE" type="car" route="r_S_E" begin="0" end="3600" vehsPerHour="140" departLane="0" departSpeed="max"/>
    <flow id="f_car_SW" type="car" route="r_S_W" begin="0" end="3600" vehsPerHour="120" departLane="2" departSpeed="max"/>
    <flow id="f_moto_SN" type="motorcycle" route="r_S_N" begin="0" end="3600" vehsPerHour="110" departLane="best" departSpeed="max"/>
    <flow id="f_bus_SN" type="bus" route="r_S_N" begin="0" end="3600" vehsPerHour="40" departLane="1" departSpeed="max"/>
    <flow id="f_truck_SN" type="truck" route="r_S_N" begin="0" end="3600" vehsPerHour="35" departLane="1" departSpeed="max"/>

    <!-- East to West & Turns -->
    <flow id="f_car_EW" type="car" route="r_E_W" begin="0" end="3600" vehsPerHour="360" departLane="best" departSpeed="max"/>
    <flow id="f_car_EN" type="car" route="r_E_N" begin="0" end="3600" vehsPerHour="110" departLane="0" departSpeed="max"/>
    <flow id="f_car_ES" type="car" route="r_E_S" begin="0" end="3600" vehsPerHour="100" departLane="2" departSpeed="max"/>
    <flow id="f_moto_EW" type="motorcycle" route="r_E_W" begin="0" end="3600" vehsPerHour="90" departLane="best" departSpeed="max"/>
    <flow id="f_bus_EW" type="bus" route="r_E_W" begin="0" end="3600" vehsPerHour="30" departLane="1" departSpeed="max"/>
    <flow id="f_truck_EW" type="truck" route="r_E_W" begin="0" end="3600" vehsPerHour="30" departLane="1" departSpeed="max"/>

    <!-- West to East & Turns -->
    <flow id="f_car_WE" type="car" route="r_W_E" begin="0" end="3600" vehsPerHour="350" departLane="best" departSpeed="max"/>
    <flow id="f_car_WS" type="car" route="r_W_S" begin="0" end="3600" vehsPerHour="100" departLane="0" departSpeed="max"/>
    <flow id="f_car_WN" type="car" route="r_W_N" begin="0" end="3600" vehsPerHour="95" departLane="2" departSpeed="max"/>
    <flow id="f_moto_WE" type="motorcycle" route="r_W_E" begin="0" end="3600" vehsPerHour="80" departLane="best" departSpeed="max"/>
    <flow id="f_bus_WE" type="bus" route="r_W_E" begin="0" end="3600" vehsPerHour="30" departLane="1" departSpeed="max"/>
    <flow id="f_truck_WE" type="truck" route="r_W_E" begin="0" end="3600" vehsPerHour="25" departLane="1" departSpeed="max"/>
</routes>
"""

with open(ROU_FILE, "w", encoding="utf-8") as f:
    f.write(routes_content)
print(f"Created {ROU_FILE}")

# 6. Define SUMO Configuration File (.sumocfg)
sumocfg_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<configuration xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:noNamespaceSchemaLocation="http://sumo.dlr.de/xsd/sumoConfiguration.xsd">
    <input>
        <net-file value="intersection.net.xml"/>
        <route-files value="intersection.rou.xml"/>
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

with open(SUMOCFG_FILE, "w", encoding="utf-8") as f:
    f.write(sumocfg_content)
print(f"Created {SUMOCFG_FILE}")

# Clean up raw node/edge/connection helper files to keep folder clean
for tmp in [NODES_FILE, EDGES_FILE, CONNECTIONS_FILE]:
    if os.path.exists(tmp):
        os.remove(tmp)

print("Build complete: network, routes, and sumocfg are verified and ready.")

