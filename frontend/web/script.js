// This script builds the DOM structure and contains the main application logic for the Attend web app.

// Version check for cache busting
async function checkVersion() {
    try {
        const response = await fetch(`/sw.js?v=${Date.now()}`, { cache: 'no-cache' });
        const text = await response.text();
        const match = text.match(/const CACHE_NAME = 'attendance-tracker-' \+ '([^']+)';/);
        if (match) {
            const currentVersion = match[1];
            const storedVersion = Cookies.get('app_version');
            if (storedVersion !== currentVersion) {
                // Prefer a non-modal in-page notification instead of alert.
                const hadCookies = Boolean(Cookies.get('srn') || Cookies.get('password') || Cookies.get('batch_id'));
                if (hadCookies) {
                    showNotification('App updated! Logging out.', 'info', 3500);
                    // Clear all cookies to ensure we start fresh
                    Cookies.deleteAll();
                } else {
                    showNotification('App updated! Refreshing.', 'info', 2500);
                }
                logEvent('sw.update_available', {}, 'info');
                // Remember new version and reload after a short delay so notification is visible
                Cookies.set('app_version', currentVersion, 365);
                setTimeout(() => window.location.reload(), 600);
            }
        }
    } catch (e) {
        console.warn('Version check failed:', e);
    }
}

function buildStaticDOM() {
    // Background gradients
    const bg1 = document.createElement('div');
    bg1.className = 'bg-gradient';
    const bg2 = document.createElement('div');
    bg2.className = 'bg-gradient-2';
    document.body.appendChild(bg1);
    document.body.appendChild(bg2);

    // Navbar
    const nav = document.createElement('nav');
    nav.className = 'navbar';

    const titleWrap = document.createElement('div');
    const h1 = document.createElement('h1');
    h1.id = 'navbar-title';
    h1.textContent = 'Attend';
    titleWrap.appendChild(h1);

    const controls = document.createElement('div');
    controls.className = 'navbar-controls';

    const githubLink = document.createElement('a');
    githubLink.id = 'github-link';
    githubLink.href = 'https://github.com/polarhive/attend';
    githubLink.target = '_blank';
    githubLink.rel = 'noopener noreferrer';
    githubLink.className = 'icon-btn';
    githubLink.style.display = 'inline-flex';
    githubLink.setAttribute('aria-label', 'GitHub');
    githubLink.innerHTML = `<svg viewBox="0 0 24 24" fill="white"><path d="M12 0c-6.626 0-12 5.373-12 12 0 5.302 3.438 9.8 8.207 11.387.599.111.793-.261.793-.577v-2.234c-3.338.726-4.033-1.416-4.033-1.416-.546-1.387-1.333-1.756-1.333-1.756-1.089-.745.083-.729.083-.729 1.205.084 1.839 1.237 1.839 1.237 1.07 1.834 2.807 1.304 3.492.997.107-.775.418-1.305.762-1.604-2.665-.305-5.467-1.334-5.467-5.931 0-1.311.469-2.381 1.236-3.221-.124-.303-.535-1.524.117-3.176 0 0 1.008-.322 3.301 1.23.957-.266 1.983-.399 3.003-.404 1.02.005 2.047.138 3.006.404 2.291-1.552 3.297-1.23 3.297-1.23.653 1.653.242 2.874.118 3.176.77.84 1.235 1.911 1.235 3.221 0 4.609-2.807 5.624-5.479 5.921.43.372.823 1.102.823 2.222v3.293c0 .319.192.694.801.576 4.765-1.589 8.199-6.086 8.199-11.386 0-6.627-5.373-12-12-12z"/></svg>`;

    const navbarThreshold = document.createElement('div');
    navbarThreshold.id = 'navbar-threshold';
    navbarThreshold.className = 'threshold-control';
    navbarThreshold.style.display = 'none';
    navbarThreshold.innerHTML = `
        <label for="threshold-slider">
            <span class="threshold-label">Min:</span>
            <span id="threshold-display" class="threshold-value">75%</span>
        </label>
        <input type="range" id="threshold-slider" min="50" max="100" value="75" step="1">
    `;

    const logoutBtn = document.createElement('button');
    logoutBtn.id = 'logout-btn';
    logoutBtn.className = 'btn-secondary';
    logoutBtn.style.display = 'none';
    logoutBtn.innerHTML = `<svg viewBox="0 0 22 22" fill="none" stroke="currentColor" stroke-width="2"><path d="M9 21H5a2 2 0 01-2-2V5a2 2 0 012-2h4M16 17l5-5-5-5M21 12H9"/></svg>`;

    controls.appendChild(githubLink);
    controls.appendChild(navbarThreshold);
    controls.appendChild(logoutBtn);

    nav.appendChild(titleWrap);
    nav.appendChild(controls);
    document.body.appendChild(nav);

    // Notification container
    const notif = document.createElement('div');
    notif.id = 'notification-container';
    document.body.appendChild(notif);

    // Main content container
    const main = document.createElement('main');
    main.className = 'container';

    // How-it-works info box
    const how = document.createElement('div');
    how.id = 'how-it-works';
    how.className = 'info-box';
    how.setAttribute('role', 'region');
    how.innerHTML = `<div class="info-bar-text"><span>Credentials stored locally on your browser. No SRN or personal data logged. Checkout the code on GitHub.</span></div>`;

    // Form wrapper and form (IDs used by app logic)
    const formWrapper = document.createElement('div');
    formWrapper.className = 'form-wrapper';

    const form = document.createElement('form');
    form.id = 'attendance-form';
    form.className = 'glass-card';

    form.innerHTML = `
        <div class="form-header"><h2>Sign In</h2></div>
        <div class="form-group">
            <label for="srn">SRN</label>
            <input type="text" id="srn" name="srn" required placeholder="PES2UG23CS123" autocomplete="username" />
        </div>
        <div class="form-group">
            <label for="password">Password</label>
            <input type="password" id="password" name="password" required placeholder="••••••••" autocomplete="current-password" />
        </div>
        <div class="form-group" id="semester-group" style="display: none;">
            <label for="semester">Semester</label>
            <div class="select-wrap">
                <select id="semester" name="semester">
                    <option value="">Select Semester (optional)</option>
                </select>
            </div>
        </div>
        <button type="submit" class="btn-primary"><span>Get Attendance</span></button>
    `;

    formWrapper.appendChild(form);
    main.appendChild(how);
    main.appendChild(formWrapper);

    // Skeleton loader
    const skeleton = document.createElement('div');
    skeleton.id = 'skeleton-loader';
    skeleton.style.display = 'none';
    skeleton.innerHTML = `<div class="skeleton skeleton-chart"></div><div class="skeleton skeleton-table"></div>`;
    main.appendChild(skeleton);

    // Result container
    const result = document.createElement('div');
    result.className = 'result';
    result.id = 'result';
    main.appendChild(result);

    document.body.appendChild(main);
}

