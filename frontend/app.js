// Traffic Intel — Main Application Controller

const simRenderer = new window.SumoCanvasRenderer('sim-canvas');
const trafficMapView = new window.TrafficMapView();
const cameraView = new window.CameraViewController();
window.trafficMapView = trafficMapView;

const PAGE_TITLES = {
    overview: 'Overview',
    map: 'Live Traffic Map',
    cameras: 'Live Cameras',
    simulation: 'Adaptive Simulation',
    analytics: 'Analytics',
    settings: 'Settings',
};

function updateSidebarIndicator() {
    const bar = document.getElementById('nav-active-bar');
    const activeBtn = document.querySelector('.nav-item.active');
    if (bar && activeBtn) {
        const top = activeBtn.offsetTop + (activeBtn.offsetHeight - 22) / 2;
        bar.style.transform = `translateY(${top}px)`;
        bar.style.opacity = '1';
    }
}

function navigateTo(pageId) {
    document.querySelectorAll('.nav-item').forEach((btn) => {
        btn.classList.toggle('active', btn.dataset.page === pageId);
    });
    updateSidebarIndicator();

    document.querySelectorAll('.page-section').forEach((sec) => {
        const isTarget = sec.id === `page-${pageId}`;
        sec.classList.remove('active');
        if (isTarget) {
            void sec.offsetWidth; // trigger clean entrance animation
            sec.classList.add('active');
        }
    });
    document.getElementById('topbar-title').textContent = PAGE_TITLES[pageId] || 'Traffic Intel';

    if (pageId === 'map') {
        trafficMapView.init();
        trafficMapView.invalidateSize();
    } else if (pageId === 'simulation') {
        simRenderer.render();
    }
}

// Camera UI helpers
function onCameraTypeChange() { cameraView.onTypeChange(); }
function connectCamera() { cameraView.connect(); }
function disconnectCamera() { cameraView.disconnect(); }
function restartCamera() { cameraView.restart(); }
function applyCameraToSumo() { cameraView.applyToSumo(); }

// Map UI helpers
function searchMapLocation() {
    const q = document.getElementById('map-search-input').value;
    trafficMapView.searchLocation(q);
}
function refreshMapTraffic() { trafficMapView.refresh(); }

// Simulation Controls
async function simAction(action) {
    await fetch(`/api/control/${action}`, { method: 'POST' });
    refreshOverview();
}

async function setControllerMode(mode) {
    const fd = new FormData();
    fd.append('mode', mode);
    await fetch('/api/control/mode', { method: 'POST', body: fd });
}

function setCameraZone(zone) {
    simRenderer.setZone(zone);
}
function simZoomIn() { simRenderer.zoomIn(); }
function simZoomOut() { simRenderer.zoomOut(); }
function simResetZoom() { simRenderer.resetZoom(); }
function simFitNetwork() {
    const sel = document.getElementById('sim-zone-select');
    if (sel) sel.value = 'CITY_OVERVIEW';
    simRenderer.fitNetwork();
}
function selectIntersectionFocus(tlId) {
    simRenderer.selectedTlId = tlId;
    const zoneMap = {
        TL_CENTRAL: 'CITY_SQUARE',
        TL_NW: 'NORTHWEST_DISTRICT',
        TL_NE: 'NORTHEAST_DISTRICT',
        TL_SW: 'SOUTHWEST_DISTRICT',
        TL_SE: 'SOUTHEAST_DISTRICT',
    };
    if (zoneMap[tlId]) {
        const sel = document.getElementById('sim-zone-select');
        if (sel) sel.value = zoneMap[tlId];
        simRenderer.setZone(zoneMap[tlId]);
    }
}

