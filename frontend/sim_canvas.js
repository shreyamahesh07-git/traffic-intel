// Traffic Intel — Restored Original 2D Overhead SUMO Simulation Renderer
// Features smooth pan & zoom, realistic multi-class vehicles, brake lights,
// miniature 3-aspect corner signal heads, and clean high-contrast cartographic asphalt.

class SumoCanvasRenderer {
    constructor(canvasId) {
        this.canvas = document.getElementById(canvasId);
        this.ctx = this.canvas ? this.canvas.getContext('2d') : null;
        this.geometry = null;
        this.latestPayload = null;
        this.selectedZone = 'CITY_SQUARE';
        this.selectedTlId = 'TL_CENTRAL';
        this._animStarted = false;

        this.PRESETS = {
            CITY_OVERVIEW: { x: 760, y: 440, zoom: 0.72 },
            CITY_SQUARE: { x: 760, y: 440, zoom: 2.25 },
            GARDEN_PARKWAY: { x: 220, y: 440, zoom: 1.90 },
            EASTERN_BLVD: { x: 1240, y: 440, zoom: 1.90 },
            NORTHWEST_DISTRICT: { x: 440, y: 680, zoom: 1.95 },
            NORTHEAST_DISTRICT: { x: 1080, y: 680, zoom: 1.95 },
            SOUTHWEST_DISTRICT: { x: 440, y: 200, zoom: 1.95 },
            SOUTHEAST_DISTRICT: { x: 1080, y: 200, zoom: 1.95 },
        };

        this.camera = { x: 760, y: 440, zoom: 2.25, targetX: 760, targetY: 440, targetZoom: 2.25 };
        this._isDragging = false;
        this._dragStartX = 0;
        this._dragStartY = 0;
        this.vehPosMap = new Map();
        this.corridorAlphas = new Map();
        this._reducedMotion = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
        this._flowPhase = 0;

        this._bindInteractions();
    }

    _bindInteractions() {
        if (!this.canvas) return;
        this.canvas.style.cursor = 'grab';

        this.canvas.addEventListener('mousedown', (e) => {
            this._isDragging = true;
            this._dragStartX = e.clientX;
            this._dragStartY = e.clientY;
            this.canvas.style.cursor = 'grabbing';
        });

        window.addEventListener('mousemove', (e) => {
            if (!this._isDragging) return;
            const dx = (e.clientX - this._dragStartX) / this.camera.zoom;
            const dy = (e.clientY - this._dragStartY) / this.camera.zoom;
            this.camera.targetX -= dx;
            this.camera.targetY += dy;
            this._dragStartX = e.clientX;
            this._dragStartY = e.clientY;
        });

        window.addEventListener('mouseup', () => {
            if (this._isDragging) {
                this._isDragging = false;
                this.canvas.style.cursor = 'grab';
            }
        });

        this.canvas.addEventListener(
            'wheel',
            (e) => {
                e.preventDefault();
                const factor = e.deltaY < 0 ? 1.15 : 0.87;
                this.camera.targetZoom = Math.max(0.35, Math.min(4.8, this.camera.targetZoom * factor));
            },
            { passive: false }
        );
    }

    zoomIn() {
        this.camera.targetZoom = Math.min(4.8, this.camera.targetZoom * 1.25);
    }

    zoomOut() {
        this.camera.targetZoom = Math.max(0.35, this.camera.targetZoom * 0.8);
    }

    resetZoom() {
        const p = this.PRESETS[this.selectedZone] || this.PRESETS.CITY_SQUARE;
        this.camera.targetX = p.x;
        this.camera.targetY = p.y;
        this.camera.targetZoom = p.zoom;
    }

    fitNetwork() {
        this.selectedZone = 'CITY_OVERVIEW';
        const p = this.PRESETS.CITY_OVERVIEW;
        this.camera.targetX = p.x;
        this.camera.targetY = p.y;
        this.camera.targetZoom = p.zoom;
    }

