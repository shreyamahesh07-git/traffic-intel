// Traffic Intel — Live Camera Analytics (Browser MediaDevices + Backend RTSP/HTTP + Explicit Demo)

class CameraViewController {
    constructor() {
        this.pollTimer = null;
        this.currentState = 'Disconnected';
        this.webcamStream = null;
        this.webcamWs = null;
        this.webcamFrameTimer = null;
        this._inFlight = false;
        this._confirmedBackendProcessing = false;
        this.offscreenCanvas = document.createElement('canvas');
        this.latestBoxes = [];
        this.lineYRatio = 0.55;
    }

    async startPolling() {
        await this.populateWebcamDevices();
        this.onTypeChange();
        if (!this.pollTimer) {
            this.fetchStatus();
            this.pollTimer = setInterval(() => this.fetchStatus(), 1200);
        }
    }

    async populateWebcamDevices() {
        const sel = document.getElementById('cam-webcam-device');
        if (!sel || !navigator.mediaDevices || !navigator.mediaDevices.enumerateDevices) return;
        try {
            const devices = await navigator.mediaDevices.enumerateDevices();
            const cams = devices.filter((d) => d.kind === 'videoinput');
            const prevVal = sel.value;
            sel.innerHTML = '';
            if (cams.length === 0) {
                sel.innerHTML = '<option value="">Default System Webcam</option>';
            } else {
                cams.forEach((cam, idx) => {
                    const opt = document.createElement('option');
                    opt.value = cam.deviceId;
                    opt.textContent = cam.label || `Camera ${idx + 1}`;
                    sel.appendChild(opt);
                });
                if (prevVal && cams.some((c) => c.deviceId === prevVal)) {
                    sel.value = prevVal;
                }
            }
        } catch (e) {
            sel.innerHTML = '<option value="">Default System Webcam</option>';
        }
    }

    onTypeChange() {
        const type = document.getElementById('cam-source-type').value;
        const verSel = document.getElementById('cam-verified-select');
        const devSel = document.getElementById('cam-webcam-device');
        const urlInput = document.getElementById('cam-source-value');

        verSel.style.display = type === 'verified_live' ? 'block' : 'none';
        devSel.style.display = type === 'webcam' ? 'block' : 'none';
        urlInput.style.display = (type === 'rtsp' || type === 'http' || type === 'video') ? 'block' : 'none';

        if (type === 'rtsp') {
            urlInput.value = 'rtsp://samples.rts.videodb.io:8554/traffic';
            urlInput.placeholder = 'rtsp://user:pass@ip:554/stream';
        } else if (type === 'http') {
            urlInput.value = '';
            urlInput.placeholder = 'http://ip:port/video';
        } else if (type === 'video') {
            urlInput.value = 'sample_traffic.mp4';
            urlInput.placeholder = 'Demo video filename (e.g. sample_traffic.mp4)';
        }
    }

    async connect() {
        // Always release any prior webcam or backend stream before starting a new one
        await this.disconnect();

        const st = document.getElementById('cam-source-type').value;
        if (st === 'webcam') {
            await this._connectBrowserWebcam();
        } else if (st === 'verified_live') {
            const camId = document.getElementById('cam-verified-select').value;
            const camLabel = document.getElementById('cam-verified-select').selectedOptions[0]?.textContent || camId;
            this._setUiState('Connecting', camLabel, null, 'warn');
            const fd = new FormData();
            fd.append('source_type', 'verified_live');
            fd.append('source_value', camId);
            const resp = await fetch('/api/camera/connect', { method: 'POST', body: fd });
            const data = await resp.json();
            this._renderBackendStatus(data);
        } else {
            const sv = document.getElementById('cam-source-value').value.trim();
            this._setUiState('Connecting', st === 'video' ? 'Demo Video (Test Source)' : 'Connecting...', null, 'warn');
            const fd = new FormData();
            fd.append('source_type', st);
            fd.append('source_value', sv);
            const resp = await fetch('/api/camera/connect', { method: 'POST', body: fd });
            const data = await resp.json();
            this._renderBackendStatus(data);
        }
    }

    async _connectBrowserWebcam() {
        if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
            this._setUiState('Camera error', 'Local Webcam', 'Browser MediaDevices API is unavailable. Open via http://localhost:8000 or HTTPS.', 'err');
            return;
        }