// Build the DOM immediately
buildStaticDOM();
checkVersion();

// DOM Elements (now available)
const form = document.getElementById('attendance-form');
const resultDiv = document.getElementById('result');
const logoutBtn = document.getElementById('logout-btn');
const notificationContainer = document.getElementById('notification-container');

// Small helper to show non-modal in-app notifications
function showNotification(message, type = 'info', timeout = 3000) {
    try {
        const notif = document.createElement('div');
        notif.className = 'notification' + (type === 'error' ? ' notification-error' : '');
        notif.textContent = message;
        if (notificationContainer) {
            notificationContainer.appendChild(notif);
            setTimeout(() => notif.remove(), timeout);
        } else {
            // Fallback to console if notifications area not present
            console.info(message);
        }
    } catch (e) {
        console.warn('Failed to show notification:', e);
    }
}

const srnInput = document.getElementById('srn');
const submitButton = document.querySelector('#attendance-form button[type="submit"]');
const submitLabel = submitButton.querySelector('span') || submitButton;
let submitInSemesterMode = false; // true when label changed to 'Submit' after semester fetch

// Ensure we have a stable base label to restore to later
if (submitLabel && !submitLabel.dataset.base) submitLabel.dataset.base = submitLabel.textContent;
else if (!submitLabel && !submitButton.dataset.base) submitButton.dataset.base = submitButton.innerText;

// Accessible live status for screen readers
const statusLive = document.createElement('div');
statusLive.id = 'status-live';
statusLive.setAttribute('role', 'status');
statusLive.setAttribute('aria-live', 'polite');
statusLive.style.position = 'absolute';
statusLive.style.left = '-9999px';
document.body.appendChild(statusLive);

function setSubmitState(isWaiting, message, options = {}) {
    if (isWaiting) {
        submitButton.disabled = true;
        submitButton.classList.add('loading');
        if (submitLabel) {
            if (!submitLabel.dataset.orig) submitLabel.dataset.orig = submitLabel.textContent;
            submitLabel.textContent = message || 'Waiting for response...';
        } else {
            if (!submitButton.dataset.orig) submitButton.dataset.orig = submitButton.innerText;
            submitButton.innerText = message || 'Waiting for response...';
        }
        statusLive.textContent = message || 'Waiting for response...';
    } else {
        // If skipRestore is true we should not restore dataset.orig (used after semester fetch)
        submitButton.disabled = false;
        submitButton.classList.remove('loading');
        if (options.skipRestore) {
            // keep whatever label is currently set (e.g., 'Submit')
        } else {
            // If there is an orig (from the last loading), restore it. Otherwise restore base label if needed.
            if (submitLabel && submitLabel.dataset.orig) {
                submitLabel.textContent = submitLabel.dataset.orig;
                delete submitLabel.dataset.orig;
            } else if (submitButton.dataset.orig) {
                submitButton.innerText = submitButton.dataset.orig;
                delete submitButton.dataset.orig;
            } else {
                // If no orig, but we have been in semester mode and not cleared, keep 'Submit'
                if (submitInSemesterMode) {
                    // keep as-is
                } else {
                    // restore base label if present
                    if (submitLabel && submitLabel.dataset.base) submitLabel.textContent = submitLabel.dataset.base;
                    else if (submitButton.dataset.base) submitButton.innerText = submitButton.dataset.base;
                }
            }
        }
        statusLive.textContent = '';
    }
}

function setSubmitToSubmitMode() {
    submitInSemesterMode = true;
    if (submitLabel) {
        if (!submitLabel.dataset.base) submitLabel.dataset.base = submitLabel.textContent;
        submitLabel.textContent = 'Submit';
    } else {
        if (!submitButton.dataset.base) submitButton.dataset.base = submitButton.innerText;
        submitButton.innerText = 'Submit';
    }
}

function clearSubmitMode() {
    submitInSemesterMode = false;
    if (submitLabel && submitLabel.dataset.base) {
        submitLabel.textContent = submitLabel.dataset.base;
        delete submitLabel.dataset.base;
    } else if (submitButton.dataset.base) {
        submitButton.innerText = submitButton.dataset.base;
        delete submitButton.dataset.base;
    }
}