    setZone(zoneId) {
        this.selectedZone = zoneId;
        const p = this.PRESETS[zoneId];
        if (p) {
            this.camera.targetX = p.x;
            this.camera.targetY = p.y;
            this.camera.targetZoom = p.zoom;
        }
        const tlMap = {
            CITY_SQUARE: 'TL_CENTRAL',
            NORTHWEST_DISTRICT: 'TL_NW',
            NORTHEAST_DISTRICT: 'TL_NE',
            SOUTHWEST_DISTRICT: 'TL_SW',
            SOUTHEAST_DISTRICT: 'TL_SE',
        };
        if (tlMap[zoneId]) {
            this.selectedTlId = tlMap[zoneId];
        }
    }

    setGeometry(geo) {
        this.geometry = geo;
        this.startLoop();
    }

    updateTelemetry(payload) {
        this.latestPayload = payload;
        if (payload && payload.vehicles) {
            const activeIds = new Set();
            for (const v of payload.vehicles) {
                const key = v.id || v.num_id;
                activeIds.add(key);
                const prev = this.vehPosMap.get(key);
                if (!prev || this._reducedMotion || Math.hypot(v.x - prev.x, v.y - prev.y) > 30) {
                    this.vehPosMap.set(key, {
                        x: v.x, y: v.y, angle: v.angle || 0,
                        tx: v.x, ty: v.y, tangle: v.angle || 0,
                    });
                } else {
                    prev.tx = v.x;
                    prev.ty = v.y;
                    prev.tangle = v.angle || 0;
                }
            }
            for (const key of this.vehPosMap.keys()) {
                if (!activeIds.has(key)) this.vehPosMap.delete(key);
            }
        } else {
            this.vehPosMap.clear();
        }
        this.startLoop();
    }

    startLoop() {
        if (this._animStarted) return;
        this._animStarted = true;
        const tick = () => {
            this.render();
            requestAnimationFrame(tick);
        };
        requestAnimationFrame(tick);
    }

    _resizeCanvas() {
        if (!this.canvas) return null;
        const rect = this.canvas.parentElement.getBoundingClientRect();
        const dpr = window.devicePixelRatio || 1;
        const w = Math.max(320, Math.floor(rect.width));
        const h = Math.max(320, Math.floor(rect.height));
        if (this.canvas.width !== w * dpr || this.canvas.height !== h * dpr) {
            this.canvas.width = w * dpr;
            this.canvas.height = h * dpr;
        }
        this.ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
        return { w, h };
    }

    render() {
        if (!this.ctx || !this.canvas) return;
        const dims = this._resizeCanvas();
        if (!dims) return;
        const { w, h } = dims;
        const ctx = this.ctx;

        // Smooth Camera Interpolation
        const camLerp = this._reducedMotion ? 1.0 : 0.16;
        this.camera.x += (this.camera.targetX - this.camera.x) * camLerp;
        this.camera.y += (this.camera.targetY - this.camera.y) * camLerp;
        this.camera.zoom += (this.camera.targetZoom - this.camera.zoom) * camLerp;

        // Smooth Vehicle Interpolation between SUMO updates
        if (this.latestPayload && this.latestPayload.is_running && !this.latestPayload.is_paused && !this._reducedMotion) {
            this._flowPhase = (this._flowPhase + 0.45) % 24;
            for (const p of this.vehPosMap.values()) {
                p.x += (p.tx - p.x) * 0.24;
                p.y += (p.ty - p.y) * 0.24;
                let da = p.tangle - p.angle;
                while (da > 180) da -= 360;
                while (da < -180) da += 360;
                p.angle += da * 0.28;
            }
        }

        // 1. Clean Cartographic Background
        ctx.fillStyle = '#f8fafc';
        ctx.fillRect(0, 0, w, h);

        if (!this.geometry) {
            ctx.fillStyle = '#64748b';
            ctx.font = '13px Inter, sans-serif';
            ctx.textAlign = 'center';
            ctx.fillText('Loading SUMO road network geometry...', w / 2, h / 2);
            return;
        }

        ctx.save();
        ctx.translate(w / 2, h / 2);
        ctx.scale(this.camera.zoom, this.camera.zoom);
        ctx.translate(-this.camera.x, this.camera.y);

        this._renderCityBackground(ctx);
        this._renderSumoRoads(ctx, this.geometry);

        if (this.latestPayload && this.latestPayload.traffic_lights) {
            this._renderTrafficLights(ctx, this.latestPayload.traffic_lights, this.latestPayload.controller_info);
        }

        if (this.latestPayload && this.latestPayload.vehicles) {
            this._renderVehicles(ctx, this.latestPayload.vehicles);
        }

        ctx.restore();

        // Stopped Notice
        if (!this.latestPayload || !this.latestPayload.is_running) {
            ctx.fillStyle = 'rgba(248, 250, 252, 0.72)';
            ctx.fillRect(0, 0, w, h);
            ctx.fillStyle = '#0f172a';
            ctx.font = '600 14px Inter, sans-serif';
            ctx.textAlign = 'center';
            ctx.fillText('Simulation stopped. Click "Start" to launch SUMO.', w / 2, h / 2);
        }
    }

