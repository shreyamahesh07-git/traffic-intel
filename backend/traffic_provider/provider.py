"""
External Traffic Data Provider Adapter for Traffic Intel.
Supports TomTom Traffic Flow API and HERE Traffic API via environment variables.
Never fabricates real-time traffic data when unconfigured.
"""

import os
import sys
import time
from typing import Dict, Any, List, Optional
import httpx

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from backend.config import (
    TRAFFIC_PROVIDER,
    TOMTOM_API_KEY,
    HERE_API_KEY,
    DEFAULT_MAP_LAT,
    DEFAULT_MAP_LON,
)


def _classify_congestion(current_speed: float, free_flow_speed: float) -> str:
    if free_flow_speed <= 0:
        return "UNKNOWN"
    ratio = current_speed / free_flow_speed
    if ratio >= 0.75:
        return "FLOWING"
    elif ratio >= 0.45:
        return "MODERATE"
    return "CONGESTED"


class TrafficDataProvider:
    """
    Adapter for external real-world traffic APIs (TomTom / HERE).
    Normalizes road speed, free-flow speed, and congestion level.
    """

    def __init__(self):
        self.provider = TRAFFIC_PROVIDER
        self.tomtom_key = TOMTOM_API_KEY
        self.here_key = HERE_API_KEY
        self.default_lat = DEFAULT_MAP_LAT
        self.default_lon = DEFAULT_MAP_LON
        self.last_error: Optional[str] = None
        self.last_fetch_ts: Optional[float] = None
        self._cache: Dict[str, Any] = {}
        self._cache_ttl = 30.0

    def is_configured(self) -> bool:
        if self.provider == "tomtom" and bool(self.tomtom_key.strip()):
            return True
        if self.provider == "here" and bool(self.here_key.strip()):
            return True
        if self.tomtom_key.strip() or self.here_key.strip():
            return True
        return False

    def active_provider_name(self) -> str:
        if self.provider == "tomtom" and self.tomtom_key.strip():
            return "tomtom"
        if self.provider == "here" and self.here_key.strip():
            return "here"
        if self.tomtom_key.strip():
            return "tomtom"
        if self.here_key.strip():
            return "here"
        return "none"

    def get_status(self) -> Dict[str, Any]:
        configured = self.is_configured()
        pname = self.active_provider_name()
        return {
            "configured": configured,
            "provider": pname,
            "default_center": [self.default_lat, self.default_lon],
            "last_error": self.last_error,
            "last_fetch_ts": self.last_fetch_ts,
            "message": (
                f"Connected to {pname.upper()} Traffic API."
                if configured
                else "Live traffic data is not connected."
            ),
            "has_flow_tiles": (pname == "tomtom" and configured),
        }

    def get_simulation_markers(self, lat: float, lon: float) -> List[Dict[str, Any]]:
        """Maps the 4 district intersections + Central Plaza onto map coordinates around (lat, lon)."""
        offsets = [
            ("TL_CENTRAL", "Central Plaza Crossroads", 0.0, 0.0),
            ("TL_NW", "Northwest Commercial (TL_NW)", 0.0022, -0.0030),
            ("TL_NE", "Northeast Corporate (TL_NE)", 0.0022, 0.0030),
            ("TL_SW", "Southwest Arterial (TL_SW)", -0.0022, -0.0030),
            ("TL_SE", "Southeast Logistics (TL_SE)", -0.0022, 0.0030),
        ]
        return [
            {
                "id": tid,
                "name": name,
                "lat": round(lat + dlat, 6),
                "lon": round(lon + dlon, 6),
                "type": "simulation_intersection",
                "source": "Simulation",
            }
            for tid, name, dlat, dlon in offsets
        ]

    def fetch_road_traffic(
        self, lat: Optional[float] = None, lon: Optional[float] = None, include_demo: bool = False
    ) -> Dict[str, Any]:
        lat = lat if lat is not None else self.default_lat
        lon = lon if lon is not None else self.default_lon
        pname = self.active_provider_name()

        if pname == "none":
            if include_demo:
                return self._demo_corridors(lat, lon)
            return {
                "configured": False,
                "provider": "none",
                "data_source": "none",
                "center": [lat, lon],
                "roads": [],
                "has_flow_tiles": False,
                "error": None,
                "message": "Live traffic data is not connected.",
            }

        cache_key = f"{pname}:{round(lat, 3)}:{round(lon, 3)}"
        now = time.time()
        if cache_key in self._cache and (now - self._cache[cache_key]["ts"]) < self._cache_ttl:
            return self._cache[cache_key]["data"]

        if pname == "tomtom":
            result = self._fetch_tomtom(lat, lon)
        else:
            result = self._fetch_here(lat, lon)

        if result.get("roads"):
            self._cache[cache_key] = {"ts": now, "data": result}
        return result

    def _fetch_tomtom(self, lat: float, lon: float) -> Dict[str, Any]:
        # Sample 4 cardinal road points around (lat, lon)
        sample_points = [
            ("North Arterial", lat + 0.0025, lon),
            ("South Arterial", lat - 0.0025, lon),
            ("East Corridor", lat, lon + 0.0030),
            ("West Corridor", lat, lon - 0.0030),
        ]
        roads = []
        self.last_error = None
        try:
            with httpx.Client(timeout=6.0) as client:
                for label, p_lat, p_lon in sample_points:
                    url = "https://api.tomtom.com/traffic/services/4/flowSegmentData/absolute/10/json"
                    resp = client.get(url, params={"point": f"{p_lat},{p_lon}", "key": self.tomtom_key})
                    if resp.status_code == 429:
                        self.last_error = "TomTom API rate limit exceeded (HTTP 429)."
                        break
                    if resp.status_code in (401, 403):
                        self.last_error = "TomTom API key rejected (HTTP 401/403)."
                        break
                    if resp.status_code != 200:
                        continue
                    data = resp.json().get("flowSegmentData", {})
                    cur_spd = float(data.get("currentSpeed", 0))
                    free_spd = float(data.get("freeFlowSpeed", 1))
                    cur_tt = data.get("currentTravelTime")
                    free_tt = data.get("freeFlowTravelTime")
                    coords = [
                        [c["latitude"], c["longitude"]]
                        for c in data.get("coordinates", {}).get("coordinate", [])
                    ]
                    if not coords:
                        coords = [[lat, lon], [p_lat, p_lon]]
                    roads.append({
                        "id": label.lower().replace(" ", "_"),
                        "name": label,
                        "current_speed_kmh": round(cur_spd, 1),
                        "free_flow_speed_kmh": round(free_spd, 1),
                        "current_travel_time_sec": int(cur_tt) if cur_tt is not None else None,
                        "free_flow_travel_time_sec": int(free_tt) if free_tt is not None else None,
                        "congestion": _classify_congestion(cur_spd, free_spd),
                        "confidence": data.get("confidence", 1.0),
                        "coordinates": coords,
                        "data_source": "External traffic provider (TomTom)",
                        "last_updated": time.strftime("%H:%M:%S"),
                    })
            self.last_fetch_ts = time.time()
        except Exception as e:
            self.last_error = f"TomTom request failed: {e}"

        return {
            "configured": True,
            "provider": "tomtom",
            "data_source": "External traffic provider (TomTom)",
            "center": [lat, lon],
            "roads": roads,
            "has_flow_tiles": True,
            "error": self.last_error,
            "message": self.last_error or f"Loaded {len(roads)} live road segments from TomTom.",
        }

    def fetch_flow_tile(self, z: int, x: int, y: int) -> Optional[bytes]:
        """Proxies TomTom live traffic flow tiles without exposing API key to frontend."""
        if self.active_provider_name() != "tomtom" or not self.tomtom_key.strip():
            return None
        try:
            url = f"https://api.tomtom.com/traffic/map/4/tile/flow/relative/{z}/{x}/{y}.png"
            with httpx.Client(timeout=4.0) as client:
                resp = client.get(url, params={"key": self.tomtom_key})
                if resp.status_code == 200:
                    return resp.content
        except Exception:
            pass
        return None

    def _fetch_here(self, lat: float, lon: float) -> Dict[str, Any]:
        self.last_error = None
        roads = []
        try:
            bbox = f"{lon - 0.01},{lat - 0.01},{lon + 0.01},{lat + 0.01}"
            url = "https://data.traffic.hereapi.com/v7/flow"
            with httpx.Client(timeout=6.0) as client:
                resp = client.get(
                    url,
                    params={
                        "in": f"bbox:{bbox}",
                        "locationReferencing": "shape",
                        "apiKey": self.here_key,
                    },
                )
                if resp.status_code == 429:
                    self.last_error = "HERE API rate limit exceeded (HTTP 429)."
                elif resp.status_code in (401, 403):
                    self.last_error = "HERE API key rejected (HTTP 401/403)."
                elif resp.status_code == 200:
                    for idx, item in enumerate(resp.json().get("results", [])[:15]):
                        loc = item.get("location", {})
                        cf = item.get("currentFlow", {})
                        cur_spd = float(cf.get("speed", 0)) * 3.6
                        free_spd = float(cf.get("freeFlow", 1)) * 3.6
                        links = loc.get("shape", {}).get("links", [])
                        coords = []
                        if links:
                            for pt in links[0].get("points", []):
                                coords.append([pt["lat"], pt["lng"]])
                        if coords:
                            roads.append({
                                "id": f"here_seg_{idx}",
                                "name": loc.get("description", f"Road Segment {idx + 1}"),
                                "current_speed_kmh": round(cur_spd, 1),
                                "free_flow_speed_kmh": round(free_spd, 1),
                                "congestion": _classify_congestion(cur_spd, free_spd),
                                "coordinates": coords,
                                "data_source": "External traffic provider",
                            })
            self.last_fetch_ts = time.time()
        except Exception as e:
            self.last_error = f"HERE request failed: {e}"

        return {
            "configured": True,
            "provider": "here",
            "data_source": "External traffic provider",
            "center": [lat, lon],
            "roads": roads,
            "error": self.last_error,
            "message": self.last_error or f"Loaded {len(roads)} live road segments from HERE.",
        }

    def _demo_corridors(self, lat: float, lon: float) -> Dict[str, Any]:
        """Explicitly labelled demo corridor dataset when user chooses Demo Scenario."""
        roads = [
            {
                "id": "demo_north",
                "name": "North Arterial Corridor (Demo Scenario)",
                "current_speed_kmh": 18.0,
                "free_flow_speed_kmh": 50.0,
                "congestion": "CONGESTED",
                "coordinates": [[lat + 0.0045, lon], [lat, lon]],
                "data_source": "Demo scenario",
            },
            {
                "id": "demo_south",
                "name": "South Arterial Corridor (Demo Scenario)",
                "current_speed_kmh": 32.0,
                "free_flow_speed_kmh": 50.0,
                "congestion": "MODERATE",
                "coordinates": [[lat - 0.0045, lon], [lat, lon]],
                "data_source": "Demo scenario",
            },
            {
                "id": "demo_east",
                "name": "East Boulevard (Demo Scenario)",
                "current_speed_kmh": 44.0,
                "free_flow_speed_kmh": 50.0,
                "congestion": "FLOWING",
                "coordinates": [[lat, lon + 0.0055], [lat, lon]],
                "data_source": "Demo scenario",
            },
            {
                "id": "demo_west",
                "name": "West Expressway (Demo Scenario)",
                "current_speed_kmh": 42.0,
                "free_flow_speed_kmh": 50.0,
                "congestion": "FLOWING",
                "coordinates": [[lat, lon - 0.0055], [lat, lon]],
                "data_source": "Demo scenario",
            },
        ]
        return {
            "configured": False,
            "provider": "demo",
            "data_source": "Demo scenario",
            "center": [lat, lon],
            "roads": roads,
            "error": None,
            "message": "Displaying clearly labelled Demo Scenario corridors (no live traffic API key configured).",
        }