// --- Begin copied app logic (adapted from original script.js) ---

// Constants and Configuration
let SRN_REGEX = /^PES[12](?:UG|PG)\d{2}[A-Z]{2}\d{3}$/;

// Global State
let isProcessing = false;
let currentAttendanceData = null;
let isOffline = false;
let availableSemesters = null;
// Track whether stage-2 loader has already been shown to avoid duplicates
let stage2Shown = false;

// Create loading animation container with skeleton
const loadingContainer = document.createElement('div');
loadingContainer.className = 'loading-container';
loadingContainer.innerHTML = `
    <div class="loading-text">Fetching your attendance data...</div>
    <div class="loading-dots">
        <div class="loading-dot"></div>
        <div class="loading-dot"></div>
        <div class="loading-dot"></div>
        <div class="loading-dot"></div>
        <div class="loading-dot"></div>
    </div>
    <div class="skeleton-loader" style="margin-top: 2rem;">
        <div class="skeleton-chart-container">
            <div class="skeleton-bar"></div>
            <div class="skeleton-bar"></div>
            <div class="skeleton-bar"></div>
            <div class="skeleton-bar"></div>
            <div class="skeleton-bar"></div>
        </div>
    </div>
    <div class="loading-logs" id="loading-logs"></div>
`;
// Loader will be inserted into the DOM when needed (see ensureLoaderInserted)

// Create offline indicator
const offlineIndicator = document.createElement('div');
offlineIndicator.className = 'offline-indicator';
offlineIndicator.textContent = 'Offline';
document.body.appendChild(offlineIndicator);

const logsDropdown = document.createElement('details');
logsDropdown.id = 'logs-dropdown';
logsDropdown.className = 'logs-dropdown';

const logsSummary = document.createElement('summary');
logsSummary.textContent = 'Show Logs';
logsSummary.className = 'logs-summary';

const logsContainer = document.createElement('div');
logsContainer.id = 'logs-container';
logsContainer.className = 'logs-container';

logsDropdown.appendChild(logsSummary);
logsDropdown.appendChild(logsContainer);
document.body.appendChild(logsDropdown);

// --- Loader stage helpers (we keep the loader element but insert it when needed) ---
function fadeOutElement(el, ms = 300) {
    return new Promise(resolve => {
        if (!el) return resolve();
        el.style.transition = `opacity ${ms}ms ease`;
        el.style.opacity = '1';
        // trigger layout
        void el.offsetWidth;
        el.style.opacity = '0';
        setTimeout(() => {
            el.style.display = 'none';
            resolve();
        }, ms);
    });
}

function fadeInElement(el, ms = 300, display = 'block') {
    return new Promise(resolve => {
        if (!el) return resolve();
        el.style.display = display;
        el.style.opacity = '0';
        el.style.transition = `opacity ${ms}ms ease`;
        // trigger layout
        void el.offsetWidth;
        el.style.opacity = '1';
        setTimeout(() => resolve(), ms);
    });
}

function ensureLoaderInserted() {
    const nav = document.querySelector('.navbar');
    if (!nav) return;
    if (!loadingContainer.parentNode || loadingContainer.parentNode !== nav.parentNode) {
        // insert directly after navbar to avoid gaps
        nav.parentNode.insertBefore(loadingContainer, nav.nextSibling);
        // small gap to visually match the chart/card top gap
        loadingContainer.style.marginTop = '12px';
        loadingContainer.style.display = 'none';
        loadingContainer.style.width = '100%';
    }
}

async function showStage2Loader() {
    ensureLoaderInserted();
    if (stage2Shown) return;
    stage2Shown = true;
    // hide any result area while loading
    const result = document.getElementById('result');
    if (result) result.style.display = 'none';
    await fadeInElement(loadingContainer, 240, 'block');
}

async function showStage3Result() {
    // fade loader out and reveal result area
    await fadeOutElement(loadingContainer, 200);
    stage2Shown = false;
    const result = document.getElementById('result');
    if (result) {
        // show instantly without animation
        result.style.transition = 'none';
        result.style.display = 'block';
        result.style.opacity = '1';
    }
}

async function showOfflineBanner() {
    try {
        logsDropdown.open = true;
    } catch (e) {
        offlineIndicator.style.display = 'block';
    }
}

async function hideOfflineBanner() {
    try {
        logsDropdown.open = false;
    } catch (e) {
        offlineIndicator.style.display = 'none';
    }
}

function setLoadingState(isLoading) {
    document.body.classList.toggle('loading', isLoading);
}

// Semantic log keys and templates used across frontend and backend.
// Keep human-readable templates and a stable event key prefix so logs are machine-parseable.
const LOG_TEMPLATES = {
    'fetch.in_progress': 'Request already in progress',
    'network.offline_fetch_blocked': 'You are offline. Cannot fetch new attendance data.',
    'fetch.start': 'Initiating attendance fetch for ${srn}',
    'auth.validating': 'Validating credentials...',
    'academy.connecting': 'Connecting to PESU Academy...',
    'fetch.server_responded': 'Server responded in ${duration}',
    'fetch.parsing': 'Parsing attendance data...',
    'mapping.redirect': 'Redirecting to add mappings...',
    'fetch.found_subjects': 'Found ${count} subjects',
    'ui.rendering': 'Rendering attendance visualization...',
    'mapping.auto_discovered': 'Auto-discovered batch IDs; redirecting to GitHub issue for mapping addition.',
    'fetch.complete': 'All done! Attendance loaded successfully',
    'error.generic': 'Error: ${error}',
    'validation.invalid_srn': 'Invalid SRN format',
    'semester.auto_selected': 'Semester auto-selected, submit to get attendance',
    'semester.fetch_error': 'Error fetching semesters: ${error}',
    'sw.update_available': 'App updated! Refresh to get the latest version.',
    'sw.registration_failed': 'ServiceWorker registration failed',
    'network.online': 'Back online! You can fetch new attendance data.',
    'network.offline': 'You are offline. App will work with cached data.',
};