        const devSel = document.getElementById('cam-webcam-device');
        const deviceId = devSel ? devSel.value : '';
        const selectedLabel = devSel && devSel.selectedOptions[0] ? devSel.selectedOptions[0].textContent : 'Local Webcam';

        this._setUiState('Requesting permission', selectedLabel, null, 'warn');

        let stream = null;
        try {
            // Use ideal deviceId first if available, fallback cleanly if exact fails
            const videoConstraints = deviceId
                ? { deviceId: { ideal: deviceId }, width: { ideal: 960 }, height: { ideal: 540 } }
                : { width: { ideal: 960 }, height: { ideal: 540 } };
            stream = await navigator.mediaDevices.getUserMedia({ video: videoConstraints, audio: false });
        } catch (err) {
            this._handleWebcamError(err, selectedLabel);
            return;
        }

        // Verify MediaStream has an active, enabled video track
        const tracks = stream.getVideoTracks();
        if (!tracks || tracks.length === 0 || tracks[0].readyState === 'ended') {
            stream.getTracks().forEach((t) => t.stop());
            this._setUiState('Camera error', selectedLabel, 'Selected camera returned an inactive or empty video track.', 'err');
            return;
        }

        tracks[0].enabled = true;
        this.webcamStream = stream;
        await this.populateWebcamDevices();

        const trackLabel = tracks[0].label || selectedLabel;
        tracks[0].onended = () => {
            if (this.webcamStream === stream) {
                this._setUiState('Camera error', trackLabel, 'Camera stream ended unexpectedly or was disconnected.', 'err');
                this._stopWebcamHardwareOnly();
            }
        };

        this._setUiState('Connecting', trackLabel, null, 'warn');

        const video = document.getElementById('cam-webcam-video');
        const canvas = document.getElementById('cam-overlay-canvas');
        const viewport = document.getElementById('cam-viewport');
        const emptyMsg = document.getElementById('cam-empty-msg');

        // Configure video element explicitly for reliable browser webcam playback
        video.muted = true;
        video.autoplay = true;
        video.playsInline = true;
        video.srcObject = stream;
        video.style.display = 'block';
        canvas.style.display = 'block';
        viewport.classList.add('live-active');
        emptyMsg.style.display = 'none';

        // Wait for loadedmetadata and real dimensions
        try {
            await this._waitForVideoMetadata(video, 5000);
            await video.play();
        } catch (playErr) {
            await this.disconnect();
            this._setUiState('Camera error', trackLabel, `Video playback failed: ${playErr.message || playErr}`, 'err');
            return;
        }

        // Verify actual non-black frames are arriving from the camera hardware
        const hasRealFrames = await this._verifyNonBlackFrames(video, 3000);
        if (!hasRealFrames) {
            await this.disconnect();
            this._setUiState(
                'Camera error',
                trackLabel,
                'No live frames received (black feed). Check if another app or a hardware privacy shutter is blocking the camera.',
                'err'
            );
            return;
        }