    _renderCityBackground(ctx) {
        // Subtle 100m Grid
        ctx.strokeStyle = '#e2e8f0';
        ctx.lineWidth = 1.0 / this.camera.zoom;
        ctx.beginPath();
        for (let x = 0; x <= 1600; x += 100) {
            ctx.moveTo(x, -900);
            ctx.lineTo(x, 100);
        }
        for (let y = -900; y <= 100; y += 100) {
            ctx.moveTo(0, y);
            ctx.lineTo(1600, y);
        }
        ctx.stroke();

        // Garden Parkway Roundabout Green Island (SUMO: 220, 440)
        ctx.fillStyle = '#dcfce7';
        ctx.beginPath();
        ctx.arc(220, -440, 72, 0, Math.PI * 2);
        ctx.fill();
        ctx.strokeStyle = '#86efac';
        ctx.lineWidth = 2.0;
        ctx.stroke();

        // Central Plaza Corner Sidewalks
        if (this.camera.zoom > 1.4) {
            ctx.fillStyle = '#f1f5f9';
            ctx.strokeStyle = '#cbd5e1';
            ctx.lineWidth = 1.5;
            const corners = [
                [710, -490], [810, -490], [710, -390], [810, -390],
            ];
            for (const [cx, cy] of corners) {
                ctx.beginPath();
                ctx.arc(cx, cy, 14, 0, Math.PI * 2);
                ctx.fill();
                ctx.stroke();
            }
        }
    }

    _renderSumoRoads(ctx, geo) {
        const edges = geo.roads || geo.edges || [];
        ctx.lineCap = 'round';
        ctx.lineJoin = 'round';

        // Layer 1: Concrete Curbs
        for (const edge of edges) {
            for (const lane of edge.lanes || []) {
                const pts = lane.shape || [];
                if (pts.length < 2) continue;
                const lw = Math.max(20, (lane.width || 3.2) * 5.2);
                ctx.lineWidth = lw + 7.0;
                ctx.strokeStyle = '#94a3b8';
                ctx.beginPath();
                ctx.moveTo(pts[0][0], -pts[0][1]);
                for (let i = 1; i < pts.length; i++) ctx.lineTo(pts[i][0], -pts[i][1]);
                ctx.stroke();
            }
        }

        // Layer 2: High-Contrast Dark Asphalt
        for (const edge of edges) {
            for (const lane of edge.lanes || []) {
                const pts = lane.shape || [];
                if (pts.length < 2) continue;
                const lw = Math.max(18, (lane.width || 3.2) * 5.0);
                ctx.lineWidth = lw;
                ctx.strokeStyle = '#1e293b';
                ctx.beginPath();
                ctx.moveTo(pts[0][0], -pts[0][1]);
                for (let i = 1; i < pts.length; i++) ctx.lineTo(pts[i][0], -pts[i][1]);
                ctx.stroke();
            }
        }

        // Layer 3: Subtle Lane Dividers (between multi-lane edges, low opacity for vehicle contrast)
        for (const edge of edges) {
            const lanes = edge.lanes || [];
            if (lanes.length < 2) continue;
            for (let li = 0; li < lanes.length - 1; li++) {
                const pts = lanes[li].shape || [];
                if (pts.length < 2) continue;
                ctx.lineWidth = 0.8;
                ctx.strokeStyle = 'rgba(226, 232, 240, 0.22)';
                ctx.setLineDash([6, 8]);
                ctx.beginPath();
                ctx.moveTo(pts[0][0], -pts[0][1]);
                for (let i = 1; i < pts.length; i++) ctx.lineTo(pts[i][0], -pts[i][1]);
                ctx.stroke();
                ctx.setLineDash([]);
            }
        }
    }