function renderLogTemplate(key, params = {}) {
    const template = LOG_TEMPLATES[key] || key;
    return template.replace(/\$\{(\w+)\}/g, (m, p1) => params[p1] !== undefined ? params[p1] : '');
}

// Log event with a stable key and optional params. This produces messages like:
// "[fetch.start] Initiating attendance fetch for PES2UG23..."
function logEvent(key, params = {}, type = 'info') {
    const text = renderLogTemplate(key, params);
    logMessage(`[${key}] ${text}`, type);
}

function logMessage(message, type = 'info') {
    if (type === 'error') {
        const notif = document.createElement('div');
        notif.className = 'notification';
        notif.textContent = message;
        notificationContainer.appendChild(notif);
        setTimeout(() => notif.remove(), 3000);
    }

    const timestamp = new Date().toLocaleTimeString('en-US', {
        hour12: false,
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit'
    });

    const logEntry = document.createElement('div');
    logEntry.className = 'log-entry';

    const timeSpan = document.createElement('span');
    timeSpan.style.color = 'var(--text-tertiary)';
    timeSpan.style.marginRight = '0.5rem';
    timeSpan.textContent = `[${timestamp}]`;

    const messageSpan = document.createElement('span');
    messageSpan.style.color = (type === 'error') ? 'var(--danger)' : 'var(--text-secondary)';
    messageSpan.textContent = message;

    logEntry.appendChild(timeSpan);
    logEntry.appendChild(messageSpan);
    logsContainer.appendChild(logEntry);
    logsSummary.textContent = `Show Logs (${logsContainer.childElementCount})`;

    const loadingLogs = document.getElementById('loading-logs');
    if (loadingLogs && document.body.classList.contains('loading')) {
        const loadingLogEntry = document.createElement('div');
        loadingLogEntry.className = 'loading-log-entry';
        loadingLogEntry.innerHTML = `<span style="color: var(--text-tertiary); margin-right: 0.5rem;">[${timestamp}]</span><span style="color: ${type === 'error' ? 'var(--danger)' : 'var(--text-secondary)'}">${message}</span>`;
        loadingLogs.appendChild(loadingLogEntry);
        loadingLogs.scrollTop = loadingLogs.scrollHeight;
    }
}

function clearLogs() {
    logsContainer.innerHTML = '';
    logsSummary.textContent = 'Show Logs';
    logsDropdown.open = false;
}