        // Preview is confirmed live!
        this._setUiState('Camera connected — waiting for analysis', trackLabel, null, 'ok');
        this._connectDetectionWebSocket(video, canvas, trackLabel);
    }

    _waitForVideoMetadata(video, timeoutMs) {
        return new Promise((resolve, reject) => {
            if (video.readyState >= 1 && video.videoWidth > 0 && video.videoHeight > 0) {
                resolve();
                return;
            }
            const timer = setTimeout(() => {
                cleanup();
                reject(new Error('Timed out waiting for camera video metadata.'));
            }, timeoutMs);

            const onMeta = () => {
                if (video.videoWidth > 0 && video.videoHeight > 0) {
                    cleanup();
                    resolve();
                }
            };
            const cleanup = () => {
                clearTimeout(timer);
                video.removeEventListener('loadedmetadata', onMeta);
                video.removeEventListener('loadeddata', onMeta);
            };
            video.addEventListener('loadedmetadata', onMeta);
            video.addEventListener('loadeddata', onMeta);
        });
    }

    _verifyNonBlackFrames(video, timeoutMs) {
        return new Promise((resolve) => {
            const start = Date.now();
            const probe = document.createElement('canvas');
            probe.width = 64;
            probe.height = 36;
            const pctx = probe.getContext('2d', { willReadFrequently: true });

            const check = () => {
                if (!this.webcamStream) {
                    resolve(false);
                    return;
                }
                if (video.readyState >= 2 && video.videoWidth > 0) {
                    pctx.drawImage(video, 0, 0, 64, 36);
                    const data = pctx.getImageData(0, 0, 64, 36).data;
                    let nonZero = 0;
                    for (let i = 0; i < data.length; i += 16) {
                        if (data[i] > 4 || data[i + 1] > 4 || data[i + 2] > 4) {
                            nonZero++;
                            if (nonZero >= 3) {
                                resolve(true);
                                return;
                            }
                        }
                    }
                }
                if (Date.now() - start >= timeoutMs) {
                    resolve(false);
                    return;
                }
                setTimeout(check, 150);
            };
            check();
        });
    }

    _connectDetectionWebSocket(video, canvas, trackLabel) {
        this._confirmedBackendProcessing = false;
        this._inFlight = false;

        const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const wsUrl = `${proto}//${window.location.host}/ws/camera/webcam?label=${encodeURIComponent(trackLabel)}`;
        const ws = new WebSocket(wsUrl);
        this.webcamWs = ws;

        ws.onopen = () => {
            this._startWebcamFrameLoop(video, canvas);
        };

        ws.onmessage = (evt) => {
            this._inFlight = false;
            try {
                const msg = JSON.parse(evt.data);
                if (msg.error) {
                    this._setUiState('Camera connected — detection model unavailable', trackLabel, msg.error, 'warn');
                    return;
                }
                if (!this._confirmedBackendProcessing) {
                    this._confirmedBackendProcessing = true;
                    this._setUiState('Processing frames', trackLabel, null, 'ok');
                }
                this.latestBoxes = msg.boxes || [];
                this.lineYRatio = msg.line_y_ratio || 0.55;
                this._drawWebcamOverlay(video, canvas);
                this._updateAnalyticsCards(msg.analytics || {});
            } catch (e) { }
        };

        ws.onerror = () => {
            this._inFlight = false;
            this._setUiState('Camera connected — waiting for analysis', trackLabel, 'Backend detection WebSocket unavailable; live preview remains active.', 'warn');
        };

        ws.onclose = () => {
            this._inFlight = false;
            if (this.webcamFrameTimer) {
                clearInterval(this.webcamFrameTimer);
                this.webcamFrameTimer = null;
            }
        };
    }

    _startWebcamFrameLoop(video, canvas) {
        if (this.webcamFrameTimer) clearInterval(this.webcamFrameTimer);
        this.webcamFrameTimer = setInterval(() => {
            if (!this.webcamWs || this.webcamWs.readyState !== WebSocket.OPEN) return;
            if (this._inFlight) return; // Never send faster than backend processes
            if (video.readyState < 2 || !video.videoWidth || !video.videoHeight) return;

            const w = Math.min(640, video.videoWidth);
            const h = Math.round((w / video.videoWidth) * video.videoHeight);
            this.offscreenCanvas.width = w;
            this.offscreenCanvas.height = h;
            const octx = this.offscreenCanvas.getContext('2d');
            octx.drawImage(video, 0, 0, w, h);

            this._inFlight = true;
            this.offscreenCanvas.toBlob(
                (blob) => {
                    if (blob && this.webcamWs && this.webcamWs.readyState === WebSocket.OPEN) {
                        this.webcamWs.send(blob);
                    } else {
                        this._inFlight = false;
                    }
                },
                'image/jpeg',
                0.75
            );
        }, 90);
    }

    _drawWebcamOverlay(video, canvas) {
        const rect = video.getBoundingClientRect();
        canvas.width = Math.max(1, Math.floor(rect.width));
        canvas.height = Math.max(1, Math.floor(rect.height));
        const ctx = canvas.getContext('2d');
        ctx.clearRect(0, 0, canvas.width, canvas.height);

        const w = canvas.width;
        const h = canvas.height;
        const lineY = h * this.lineYRatio;

        ctx.strokeStyle = '#0284c7';
        ctx.lineWidth = 2;
        ctx.beginPath();
        ctx.moveTo(0, lineY);
        ctx.lineTo(w, lineY);
        ctx.stroke();

        const classColors = { Car: '#0284c7', Bus: '#16a34a', Truck: '#dc2626', Motorcycle: '#d97706' };
        for (const b of this.latestBoxes) {
            const x1 = b.nx1 * w;
            const y1 = b.ny1 * h;
            const bw = (b.nx2 - b.nx1) * w;
            const bh = (b.ny2 - b.ny1) * h;
            const col = classColors[b.class] || '#0284c7';

            ctx.strokeStyle = col;
            ctx.lineWidth = 2;
            ctx.strokeRect(x1, y1, bw, bh);

            const label = `#${b.id} ${b.class} ${Math.round((b.confidence || 0) * 100)}%`;
            ctx.font = '600 11px Inter, sans-serif';
            const tw = ctx.measureText(label).width + 8;
            ctx.fillStyle = col;
            ctx.fillRect(x1, Math.max(0, y1 - 18), tw, 18);
            ctx.fillStyle = '#ffffff';
            ctx.fillText(label, x1 + 4, Math.max(12, y1 - 5));
        }
    }

    _handleWebcamError(err, label) {
        let msg = 'Unable to connect to the selected camera. Check the camera permissions or device connection.';
        if (err.name === 'NotAllowedError' || err.name === 'PermissionDeniedError') {
            msg = 'Camera permission denied. Allow camera access in your browser address bar and try again.';
        } else if (err.name === 'NotFoundError' || err.name === 'DevicesNotFoundError') {
            msg = 'Camera not found. Ensure your Integrated Camera or USB webcam is connected.';
        } else if (err.name === 'NotReadableError' || err.name === 'TrackStartError') {
            msg = 'Camera is already in use by another application (e.g. Zoom, Teams, or another browser tab).';
        }
        this._setUiState('Camera error', label, msg, 'err');
    }

    _stopWebcamHardwareOnly() {
        if (this.webcamFrameTimer) {
            clearInterval(this.webcamFrameTimer);
            this.webcamFrameTimer = null;
        }
        this._inFlight = false;
        this._confirmedBackendProcessing = false;
        if (this.webcamWs) {
            try { this.webcamWs.close(); } catch (e) { }
            this.webcamWs = null;
        }
        if (this.webcamStream) {
            this.webcamStream.getTracks().forEach((t) => t.stop());
            this.webcamStream = null;
        }
    }

    async disconnect() {
        this._stopWebcamHardwareOnly();

        const video = document.getElementById('cam-webcam-video');
        const canvas = document.getElementById('cam-overlay-canvas');
        const img = document.getElementById('cam-stream-img');
        if (video) {
            video.pause();
            video.srcObject = null;
            video.style.display = 'none';
        }
        if (canvas) {
            canvas.getContext('2d').clearRect(0, 0, canvas.width, canvas.height);
            canvas.style.display = 'none';
        }
        if (img) {
            img.removeAttribute('src');
            img.style.display = 'none';
        }

        const resp = await fetch('/api/camera/disconnect', { method: 'POST' });
        const data = await resp.json();
        this._renderBackendStatus(data);
    }

    async restart() {
        await this.connect();
    }

    async fetchStatus() {
        if (this.webcamStream) return;
        try {
            const resp = await fetch('/api/camera/status');
            const data = await resp.json();
            this._renderBackendStatus(data);
        } catch (e) { }
    }

    _setUiState(stateText, label, errorMsg, tone) {
        this.currentState = stateText;
        const badge = document.getElementById('cam-state-badge');
        const errBox = document.getElementById('cam-error-box');
        const srcBadge = document.getElementById('cam-source-badge');
        const viewport = document.getElementById('cam-viewport');
        const emptyMsg = document.getElementById('cam-empty-msg');

        if (badge) {
            badge.innerHTML = `<span class="dot"></span> ${stateText}`;
            badge.className = 'status-pill ' + (tone || '');
        }
        if (srcBadge) srcBadge.textContent = label || 'Disconnected';
        if (errBox) {
            errBox.style.display = errorMsg ? 'block' : 'none';
            errBox.textContent = errorMsg || '';
        }
        const isInactive = stateText === 'Disconnected' || stateText === 'Camera error' || stateText === 'DISCONNECTED' || stateText === 'ERROR';
        if (viewport && isInactive) {
            viewport.classList.remove('live-active');
        }
        if (emptyMsg && (isInactive || stateText === 'Requesting permission' || (stateText === 'Connecting' && !this.webcamStream))) {
            emptyMsg.style.display = 'block';
            emptyMsg.textContent =
                stateText === 'Requesting permission' ? 'Requesting browser camera permission...' :
                    stateText === 'Connecting' ? 'Connecting to selected camera source...' :
                        (stateText === 'Camera error' || stateText === 'ERROR') ? (errorMsg || 'Unable to connect to the selected camera.') :
                            'Connect a local webcam, RTSP/IP camera stream, or explicitly choose the Demo Video test source to begin vehicle detection.';
        }
    }

    _renderBackendStatus(data) {
        const raw = data.state || 'DISCONNECTED';
        const stateMap = {
            DISCONNECTED: ['Disconnected', ''],
            CONNECTING: ['Connecting', 'warn'],
            CONNECTED: ['Camera connected', 'ok'],
            PROCESSING: ['Processing frames', 'ok'],
            RECONNECTING: ['Connecting', 'warn'],
            ERROR: ['Camera error', 'err'],
        };
        const [labelText, tone] = stateMap[raw] || [raw, ''];
        this._setUiState(labelText, data.source_label || 'Disconnected', data.error, tone);
        this._updateProvenance(data.provenance || {}, raw);

        const img = document.getElementById('cam-stream-img');
        const viewport = document.getElementById('cam-viewport');
        const emptyMsg = document.getElementById('cam-empty-msg');

        if (raw === 'CONNECTED' || raw === 'PROCESSING') {
            if (img && img.style.display === 'none') {
                img.src = `/api/camera/stream?t=${Date.now()}`;
                img.style.display = 'block';
            }
            if (viewport) viewport.classList.add('live-active');
            if (emptyMsg) emptyMsg.style.display = 'none';
        } else {
            if (img) {
                if (img.getAttribute('src')) img.removeAttribute('src');
                img.style.display = 'none';
            }
        }
        this._updateAnalyticsCards(data.analytics || {});
    }

    _updateProvenance(p, rawState) {
        const badge = document.getElementById('cam-live-status-badge');
        if (badge) {
            badge.textContent = rawState === 'ERROR' ? 'Source unavailable' : (p.live_status_label || 'Disconnected');
        }
        document.getElementById('prov-cam-name').textContent = p.camera_name || '—';
        document.getElementById('prov-cam-loc').textContent = p.camera_location || '—';
        document.getElementById('prov-cam-provider').textContent = p.provider || '—';
        document.getElementById('prov-cam-type').textContent = p.stream_type || '—';
        document.getElementById('prov-cam-last').textContent = p.last_frame_time || '—';

        const tsRow = document.getElementById('prov-ts-row');
        if (p.provider_timestamp) {
            tsRow.style.display = 'block';
            document.getElementById('prov-cam-ts').textContent = p.provider_timestamp;
        } else {
            tsRow.style.display = 'none';
        }

        const linkRow = document.getElementById('prov-link-row');
        const linkEl = document.getElementById('prov-cam-link');
        if (p.source_webpage) {
            linkRow.style.display = 'block';
            linkEl.href = p.source_webpage;
        } else {
            linkRow.style.display = 'none';
        }
    }

    _updateAnalyticsCards(a) {
        document.getElementById('cam-active-cnt').textContent = a.active_detected ?? 0;
        document.getElementById('cam-crossed-cnt').textContent = a.total_crossed ?? 0;
        document.getElementById('cam-density').textContent = a.density_level || 'NONE';
        document.getElementById('cam-fps').textContent = (a.fps ?? 0).toFixed(1);
        document.getElementById('cam-dir-cnt').textContent = `${a.inbound_count ?? 0} / ${a.outbound_count ?? 0}`;
        const lc = a.lane_counts || { Left: 0, Center: 0, Right: 0 };
        document.getElementById('cam-lane-cnt').textContent = `${lc.Left} / ${lc.Center} / ${lc.Right}`;
        const cc = a.class_counts || { Car: 0, Bus: 0, Truck: 0, Motorcycle: 0 };
        document.getElementById('cam-cls-cnt').textContent = `${cc.Car} / ${cc.Bus} / ${cc.Truck} / ${cc.Motorcycle}`;
    }

    async applyToSumo() {
        const approach = document.getElementById('cam-bridge-approach').value;
        const msgEl = document.getElementById('cam-bridge-msg');
        const fd = new FormData();
        fd.append('source', 'camera');
        fd.append('approach', approach);
        const resp = await fetch('/api/simulation/apply_real_traffic', { method: 'POST', body: fd });
        const data = await resp.json();
        if (msgEl) msgEl.textContent = data.message || data.status;
    }
}

window.CameraViewController = CameraViewController;