async function applySimTimings() {
    const minG = parseFloat(document.getElementById('sim-min-green').value);
    const maxG = parseFloat(document.getElementById('sim-max-green').value);
    const maxR = parseFloat(document.getElementById('sim-max-red').value);
    const yel = parseFloat(document.getElementById('sim-yellow').value);
    const msgEl = document.getElementById('sim-timing-msg');

    if (isNaN(minG) || isNaN(maxG) || isNaN(maxR) || isNaN(yel)) {
        msgEl.style.color = '#b91c1c';
        msgEl.textContent = 'Enter valid numeric timing values.';
        return;
    }
    if (maxG <= minG) {
        msgEl.style.color = '#b91c1c';
        msgEl.textContent = 'Max Green must be greater than Min Green.';
        return;
    }
    if (maxR <= 0) {
        msgEl.style.color = '#b91c1c';
        msgEl.textContent = 'Max Red must be greater than 0.';
        return;
    }
    if (yel < 3) {
        msgEl.style.color = '#b91c1c';
        msgEl.textContent = 'Yellow clearance must be at least 3s for safe phase transitions.';
        return;
    }

    const fd = new FormData();
    fd.append('min_green', minG);
    fd.append('max_green', maxG);
    fd.append('max_red', maxR);
    fd.append('yellow_dur', yel);
    fd.append('green_wave', document.getElementById('sim-mode-select').value === 'GREEN_WAVE');

    const resp = await fetch('/api/settings/timings', { method: 'POST', body: fd });
    const data = await resp.json();
    if (resp.ok) {
        msgEl.style.color = '#15803d';
        msgEl.textContent = `Applied (MinG=${minG}s, MaxG=${maxG}s, MaxR=${maxR}s, Yellow=${yel}s).`;
    } else {
        msgEl.style.color = '#b91c1c';
        msgEl.textContent = data.message || 'Validation failed.';
    }
}

async function setSimSpeed(multiplier) {
    const fd = new FormData();
    fd.append('multiplier', multiplier);
    await fetch('/api/control/sim_speed', { method: 'POST', body: fd });
}

async function setScenario(scenario) {
    const fd = new FormData();
    fd.append('scenario', scenario);
    await fetch('/api/simulation/scenario', { method: 'POST', body: fd });
}

const _prevNumValues = new Map();
const _prefersReducedMotion = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