    _renderTrafficLights(ctx, tlsMap, ctrlInfo) {
        const tlCoords = {
            TL_CENTRAL: [760, -440],
            TL_NW: [440, -680],
            TL_NE: [1080, -680],
            TL_SW: [440, -200],
            TL_SE: [1080, -200],
            GATE_MID_N: [760, -680],
            GATE_MID_S: [760, -200],
        };

        const ints = (ctrlInfo && ctrlInfo.intersections) || {};

        for (const [tlId, [cx, cy]] of Object.entries(tlCoords)) {
            const tl = tlsMap[tlId] || {};
            const pIdx = tl.phase_index ?? 0;
            const nsSig = pIdx === 0 ? 'GREEN' : pIdx === 1 ? 'YELLOW' : 'RED';
            const ewSig = pIdx === 2 ? 'GREEN' : pIdx === 3 ? 'YELLOW' : 'RED';

            const heads = [
                { x: cx + 26, y: cy - 44, sig: nsSig, rot: 0 },
                { x: cx - 26, y: cy + 44, sig: nsSig, rot: Math.PI },
                { x: cx + 44, y: cy + 26, sig: ewSig, rot: Math.PI / 2 },
                { x: cx - 44, y: cy - 26, sig: ewSig, rot: -Math.PI / 2 },
            ];

            for (const h of heads) {
                ctx.save();
                ctx.translate(h.x, h.y);
                ctx.rotate(h.rot);

                ctx.fillStyle = '#0f172a';
                ctx.strokeStyle = '#64748b';
                ctx.lineWidth = 1.0;
                ctx.beginPath();
                ctx.roundRect(-4, -10, 8, 20, 2);
                ctx.fill();
                ctx.stroke();

                const drawLamp = (ly, active, onCol, offCol) => {
                    ctx.fillStyle = active ? onCol : offCol;
                    ctx.beginPath();
                    ctx.arc(0, ly, 2.0, 0, Math.PI * 2);
                    ctx.fill();
                };
                drawLamp(-6.5, h.sig === 'RED', '#ef4444', '#450a0a');
                drawLamp(0, h.sig === 'YELLOW', '#f59e0b', '#451a03');
                drawLamp(6.5, h.sig === 'GREEN', '#10b981', '#022c22');
                ctx.restore();
            }

            // Stop Bars & Restrained Queue / Active Corridor Flow Indicators
            const drawBar = (x1, y1, x2, y2, sig) => {
                ctx.strokeStyle = sig === 'GREEN' ? '#10b981' : sig === 'YELLOW' ? '#f59e0b' : '#ef4444';
                ctx.lineWidth = 2.4;
                ctx.beginPath();
                ctx.moveTo(x1, y1);
                ctx.lineTo(x2, y2);
                ctx.stroke();
            };
            drawBar(cx - 22, cy - 33, cx + 22, cy - 33, nsSig);
            drawBar(cx - 22, cy + 33, cx + 22, cy + 33, nsSig);
            drawBar(cx + 33, cy - 22, cx + 33, cy + 22, ewSig);
            drawBar(cx - 33, cy - 22, cx - 33, cy + 22, ewSig);

            // Subtle Directional Flow Indicator on Active Green Corridor (smooth fade in/out)
            const snap = ints[tlId];
            if (this.latestPayload?.is_running && !this.latestPayload?.is_paused) {
                const alphaState = this.corridorAlphas.get(tlId) || { ns: 0, ew: 0 };
                const targetNs = pIdx === 0 ? 0.42 : 0.0;
                const targetEw = pIdx === 2 ? 0.42 : 0.0;
                const fLerp = this._reducedMotion ? 1.0 : 0.14;
                alphaState.ns += (targetNs - alphaState.ns) * fLerp;
                alphaState.ew += (targetEw - alphaState.ew) * fLerp;
                this.corridorAlphas.set(tlId, alphaState);

                if (alphaState.ns > 0.02) {
                    ctx.save();
                    ctx.strokeStyle = `rgba(16, 185, 129, ${alphaState.ns.toFixed(2)})`;
                    ctx.lineWidth = 2.2;
                    ctx.setLineDash([6, 8]);
                    ctx.lineDashOffset = -this._flowPhase;
                    ctx.beginPath();
                    ctx.moveTo(cx, cy - 58);
                    ctx.lineTo(cx, cy + 58);
                    ctx.stroke();
                    ctx.setLineDash([]);
                    ctx.restore();
                }
                if (alphaState.ew > 0.02) {
                    ctx.save();
                    ctx.strokeStyle = `rgba(16, 185, 129, ${alphaState.ew.toFixed(2)})`;
                    ctx.lineWidth = 2.2;
                    ctx.setLineDash([6, 8]);
                    ctx.lineDashOffset = -this._flowPhase;
                    ctx.beginPath();
                    ctx.moveTo(cx - 58, cy);
                    ctx.lineTo(cx + 58, cy);
                    ctx.stroke();
                    ctx.setLineDash([]);
                    ctx.restore();
                }
            }

            // Restrained Queue Emphasis on Approaches with Real Queued Vehicles (>= 3)
            if (snap && snap.corridor_metrics) {
                const qNS = snap.corridor_metrics['0']?.queue_raw || 0;
                const qEW = snap.corridor_metrics['1']?.queue_raw || 0;
                if (qNS >= 3) {
                    ctx.fillStyle = 'rgba(239, 68, 68, 0.14)';
                    ctx.fillRect(cx - 18, cy - 82, 36, 46);
                }
                if (qEW >= 3) {
                    ctx.fillStyle = 'rgba(239, 68, 68, 0.14)';
                    ctx.fillRect(cx - 82, cy - 18, 46, 36);
                }
            }

            // Intersection Name & Phase Tag
            const remTxt = snap && snap.stage === 'MAIN_GREEN' ? ` · ${snap.remaining_max_green_sec}s` : '';
            const label = `${tlId}${remTxt}`;
            ctx.save();
            ctx.font = `600 ${Math.max(8, 10 / Math.max(0.7, this.camera.zoom * 0.65))}px Inter, sans-serif`;
            const tw = ctx.measureText(label).width + 10;
            ctx.fillStyle = tlId === this.selectedTlId ? '#f0fdfa' : 'rgba(255,255,255,0.92)';
            ctx.strokeStyle = tlId === this.selectedTlId ? '#0f766e' : '#cbd5e1';
            ctx.lineWidth = 1.2 / this.camera.zoom;
            ctx.beginPath();
            ctx.roundRect(cx - tw / 2, cy - 66, tw, 16, 4);
            ctx.fill();
            ctx.stroke();
            ctx.fillStyle = '#0f172a';
            ctx.textAlign = 'center';
            ctx.textBaseline = 'middle';
            ctx.fillText(label, cx, cy - 58);
            ctx.restore();
        }
    }