function generateAttendanceChart(attendanceData, customThreshold = null) {
    const ctx = document.getElementById('attendanceChart').getContext('2d');
    if (window.attendanceChart instanceof Chart) {
        window.attendanceChart.destroy();
    }
    const subjects = attendanceData.map(item => item.subject);
    const attendedData = attendanceData.map(item => item.attended);
    const skippedData = attendanceData.map(item => item.skipped);
    const totalData = attendanceData.map(item => item.total);
    const threshold = customThreshold !== null ? customThreshold : (attendanceData[0]?.threshold || 75);
    const thresholdData = totalData.map(total => Math.ceil((threshold / 100) * total));
    window.attendanceChart = new Chart(ctx, {
        type: 'bar',
        data: {
            labels: subjects.map((subject, index) =>
                `${subject}\n${attendedData[index]}/${attendedData[index] + skippedData[index]}`
            ),
            datasets: [
                { label: 'Attended', data: attendedData, backgroundColor: 'rgb(34, 197, 94)', borderColor: 'rgb(34, 197, 94)', borderWidth: 0 },
                { label: 'Skipped', data: skippedData, backgroundColor: 'rgb(239, 68, 68)', borderColor: 'rgb(239, 68, 68)', borderWidth: 0 },
                { label: `${threshold}% Threshold`, data: thresholdData, type: 'line', backgroundColor: 'rgba(250, 204, 21, 0.2)', borderColor: 'rgb(250, 204, 21)', borderWidth: 3, fill: false, pointRadius: 5, pointHoverRadius: 7, pointBackgroundColor: 'rgb(250, 204, 21)', pointBorderColor: 'rgb(250, 204, 21)', tension: 0 }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: { title: { display: false }, legend: { display: true, position: 'bottom', align: 'center', labels: { color: '#ffffff', padding: 12, font: { size: 13, weight: '500' }, usePointStyle: true, boxWidth: 12 } } },
            scales: { x: { stacked: true, ticks: { color: '#a1a1aa', font: { size: 11 } }, grid: { color: 'rgba(255, 255, 255, 0.05)', drawBorder: false } }, y: { stacked: true, beginAtZero: true, ticks: { color: '#a1a1aa', font: { size: 11 } }, grid: { color: 'rgba(255, 255, 255, 0.05)', drawBorder: false } } },
            interaction: { intersect: false, mode: 'index' }
        }
    });
}

function updateThreshold(newThreshold) {
    if (!currentAttendanceData) return;
    ThresholdManager.saveThreshold(newThreshold);
    const thresholdDisplay = document.getElementById('threshold-display');
    if (thresholdDisplay) {
        thresholdDisplay.textContent = `${newThreshold}%`;
    }
    generateAttendanceChart(currentAttendanceData, newThreshold);
    updateskippableValues(newThreshold);
}

function updateskippableValues(threshold) {
    const tableRows = document.querySelectorAll('#attendance-table tbody tr');
    tableRows.forEach((row, index) => {
        if (index < currentAttendanceData.length) {
            const item = currentAttendanceData[index];
            let newskippable;
            if (item.total === 0) {
                newskippable = 0;
            } else {
                const currentPercentage = (item.attended / item.total) * 100;
                if (currentPercentage >= threshold) {
                    newskippable = Math.floor((item.attended * 100 / threshold) - item.total);
                } else {
                    const needed = Math.ceil((threshold * item.total - 100 * item.attended) / (100 - threshold));
                    newskippable = -needed;
                }
            }
            const skippableCell = row.querySelector('.skippable-cell');
            if (skippableCell) {
                let skippableHtml;
                if (newskippable > 0) {
                    skippableHtml = `<span class="skippable-skip">✔ Skip ${newskippable}</span>`;
                } else if (newskippable < 0) {
                    const need = Math.abs(newskippable);
                    skippableHtml = `<span class="skippable-need">✘ Need ${need}</span>`;
                } else {
                    skippableHtml = '0';
                }
                skippableCell.innerHTML = skippableHtml;
            }
        }
    });
}

function parseAttendanceData(rawData) {
    if (!rawData || !rawData.attendance) {
        return rawData;
    }

    const threshold = ThresholdManager.getThreshold();

    const parsedAttendance = rawData.attendance.map(item => {
        const attendanceParts = item.raw_data.split("/");
        if (attendanceParts.length !== 2) {
            console.warn(`Invalid attendance format: ${item.raw_data}`);
            return { subject: item.subject, attended: 0, total: 0, skipped: 0, percentage: 0, skippable: 0, threshold: threshold };
        }
        const attended = parseInt(attendanceParts[0]);
        const total = parseInt(attendanceParts[1]);
        const skipped = total - attended;
        const percentage = total > 0 ? Math.round((attended / total) * 100 * 100) / 100 : 0;
        let skippable;
        if (total === 0) {
            skippable = 0;
        } else {
            const currentPercentage = (attended / total) * 100;
            if (currentPercentage >= threshold) {
                skippable = Math.floor((attended * 100 / threshold) - total);
            } else {
                const needed = Math.ceil((threshold * total - 100 * attended) / (100 - threshold));
                skippable = -needed;
            }
        }

        return { subject: item.subject, attended: attended, total: total, skipped: skipped, percentage: percentage, skippable: skippable, threshold: threshold };
    });

    return { ...rawData, attendance: parsedAttendance };
}

function attachInputControlListeners() {
    document.querySelectorAll('.control-btn').forEach(btn => {
        btn.addEventListener('click', (e) => {
            const button = e.target;
            const type = button.dataset.type;
            const index = parseInt(button.dataset.index);
            const input = document.querySelector(`input[data-type="${type}"][data-index="${index}"]`);
            if (!input) return;
            let value = parseInt(input.value) || 0;
            if (button.classList.contains('increment')) { value++; }
            else if (button.classList.contains('decrement')) { value = Math.max(0, value - 1); }
            input.value = value;
            recalculateRow(index);
        });
    });
    document.querySelectorAll('.attendance-input').forEach(input => {
        input.addEventListener('input', (e) => { const index = parseInt(e.target.dataset.index); recalculateRow(index); });
        input.addEventListener('blur', (e) => { let value = parseInt(e.target.value); if (isNaN(value) || value < 0) { e.target.value = 0; recalculateRow(parseInt(e.target.dataset.index)); } });
    });
}

function recalculateRow(index) {
    const attendedInput = document.querySelector(`input[data-type="attended"][data-index="${index}"]`);
    const totalInput = document.querySelector(`input[data-type="total"][data-index="${index}"]`);
    if (!attendedInput || !totalInput) return;
    let attended = parseInt(attendedInput.value) || 0;
    let total = parseInt(totalInput.value) || 0;
    if (attended > total && total > 0) { attended = total; attendedInput.value = attended; }
    if (currentAttendanceData && currentAttendanceData[index]) { currentAttendanceData[index].attended = attended; currentAttendanceData[index].total = total; }
    const percentage = total > 0 ? Math.round((attended / total) * 100 * 100) / 100 : 0;
    const threshold = ThresholdManager.getThreshold();
    let skippable;
    if (total === 0) { skippable = 0; } else { const currentPercentage = (attended / total) * 100; if (currentPercentage >= threshold) { skippable = Math.floor((attended * 100 / threshold) - total); } else { const needed = Math.ceil((threshold * total - 100 * attended) / (100 - threshold)); skippable = -needed; } }
    const row = document.querySelector(`tr[data-row-index="${index}"]`);
    if (!row) return;
    const percentageCell = row.querySelector('.percentage-cell');
    const skippableCell = row.querySelector('.skippable-cell');
    if (percentageCell) { percentageCell.textContent = `${percentage}%`; }
    if (skippableCell) {
        let skippableHtml;
        if (skippable > 0) skippableHtml = `<span class="skippable-skip">✔ Skip ${skippable}</span>`;
        else if (skippable < 0) { const need = Math.abs(skippable); skippableHtml = `<span class="skippable-need">✘ Need ${need}</span>`; }
        else skippableHtml = '0';
        skippableCell.innerHTML = skippableHtml;
    }
    if (currentAttendanceData) { generateAttendanceChart(currentAttendanceData, threshold); }
}

function displayAttendance(data) {
    if (!data || !data.attendance || data.attendance.length === 0) { resultDiv.innerHTML = "<p>No attendance data available.</p>"; return; }
    const parsedData = parseAttendanceData(data);
    currentAttendanceData = parsedData.attendance;
    const initialThreshold = ThresholdManager.getThreshold();
    const navbarThreshold = document.getElementById('navbar-threshold');
    const thresholdSlider = document.getElementById('threshold-slider');
    const thresholdDisplay = document.getElementById('threshold-display');
    if (navbarThreshold && thresholdSlider && thresholdDisplay) { navbarThreshold.style.display = 'block'; thresholdSlider.value = initialThreshold; thresholdDisplay.textContent = `${initialThreshold}%`; }

    let html = `
        <div class="chart-container"><canvas id="attendanceChart" width="400" height="200"></canvas></div>
        <div class="table-container"><table id="attendance-table"><thead><tr><th>Subject</th><th>Attended</th><th>Total</th><th>Percent</th><th>Buffer</th></tr></thead><tbody>`;

    parsedData.attendance.forEach((item, index) => {
        let skippableHtml;
        if (item.skippable > 0) skippableHtml = `<span class="skippable-skip">✔ Skip ${item.skippable}</span>`;
        else if (item.skippable < 0) { const need = Math.abs(item.skippable); skippableHtml = `<span class="skippable-need">✘ Need ${need}</span>`; }
        else skippableHtml = '0';

        html += `
            <tr data-row-index="${index}">
                <td>${item.subject}</td>
                <td>
                    <div class="input-control">
                        <button class="control-btn decrement" data-type="attended" data-index="${index}" aria-label="Decrease attended count for ${item.subject}">−</button>
                        <input type="number" class="attendance-input" data-type="attended" data-index="${index}" value="${item.attended}" min="0" aria-label="Attended classes for ${item.subject}">
                        <button class="control-btn increment" data-type="attended" data-index="${index}" aria-label="Increase attended count for ${item.subject}">+</button>
                    </div>
                </td>
                <td>
                    <div class="input-control">
                        <button class="control-btn decrement" data-type="total" data-index="${index}" aria-label="Decrease total count for ${item.subject}">−</button>
                        <input type="number" class="attendance-input" data-type="total" data-index="${index}" value="${item.total}" min="0" aria-label="Total classes for ${item.subject}">
                        <button class="control-btn increment" data-type="total" data-index="${index}" aria-label="Increase total count for ${item.subject}">+</button>
                    </div>
                </td>
                <td class="percentage-cell">${item.percentage}%</td>
                <td class="skippable-cell">${skippableHtml}</td>
            </tr>
        `;
    });

    html += `</tbody></table></div>`;
    resultDiv.innerHTML = html;
    attachInputControlListeners();
    generateAttendanceChart(parsedData.attendance);
}

function handleThresholdChange(e) { updateThreshold(parseInt(e.target.value)); }

function updateUIForLoggedInState() {
    const isLoggedIn = Auth.isLoggedIn();
    const navbarThreshold = document.getElementById('navbar-threshold');
    form.style.display = isLoggedIn ? 'none' : 'block';
    logoutBtn.style.display = isLoggedIn ? 'block' : 'none';
    if (navbarThreshold) { navbarThreshold.style.display = isLoggedIn ? 'block' : 'none'; }
    const githubLink = document.getElementById('github-link');
    if (githubLink) { githubLink.style.display = isLoggedIn ? 'none' : 'inline-flex'; }
    const howBox = document.getElementById('how-it-works');
    if (howBox) { const hasSavedData = Cookies.get('srn') || Cookies.get('password') || Cookies.get('threshold'); howBox.style.display = (isLoggedIn || hasSavedData) ? 'none' : 'block'; }
    if (!isLoggedIn) { resultDiv.innerHTML = ''; }

    // If the form is hidden (no login fields visible) and we don't already have results
    try {
        const formEl = document.querySelector('.form-wrapper');
        const resultEmpty = !resultDiv || resultDiv.innerHTML.trim() === '';
        const formHidden = !formEl || getComputedStyle(formEl).display === 'none';
        if (formHidden && resultEmpty && !isProcessing && !stage2Shown) {
            // show loader immediately but don't await
            showStage2Loader().catch(() => { });
        }
    } catch (e) {
        // ignore any errors from computed style
    }
}

const Cookies = {
    set: (name, value, days) => { const date = new Date(); date.setTime(date.getTime() + (days * 24 * 60 * 60 * 1000)); document.cookie = `${name}=${value};expires=${date.toUTCString()};path=/`; },
    get: (name) => { const value = `; ${document.cookie}`; const parts = value.split(`; ${name}=`); if (parts.length === 2) return parts.pop().split(';').shift(); return null; },
    delete: (name) => { document.cookie = `${name}=; expires=Thu, 01 Jan 1970 00:00:00 UTC; path=/;`; },
    deleteAll: () => { const cookies = document.cookie.split(";"); for (let cookie of cookies) { const eqPos = cookie.indexOf("="); const name = eqPos > -1 ? cookie.substr(0, eqPos).trim() : cookie.trim(); if (name) { Cookies.delete(name); } } }
};

const ThresholdManager = { getThreshold: () => { const saved = Cookies.get('threshold'); return saved ? parseInt(saved) : 75; }, saveThreshold: (threshold) => { Cookies.set('threshold', threshold.toString(), 365); } };

const Auth = {
    credentials: { srn: null, password: null, batch_id: null },
    loadFromCookies: () => { const srn = Cookies.get('srn'); const password = Cookies.get('password'); const batch_id = Cookies.get('batch_id'); if (srn && password) { Auth.credentials.srn = srn; Auth.credentials.password = password; Auth.credentials.batch_id = batch_id; return true; } return false; },
    save: (srn, password, batch_id = null) => { Auth.credentials.srn = srn.toUpperCase(); Auth.credentials.password = password; Auth.credentials.batch_id = batch_id; Cookies.set('srn', srn.toUpperCase(), 365); Cookies.set('password', password, 365); if (batch_id) Cookies.set('batch_id', batch_id, 365); },
    clear: () => { Auth.credentials.srn = null; Auth.credentials.password = null; Auth.credentials.batch_id = null; Cookies.delete('srn'); Cookies.delete('password'); Cookies.delete('batch_id'); Cookies.delete('threshold'); },
    isLoggedIn: () => { return Boolean(Auth.credentials.srn && Auth.credentials.password); }
};

function validateSRN(srn) {
    return SRN_REGEX.test(srn.toUpperCase());
}

function checkSRNValidity() {
    const srn = srnInput.value.toUpperCase();
    const isValid = validateSRN(srn);
    if (srn && !isValid) {
        srnInput.classList.add('invalid');
        submitButton.disabled = true;
    } else {
        srnInput.classList.remove('invalid');
        submitButton.disabled = !srn || !document.getElementById('password').value;
    }
}

async function fetchAttendance(srn, password, batchId = null) {
    if (isProcessing) { logEvent('fetch.in_progress', {}, 'error'); return; }
    if (isOffline) { logEvent('network.offline_fetch_blocked', {}, 'error'); return; }
    try {
        // Ensure button shows fetch state
        setSubmitState(true, 'Fetching attendance...');

        clearLogs();
        setLoadingState(true);
        isProcessing = true;
        const loadingLogs = document.getElementById('loading-logs'); if (loadingLogs) { loadingLogs.innerHTML = ''; }

        logEvent('fetch.start', { srn }, 'info');
        logEvent('auth.validating', {}, 'info');
        logEvent('academy.connecting', {}, 'info');
        const requestStartTime = performance.now();

        const response = await fetch('/api/attendance', { method: 'POST', headers: { 'Content-Type': 'application/json', 'Cache-Control': 'no-cache, no-store, must-revalidate', 'Pragma': 'no-cache', 'Expires': '0' }, body: JSON.stringify({ username: srn, password: password, batch_id: batchId }) });

        if (!response.ok) { const errorData = await response.json(); const errorMessage = errorData.error?.details || errorData.message || `HTTP error! status: ${response.status}`; throw new Error(errorMessage); }

        const data = await response.json();
        if (!data.success) { throw new Error(data.error?.details || data.message || "Unknown error from server"); }
        const requestEndTime = performance.now();
        const requestDuration = requestEndTime - requestStartTime;
        let durationText; if (requestDuration >= 1000) durationText = `${(requestDuration / 1000).toFixed(1)} seconds`; else durationText = `${Math.round(requestDuration)}ms`;
        logEvent('fetch.server_responded', { duration: durationText }, 'info');
        logEvent('fetch.parsing', {}, 'info');

        // If server returns redirect, redirect instead of showing data
        if (data.data?.redirect) {
            logEvent('mapping.redirect', {}, 'info');
            window.location = data.data.redirect;
            return;
        }

        const attendanceData = { attendance: data.data.attendance || data.data };
        logEvent('fetch.found_subjects', { count: attendanceData.attendance.length }, 'info');
        Auth.save(srn, password);
        logEvent('ui.rendering', {}, 'info');
        displayAttendance(attendanceData);
        updateUIForLoggedInState();

        // If backend discovered batchClassId(s) at runtime, redirect to GitHub issue for mapping addition
        const suggestions = data.data?.suggestions || [];
        const discovered = data.data?.discovered_batch_ids || [];
        if (suggestions && suggestions.length > 0 && discovered.length > 0) {
            const prefix = srn.replace(/\d+$/, '');
            const title = encodeURIComponent(`feat: mappings for ${prefix}`);
            const body = encodeURIComponent(`## Description\nAdd mappings for ${prefix}.\n\n## Args\n- sem: ${prefix}\n- source: auto-discovered\n- target: [${discovered.join(', ')}]\n\n## Notes\nAny additional context here.`);
            const issueUrl = `https://github.com/polarhive/attend/issues/new?title=${title}&body=${body}`;
            logEvent('mapping.auto_discovered', {}, 'info');
            window.open(issueUrl, '_blank');
        }


        logEvent('fetch.complete', {}, 'info');
    } catch (error) {
        logEvent('error.generic', { error: error.message }, 'error');
        Auth.clear();
    } finally {
        setLoadingState(false);
        isProcessing = false;
        // Clear any semester mode so the button label returns to the base 'Get Attendance'
        clearSubmitMode();
        setSubmitState(false);
    }
}

function logout() { Auth.clear(); Cookies.deleteAll(); location.reload(); }

function cleanUrlParameters() { if (window.location.search) { const cleanUrl = window.location.protocol + "//" + window.location.host + window.location.pathname; window.history.replaceState({}, document.title, cleanUrl); } }

form.addEventListener('submit', async (e) => {
    e.preventDefault();
    setSubmitState(true, 'Waiting for response...');
    const srn = srnInput.value.toUpperCase();
    const password = document.getElementById('password').value;
    if (!validateSRN(srn)) { logEvent('validation.invalid_srn', {}, 'error'); setSubmitState(false); return; }
    cleanUrlParameters();

    const semesterSelect = document.getElementById('semester');
    const selectedBatchId = semesterSelect.value;

    if (!availableSemesters) {
        // First submit: fetch semesters
        try {
            setSubmitState(true, 'Fetching semesters...');
            const resp = await fetch('/api/semesters', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ username: srn, password: password })
            });
            if (!resp.ok) throw new Error(`Failed to fetch semesters: ${resp.status}`);
            const data = await resp.json();
            if (!data.success) throw new Error(data.error?.details || data.message);
            availableSemesters = data.data.semesters;
            // Populate dropdown
            semesterSelect.innerHTML = '<option value="">Select Semester</option>';
            for (const [id, name] of Object.entries(availableSemesters)) {
                const option = document.createElement('option');
                option.value = id;
                option.textContent = name;
                semesterSelect.appendChild(option);
            }
            // Auto-select the highest semester or saved one
            const savedBatchId = Auth.credentials.batch_id;
            if (savedBatchId && availableSemesters[savedBatchId]) {
                semesterSelect.value = savedBatchId;
            } else {
                const maxId = Math.max(...Object.keys(availableSemesters).map(Number));
                semesterSelect.value = maxId;
            }
            // Show semester group
            document.getElementById('semester-group').style.display = 'block';
            logEvent('semester.auto_selected', {}, 'info');

            // Change button label to 'Submit' so user knows to submit with selected semester
            try {
                setSubmitToSubmitMode();
            } catch (e) {
                // ignore any DOM exceptions
            }

            // restore button state (enabled) so user can pick/submit, but do not overwrite the new label
            setSubmitState(false, undefined, { skipRestore: true });
            return;
        } catch (error) {
            logEvent('semester.fetch_error', { error: error.message }, 'error');
            setSubmitState(false);
            return;
        }
    }

    // Stage 1 -> Stage 2: fade out login and show loader immediately below navbar
    const formWrapper = document.querySelector('.form-wrapper');
    await fadeOutElement(formWrapper, 220);
    await showStage2Loader();

    // Fetch and then reveal results
    await fetchAttendance(srn, password, selectedBatchId || null);
    // Save credentials including batch_id
    Auth.save(srn, password, selectedBatchId);
    await showStage3Result();
    setSubmitState(false);
});
srnInput.addEventListener('input', checkSRNValidity);
document.getElementById('password').addEventListener('input', checkSRNValidity);
logoutBtn.addEventListener('click', logout);