function animateNumber(el, targetVal, suffix = '') {
    if (!el) return;
    const prev = _prevNumValues.get(el.id);
    if (prev === targetVal) return;
    _prevNumValues.set(el.id, targetVal);

    if (_prefersReducedMotion || typeof prev !== 'number' || isNaN(targetVal)) {
        el.textContent = `${targetVal}${suffix}`;
        return;
    }
    const start = prev;
    const diff = targetVal - start;
    const duration = 240;
    const t0 = performance.now();
    const step = (now) => {
        const p = Math.min(1, (now - t0) / duration);
        const eased = 1 - Math.pow(1 - p, 3);
        const val = Math.round(start + diff * eased);
        el.textContent = `${val}${suffix}`;
        if (p < 1) requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
}

// Overview Polling
async function refreshOverview() {
    try {
        const resp = await fetch('/api/overview');
        const data = await resp.json();

        const sim = data.simulation || {};
        const cam = data.camera || {};
        const prov = data.traffic_provider || {};

        // Topbar pills
        const pSim = document.getElementById('pill-sim');
        pSim.innerHTML = `<span class="dot"></span> Simulation: ${sim.is_running ? (sim.is_paused ? 'Paused' : 'Running') : 'Stopped'}`;
        pSim.className = 'status-pill ' + (sim.is_running && !sim.is_paused ? 'ok' : sim.is_paused ? 'warn' : '');

        const pCam = document.getElementById('pill-cam');
        pCam.innerHTML = `<span class="dot"></span> Camera: ${cam.state}`;
        pCam.className = 'status-pill ' + (cam.state === 'PROCESSING' || cam.state === 'CONNECTED' ? 'ok' : cam.state === 'ERROR' ? 'err' : '');

        const pProv = document.getElementById('pill-prov');
        pProv.innerHTML = `<span class="dot"></span> Traffic API: ${prov.configured ? prov.provider.toUpperCase() : 'Not Connected'}`;
        pProv.className = 'status-pill ' + (prov.configured ? 'ok' : '');

        // Overview KPIs & Accurate Animated Indicators (only pulse when truly active)
        const simActive = Boolean(sim.is_running && !sim.is_paused);
        const camActive = cam.state === 'PROCESSING' || cam.state === 'CONNECTED';
        const provActive = Boolean(prov.configured);

        const simDot = document.getElementById('ov-sim-dot');
        if (simDot) {
            simDot.style.background = simActive ? '#16a34a' : (sim.is_paused ? '#d97706' : '#94a3b8');
            simDot.className = simActive ? 'live-dot-active' : '';
        }
        const camDot = document.getElementById('ov-cam-dot');
        if (camDot) {
            camDot.style.background = camActive ? '#16a34a' : (cam.state === 'ERROR' ? '#dc2626' : '#94a3b8');
            camDot.className = camActive ? 'live-dot-active' : '';
        }
        const provDot = document.getElementById('ov-prov-dot');
        if (provDot) {
            provDot.style.background = provActive ? '#16a34a' : '#94a3b8';
            provDot.className = provActive ? 'live-dot-active' : '';
        }

        document.getElementById('ov-sim-state').textContent = sim.is_running ? (sim.is_paused ? 'Paused' : 'Running') : 'Stopped';
        document.getElementById('ov-sim-sub').textContent = sim.is_running ? `Controller: ${sim.controller_mode}` : 'Start simulation to run SUMO';
        document.getElementById('ov-cam-state').textContent = cam.state || 'DISCONNECTED';
        document.getElementById('ov-cam-sub').textContent = cam.source_label || 'No camera connected';
        document.getElementById('ov-prov-state').textContent = prov.configured ? prov.provider.toUpperCase() : 'Not Connected';
        document.getElementById('ov-prov-sub').textContent = prov.configured ? 'Live traffic feed active' : 'Configure in Settings';

        const fleetEl = document.getElementById('ov-sim-vehicles');
        if (sim.is_running) {
            animateNumber(fleetEl, Number(sim.active_vehicles || 0));
        } else {
            _prevNumValues.delete('ov-sim-vehicles');
            fleetEl.textContent = '—';
        }
        document.getElementById('ov-sim-speed').textContent = sim.is_running ? `Avg ${sim.avg_speed_kmh} km/h · ${sim.total_queued} queued` : 'Source: Simulation';

        // Intersection Overview Table
        const intContainer = document.getElementById('ov-intersections-container');
        const ints = sim.intersections || {};
        if (!sim.is_running) {
            intContainer.innerHTML = '<div class="empty-state">Simulation stopped. Start the simulation on the Adaptive Simulation page to inspect live intersection phases.</div>';
        } else if (Object.keys(ints).length > 0) {
            let html = '<table class="table"><thead><tr><th>Intersection</th><th>Active Phase</th><th>Fairness</th><th>Elapsed</th></tr></thead><tbody>';
            for (const tid of ['TL_CENTRAL', 'TL_NW', 'TL_NE', 'TL_SW', 'TL_SE']) {
                const s = ints[tid];
                if (!s) continue;
                const dotClass = s.stage === 'MAIN_YELLOW' ? 'sig-yellow' : 'sig-green';
                html += `<tr>
                    <td><strong>${s.name}</strong><div class="mono" style="font-size:11px;color:#64748b;">${tid}</div></td>
                    <td><span class="sig-dot ${dotClass}"></span>${s.phase_description}</td>
                    <td><span class="source-badge">${s.fairness_status}</span></td>
                    <td class="mono">${s.stage_elapsed_sec}s</td>
                </tr>`;
            }
            html += '</tbody></table>';
            intContainer.innerHTML = html;
        }
    } catch (e) {
        console.warn('Overview poll failed:', e);
    }
}

const _phaseTimeline = [];
let _lastRecordedPhaseKey = '';

function updateSignalStripAndTimeline(payload, sSel, selId) {
    const stripTl = document.getElementById('strip-tl-id');
    const stripDot = document.getElementById('strip-phase-dot');
    const stripDesc = document.getElementById('strip-phase-desc');
    const stripTimer = document.getElementById('strip-phase-timer');
    const stripBar = document.getElementById('strip-phase-bar');
    const timelineEl = document.getElementById('sim-phase-timeline');

    if (!payload.is_running || !sSel) {
        if (stripDesc) stripDesc.textContent = 'Simulation stopped';
        if (stripBar) stripBar.style.width = '0%';
        return;
    }

    const isYellow = sSel.stage === 'MAIN_YELLOW';
    if (stripTl) stripTl.textContent = selId;
    if (stripDot) stripDot.className = `sig-dot ${isYellow ? 'sig-yellow' : 'sig-green'}`;
    if (stripDesc) stripDesc.textContent = `${sSel.phase_description} (${isYellow ? 'Yellow Clearance' : 'Green'})`;
    if (stripTimer) stripTimer.textContent = `${sSel.stage_elapsed_sec}s / ${sSel.max_green_sec || 45}s`;
    if (stripBar) {
        const maxRef = isYellow ? 3.0 : (sSel.max_green_sec || 45.0);
        const pct = Math.min(100, Math.round((sSel.stage_elapsed_sec / maxRef) * 100));
        stripBar.style.width = `${pct}%`;
        stripBar.style.backgroundColor = isYellow ? '#eab308' : '#0f766e';
    }

    const phaseKey = `${selId}:${sSel.active_corridor}:${sSel.stage}`;
    if (phaseKey !== _lastRecordedPhaseKey) {
        _lastRecordedPhaseKey = phaseKey;
        const simTime = payload.telemetry?.simulation_time ?? 0;
        const reason = sSel.fairness_override ? sSel.fairness_status.replaceAll('_', ' ') : 'DQN Adaptive';
        _phaseTimeline.unshift({
            simTime,
            tl: selId,
            desc: sSel.phase_description,
            stage: isYellow ? 'Yellow Clearance' : 'Green Active',
            dot: isYellow ? 'sig-yellow' : 'sig-green',
            reason,
        });
        if (_phaseTimeline.length > 5) _phaseTimeline.pop();

        if (timelineEl) {
            timelineEl.innerHTML = _phaseTimeline
                .map(
                    (item) => `<div class="timeline-item">
                        <span class="sig-dot ${item.dot}"></span>
                        <span class="mono" style="color:#64748b;">${item.simTime}s</span>
                        <span style="flex:1;"><strong>${item.desc}</strong> · ${item.stage}</span>
                        <span class="source-badge">${item.reason}</span>
                    </div>`
                )
                .join('');
        }
    }
}

// Simulation Telemetry SSE Stream
function startTelemetryStream() {
    const es = new EventSource('/api/stream');
    es.onmessage = (evt) => {
        try {
            const payload = JSON.parse(evt.data);
            simRenderer.updateTelemetry(payload);

            const m = payload.metrics || {};
            animateNumber(document.getElementById('sim-m-active'), Number(m.total_active ?? 0));
            animateNumber(document.getElementById('sim-m-queued'), Number(m.total_queued ?? 0));
            document.getElementById('sim-m-speed').textContent = `${m.average_speed_kmh ?? 0} km/h`;
            document.getElementById('sim-m-time').textContent = `${payload.telemetry?.simulation_time ?? 0}s`;
            document.getElementById('sim-ctrl-badge').textContent = payload.controller_mode || 'DQN';

            const listEl = document.getElementById('sim-intersections-list');
            const decPanel = document.getElementById('sim-decision-panel');
            const decTlBadge = document.getElementById('sim-dec-tl');
            const ints = payload.controller_info?.intersections || {};
            const selId = simRenderer.selectedTlId || 'TL_CENTRAL';
            if (decTlBadge) decTlBadge.textContent = selId;

            if (!payload.is_running) {
                listEl.innerHTML = '<div class="empty-state">Simulation stopped.</div>';
                if (decPanel) decPanel.innerHTML = '<div class="empty-state">Simulation stopped.</div>';
            } else if (Object.keys(ints).length > 0) {
                const sSel = ints[selId] || ints.TL_CENTRAL;
                updateSignalStripAndTimeline(payload, sSel, selId);
                if (decPanel && sSel) {
                    const ovrBadge = sSel.fairness_override
                        ? '<span class="status-pill warn">Fairness Override Active</span>'
                        : '<span class="status-pill ok">DQN Adaptive</span>';
                    decPanel.innerHTML = `
                        <div style="margin-bottom:8px;">${ovrBadge}</div>
                        <div style="margin-bottom:4px;"><strong>DQN Recommendation:</strong> ${sSel.dqn_recommended_desc || '—'}</div>
                        <div style="margin-bottom:4px;"><strong>Safety Validation:</strong> <span class="mono">${sSel.safety_validation || 'SAFE_4PHASE_OK'}</span></div>
                        <div style="margin-bottom:4px;"><strong>Final Signal Action:</strong> ${sSel.phase_description} (${sSel.stage === 'MAIN_YELLOW' ? 'YELLOW' : 'GREEN'}, ${sSel.stage_elapsed_sec}s / rem ${sSel.remaining_max_green_sec}s)</div>
                        <div style="background:var(--bg-subtle); padding:8px 10px; border-radius:6px; margin-top:6px; color:#0f172a;">
                            ${sSel.explanation}
                        </div>
                    `;
                }

                listEl.innerHTML = ['TL_CENTRAL', 'TL_NW', 'TL_NE', 'TL_SW', 'TL_SE']
                    .filter((id) => ints[id])
                    .map((id) => {
                        const s = ints[id];
                        const cm0 = s.corridor_metrics?.['0'] || {};
                        const cm1 = s.corridor_metrics?.['1'] || {};
                        const activeBorder = id === selId ? 'border-color:#0f766e; background:#f0fdfa;' : 'border-color:#e2e8f0;';
                        return `<div onclick="selectIntersectionFocus('${id}')" style="cursor:pointer; padding:10px; border:1px solid; ${activeBorder} border-radius:8px; margin-bottom:8px;">
                            <div style="display:flex; justify-content:space-between; font-weight:600; margin-bottom:4px;">
                                <span>${s.name}</span>
                                <span class="source-badge">${s.fairness_status}</span>
                            </div>
                            <div style="color:#475569; margin-bottom:4px;">
                                Phase: <strong>${s.phase_description}</strong> (${s.stage_elapsed_sec}s)
                            </div>
                            <div class="mono" style="font-size:11px; color:#64748b;">
                                NS Q:${cm0.queue_raw ?? 0} Red:${cm0.red_sec ?? 0}s | EW Q:${cm1.queue_raw ?? 0} Red:${cm1.red_sec ?? 0}s
                            </div>
                        </div>`;
                    })
                    .join('');
            }
        } catch (e) {
            console.warn('SSE parse error:', e);
        }
    };
}

// Analytics Comparison Benchmark
async function runComparisonBenchmark() {
    const btn = document.getElementById('cmp-run-btn');
    const card = document.getElementById('cmp-results-card');
    const scenario = document.getElementById('cmp-scenario').value;
    const steps = document.getElementById('cmp-steps').value;

    btn.disabled = true;
    btn.textContent = 'Running SUMO Benchmark...';
    card.innerHTML = '<div class="empty-state">Executing controlled Fixed-Time vs Adaptive DQN runs in SUMO...</div>';

    try {
        const fd = new FormData();
        fd.append('scenario', scenario);
        fd.append('steps', steps);
        const resp = await fetch('/api/analytics/compare', { method: 'POST', body: fd });
        const data = await resp.json();
        if (!data.available) {
            card.innerHTML = `<div class="empty-state">${data.error || 'Benchmark failed.'}</div>`;
            return;
        }
        const r = data.result;
        const f = r.fixed_time;
        const a = r.adaptive_dqn;
        const d = r.deltas;

        card.innerHTML = `
            <div class="card-title">
                <span>Controlled Benchmark Results — ${r.scenario} (${r.sim_duration_sec}s simulated)</span>
                <span class="source-badge">${r.data_source}</span>
            </div>
            <table class="table">
                <thead>
                    <tr>
                        <th>Metric</th>
                        <th>Fixed-Time Baseline</th>
                        <th>Adaptive DQN</th>
                        <th>Measured Difference</th>
                    </tr>
                </thead>
                <tbody>
                    <tr>
                        <td>Average Waiting Time</td>
                        <td class="mono">${f.avg_waiting_time_sec} s</td>
                        <td class="mono">${a.avg_waiting_time_sec} s</td>
                        <td class="mono">${d.waiting_time_reduction_pct}% reduction</td>
                    </tr>
                    <tr>
                        <td>Average Queue Length</td>
                        <td class="mono">${f.avg_queue_length} veh</td>
                        <td class="mono">${a.avg_queue_length} veh</td>
                        <td class="mono">${d.queue_reduction_pct}% reduction</td>
                    </tr>
                    <tr>
                        <td>Average Speed</td>
                        <td class="mono">${f.avg_speed_kmh} km/h</td>
                        <td class="mono">${a.avg_speed_kmh} km/h</td>
                        <td class="mono">${d.speed_improvement_pct}% change</td>
                    </tr>
                    <tr>
                        <td>Total Vehicles Served</td>
                        <td class="mono">${f.total_vehicles_served}</td>
                        <td class="mono">${a.total_vehicles_served}</td>
                        <td class="mono">${d.throughput_change_pct}% change</td>
                    </tr>
                    <tr>
                        <td>Throughput</td>
                        <td class="mono">${f.throughput_vph} veh/h</td>
                        <td class="mono">${a.throughput_vph} veh/h</td>
                        <td class="mono">—</td>
                    </tr>
                    <tr>
                        <td>Total Time Waiting</td>
                        <td class="mono">${f.total_time_waiting_sec} veh·s</td>
                        <td class="mono">${a.total_time_waiting_sec} veh·s</td>
                        <td class="mono">—</td>
                    </tr>
                </tbody>
            </table>
        `;
    } catch (e) {
        card.innerHTML = `<div class="empty-state">Error running comparison: ${e}</div>`;
    } finally {
        btn.disabled = false;
        btn.textContent = 'Run Comparison Benchmark';
    }
}

// Settings
async function loadSettings() {
    const resp = await fetch('/api/settings');
    const data = await resp.json();
    const t = data.timings || {};
    document.getElementById('set-min-green').value = t.min_green_sec ?? 10;
    document.getElementById('set-max-green').value = t.max_green_sec ?? 45;
    document.getElementById('set-max-red').value = t.max_red_sec ?? 50;
    document.getElementById('set-green-wave').checked = Boolean(t.green_wave_enabled);

    const p = data.provider || {};
    document.getElementById('set-provider').value = p.provider || 'none';
    if (p.default_center) {
        document.getElementById('set-lat').value = p.default_center[0];
        document.getElementById('set-lon').value = p.default_center[1];
    }
}

async function saveTimingSettings() {
    const fd = new FormData();
    fd.append('min_green', document.getElementById('set-min-green').value);
    fd.append('max_green', document.getElementById('set-max-green').value);
    fd.append('max_red', document.getElementById('set-max-red').value);
    fd.append('green_wave', document.getElementById('set-green-wave').checked);
    await fetch('/api/settings/timings', { method: 'POST', body: fd });
    document.getElementById('set-timing-msg').textContent = 'Signal timings updated.';
}

async function saveProviderSettings() {
    const fd = new FormData();
    fd.append('provider', document.getElementById('set-provider').value);
    fd.append('api_key', document.getElementById('set-api-key').value);
    fd.append('default_lat', document.getElementById('set-lat').value);
    fd.append('default_lon', document.getElementById('set-lon').value);
    const resp = await fetch('/api/settings/provider', { method: 'POST', body: fd });
    const data = await resp.json();
    document.getElementById('set-provider-msg').textContent = data.message;
    refreshOverview();
}

// Initialize Application
window.addEventListener('DOMContentLoaded', async () => {
    updateSidebarIndicator();
    try {
        const geoResp = await fetch('/api/network/geometry');
        const geo = await geoResp.json();
        simRenderer.setGeometry(geo);
    } catch (e) {
        console.warn('Could not load SUMO geometry:', e);
    }
    loadSettings();
    refreshOverview();
    setInterval(refreshOverview, 2500);
    startTelemetryStream();
    cameraView.startPolling();
});