    _renderVehicles(ctx, vehicles) {
        const carColors = ['#0284c7', '#3b82f6', '#10b981', '#64748b', '#e11d48'];

        for (const v of vehicles) {
            const pose = this.vehPosMap.get(v.id || v.num_id) || { x: v.x, y: v.y, angle: v.angle || 0 };
            const x = pose.x;
            const y = -pose.y;
            const angleRad = (pose.angle * Math.PI) / 180.0;
            const cls = (v.class || 'car').toLowerCase();
            const isStopped = v.is_queued || (v.speed_kmh < 2.5);

            let len = 4.8, wid = 2.1;
            let bodyColor = '#2563eb';
            if (cls === 'bus') {
                len = 12.0; wid = 2.8; bodyColor = '#f59e0b';
            } else if (cls === 'truck') {
                len = 9.5; wid = 2.6; bodyColor = '#64748b';
            } else if (cls === 'motorcycle') {
                len = 2.2; wid = 1.0; bodyColor = '#06b6d4';
            } else if (cls === 'emergency') {
                len = 5.5; wid = 2.2; bodyColor = '#dc2626';
            } else {
                const hash = (v.num_id || 0) * 17;
                bodyColor = carColors[hash % carColors.length];
            }

            const minLen = cls === 'bus' ? 44 : cls === 'truck' ? 38 : cls === 'motorcycle' ? 16 : 25;
            const minWid = cls === 'bus' ? 14 : cls === 'truck' ? 13 : cls === 'motorcycle' ? 7 : 11;
            len = Math.max(len, minLen / this.camera.zoom);
            wid = Math.max(wid, minWid / this.camera.zoom);

            ctx.save();
            ctx.translate(x, y);
            ctx.rotate(angleRad);

            // Headlight Beam
            ctx.fillStyle = 'rgba(254, 240, 138, 0.22)';
            ctx.beginPath();
            ctx.moveTo(-wid * 0.4, -len / 2);
            ctx.lineTo(-wid * 0.9, -len / 2 - 12);
            ctx.lineTo(-wid * 0.1, -len / 2 - 12);
            ctx.closePath();
            ctx.fill();

            // Vehicle Body
            ctx.fillStyle = bodyColor;
            ctx.strokeStyle = '#0f172a';
            ctx.lineWidth = 1.1;
            ctx.beginPath();
            ctx.roundRect(-wid / 2, -len / 2, wid, len, 3);
            ctx.fill();
            ctx.stroke();

            // Cabin / Cargo Details
            ctx.fillStyle = '#0f172a';
            if (cls === 'bus') {
                ctx.beginPath();
                ctx.roundRect(-wid * 0.42, -len * 0.42, wid * 0.84, len * 0.84, 2);
                ctx.fill();
            } else if (cls === 'truck') {
                ctx.beginPath();
                ctx.roundRect(-wid * 0.44, -len * 0.44, wid * 0.88, len * 0.32, 2);
                ctx.fill();
                ctx.fillStyle = '#cbd5e1';
                ctx.fillRect(-wid * 0.42, -len * 0.05, wid * 0.84, len * 0.48);
            } else if (cls === 'motorcycle') {
                ctx.fillStyle = '#f8fafc';
                ctx.beginPath();
                ctx.arc(0, 0, wid * 0.4, 0, Math.PI * 2);
                ctx.fill();
            } else {
                ctx.beginPath();
                ctx.roundRect(-wid * 0.38, -len * 0.28, wid * 0.76, len * 0.52, 2);
                ctx.fill();
            }

            // Brake Lights when stopped/queued
            if (isStopped) {
                ctx.fillStyle = '#ef4444';
                ctx.fillRect(-wid * 0.48, len / 2 - 2, wid * 0.28, 2.5);
                ctx.fillRect(wid * 0.20, len / 2 - 2, wid * 0.28, 2.5);
            }

            ctx.restore();

            // ID & Speed Badge when zoomed in
            if (this.camera.zoom > 1.85) {
                ctx.save();
                ctx.font = '600 8px JetBrains Mono, monospace';
                ctx.fillStyle = 'rgba(15, 23, 42, 0.78)';
                ctx.textAlign = 'center';
                ctx.fillText(`#${v.num_id}`, x, y - len / 2 - 5);
                ctx.restore();
            }
        }
    }
}

window.SumoCanvasRenderer = SumoCanvasRenderer;
