// Traffic Intel — Live Traffic Map (Leaflet + OpenStreetMap + Real Traffic Provider)

class TrafficMapView {
    constructor() {
        this.map = null;
        this.flowTileLayer = null;
        this.layers = {
            roads: null,
            selectedFlow: null,
            sim: null,
            cameras: null,
        };
        this.currentLat = 28.6139;
        this.currentLon = 77.2090;
        this.selectedRoadId = null;
    }

    init() {
        if (this.map || typeof L === 'undefined') return;
        const el = document.getElementById('traffic-map');
        if (!el) return;

        this.map = L.map('traffic-map').setView([this.currentLat, this.currentLon], 15);
        L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
            maxZoom: 19,
            attribution: '&copy; OpenStreetMap contributors',
        }).addTo(this.map);

        this.layers.roads = L.layerGroup().addTo(this.map);
        this.layers.selectedFlow = L.layerGroup().addTo(this.map);
        this.layers.sim = L.layerGroup().addTo(this.map);
        this.layers.cameras = L.layerGroup().addTo(this.map);

        this.refresh();
    }

    invalidateSize() {
        if (this.map) {
            setTimeout(() => this.map.invalidateSize(), 120);
        }
    }

    async searchLocation(query) {
        const q = (query || '').trim();
        if (!q) return;
        const coordMatch = q.match(/^(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)$/);
        if (coordMatch) {
            this.currentLat = parseFloat(coordMatch[1]);
            this.currentLon = parseFloat(coordMatch[2]);
            if (this.map) this.map.setView([this.currentLat, this.currentLon], 15);
            await this.refresh();
            return;
        }
        try {
            const resp = await fetch(`https://nominatim.openstreetmap.org/search?format=json&q=${encodeURIComponent(q)}&limit=1`);
            const items = await resp.json();
            if (items && items.length > 0) {
                this.currentLat = parseFloat(items[0].lat);
                this.currentLon = parseFloat(items[0].lon);
                if (this.map) this.map.setView([this.currentLat, this.currentLon], 15);
                await this.refresh();
            }
        } catch (e) {
            console.warn('Location search failed:', e);
        }
    }

    async refresh() {
        if (!this.map) return;
        try {
            const [statusRes, trafficRes] = await Promise.all([
                fetch(`/api/map/status?lat=${this.currentLat}&lon=${this.currentLon}`),
                fetch(`/api/map/traffic?lat=${this.currentLat}&lon=${this.currentLon}&include_demo=false`),
            ]);
            const statusData = await statusRes.json();
            const trafficData = await trafficRes.json();

            const badge = document.getElementById('map-source-badge');
            const alertBox = document.getElementById('map-provider-alert');

            if (trafficData.configured) {
                badge.textContent = trafficData.provider.toUpperCase();
                alertBox.innerHTML = trafficData.error
                    ? `<span style="color:#b91c1c;">${trafficData.error}</span>`
                    : (trafficData.message || 'Live traffic data connected.');

                if (trafficData.has_flow_tiles && !this.flowTileLayer) {
                    this.flowTileLayer = L.tileLayer('/api/map/tile/{z}/{x}/{y}', {
                        maxZoom: 19,
                        opacity: 0.78,
                    }).addTo(this.map);
                }
            } else {
                badge.textContent = 'Not connected';
                alertBox.innerHTML = `
                    <strong>Live traffic data is not connected.</strong>
                    <div style="margin-top:4px;">Configure a TomTom or HERE Traffic API key in Settings to display live road congestion overlays.</div>
                    <div style="margin-top:8px;">
                        <button class="btn btn-primary btn-sm" onclick="navigateTo('settings')">Configure Provider</button>
                    </div>
                `;
                if (this.flowTileLayer) {
                    this.map.removeLayer(this.flowTileLayer);
                    this.flowTileLayer = null;
                }
            }

            // Render Simulation Intersections
            this.layers.sim.clearLayers();
            for (const m of statusData.simulation_markers || []) {
                const marker = L.circleMarker([m.lat, m.lon], {
                    radius: 7,
                    color: '#0f766e',
                    fillColor: '#14b8a6',
                    fillOpacity: 0.9,
                    weight: 2,
                });
                marker.bindPopup(`<strong>${m.name}</strong><br/>ID: ${m.id}<br/>Source: Simulation`);
                marker.addTo(this.layers.sim);
            }

            // Render Live Camera Markers
            this.layers.cameras.clearLayers();
            for (const c of statusData.camera_markers || []) {
                const marker = L.circleMarker([c.lat, c.lon], {
                    radius: 7,
                    color: '#0284c7',
                    fillColor: '#38bdf8',
                    fillOpacity: 0.95,
                    weight: 2,
                });
                marker.bindPopup(`<strong>Live Camera</strong><br/>${c.name}<br/>Detected: ${c.active_detected}`);
                marker.addTo(this.layers.cameras);
            }

            // Render Real Road Congestion Segments (never fake overlays)
            this.layers.roads.clearLayers();
            const colorMap = {
                FLOWING: '#16a34a',
                MODERATE: '#d97706',
                CONGESTED: '#dc2626',
            };
            for (const r of trafficData.roads || []) {
                const line = L.polyline(r.coordinates, {
                    color: colorMap[r.congestion] || '#64748b',
                    weight: 6,
                    opacity: 0.9,
                });
                line.on('click', () => this._selectRoad(r));
                line.addTo(this.layers.roads);
            }
        } catch (e) {
            console.error('Map refresh failed:', e);
        }
    }

    _selectRoad(road) {
        this.selectedRoadId = road.id;
        if (this.layers.selectedFlow) {
            this.layers.selectedFlow.clearLayers();
            const flowLine = L.polyline(road.coordinates, {
                color: '#0f766e',
                weight: 4,
                opacity: 0.95,
                dashArray: '8, 6',
                className: 'road-flow-active',
            });
            flowLine.addTo(this.layers.selectedFlow);
        }

        const panel = document.getElementById('map-selected-road');
        if (!panel) return;
        const ttHtml = road.current_travel_time_sec != null
            ? `<div>Travel Time: <span class="mono">${road.current_travel_time_sec}s (free-flow ${road.free_flow_travel_time_sec ?? '—'}s)</span></div>`
            : '';
        const updHtml = road.last_updated
            ? `<div>Last Update: <span class="mono">${road.last_updated}</span></div>`
            : '';

        panel.innerHTML = `
            <div style="font-weight:600; color:#0f172a; margin-bottom:4px;">${road.name}</div>
            <div>Condition: <strong>${road.congestion}</strong></div>
            <div>Speed: <span class="mono">${road.current_speed_kmh} / ${road.free_flow_speed_kmh} km/h</span></div>
            ${ttHtml}
            ${updHtml}
            <div style="margin:4px 0 8px;">Source: <span class="source-badge">${road.data_source}</span></div>
            <button class="btn btn-primary btn-sm" style="width:100%;" onclick="window.trafficMapView.applyRoadToSumo('${road.congestion}')">
                Apply to SUMO Simulation
            </button>
        `;
    }

    async applyRoadToSumo(congestionLevel) {
        const fd = new FormData();
        fd.append('source', 'provider');
        fd.append('approach', 'north');
        fd.append('congestion_level', congestionLevel);
        const resp = await fetch('/api/simulation/apply_real_traffic', { method: 'POST', body: fd });
        const data = await resp.json();
        const panel = document.getElementById('map-selected-road');
        if (panel) {
            panel.innerHTML += `<div style="margin-top:6px; color:#0f766e;">${data.message}</div>`;
        }
    }
}

window.TrafficMapView = TrafficMapView;