const thresholdSlider = document.getElementById('threshold-slider');
if (thresholdSlider) { thresholdSlider.addEventListener('input', handleThresholdChange); }

(function initializeApp() {
    const hasSavedCredentials = document.cookie.includes('srn=') && document.cookie.includes('password=');
    if (hasSavedCredentials) {
        setLoadingState(true);
        document.addEventListener('DOMContentLoaded', () => {
            const formWrapper = document.querySelector('.form-wrapper');
            const howBox = document.getElementById('how-it-works');
            if (formWrapper) formWrapper.style.display = 'none';
            if (howBox) howBox.style.display = 'none';
        });
    }

    window.addEventListener('load', async () => {
        cleanUrlParameters();
        if (hasSavedCredentials && Auth.loadFromCookies()) {
            // Auto-login flow: fade out the form, show loader, fetch, then show results
            updateUIForLoggedInState();
            const formWrapper = document.querySelector('.form-wrapper');
            try {
                if (formWrapper) await fadeOutElement(formWrapper, 200);
                await showStage2Loader();
                if (Auth.credentials.srn && Auth.credentials.password) {
                    await fetchAttendance(Auth.credentials.srn, Auth.credentials.password, Auth.credentials.batch_id);
                    await showStage3Result();
                }
            } catch (e) {
                // fallback to default UI if anything fails
                updateUIForLoggedInState();
            }
        } else {
            updateUIForLoggedInState();
            // If semester group is already visible (e.g., from saved cookies), keep the button in Submit mode
            try {
                const semGroup = document.getElementById('semester-group');
                if (semGroup && getComputedStyle(semGroup).display !== 'none') {
                    setSubmitToSubmitMode();
                }
            } catch (e) { /* ignore */ }
        }
    });
})();

window.addEventListener('popstate', () => { updateUIForLoggedInState(); });

if ('serviceWorker' in navigator) {
    window.addEventListener('load', function () {
        navigator.serviceWorker.register('/sw.js')
            .then(function (registration) {
                registration.addEventListener('updatefound', function () {
                    const newWorker = registration.installing;
                    newWorker.addEventListener('statechange', function () {
                        if (newWorker.state === 'installed' && navigator.serviceWorker.controller) {
                            logEvent('sw.update_available', {}, 'info');
                            try { showNotification(renderLogTemplate('sw.update_available'), 'info', 5000); } catch (e) { /* ignore */ }
                        }
                    });
                });
            })
            .catch(function (err) { logEvent('sw.registration_failed', {}, 'error'); });
    });
}

window.addEventListener('online', function () {
    isOffline = false;
    hideOfflineBanner();
    offlineIndicator.style.display = 'none';
    logEvent('network.online', {}, 'info');
});

window.addEventListener('offline', function () {
    isOffline = true;
    showOfflineBanner().catch(() => { });
    logEvent('network.offline', {}, 'info');
});

if (!navigator.onLine) { isOffline = true; showOfflineBanner().catch(() => { offlineIndicator.style.display = 'block'; }); }
