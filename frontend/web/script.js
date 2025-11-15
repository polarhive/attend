// DOM Elements
const form = document.getElementById('attendance-form');
const resultDiv = document.getElementById('result');
const logoutBtn = document.getElementById('logout-btn');
const notificationContainer = document.getElementById('notification-container');
const srnInput = document.getElementById('srn');
const submitButton = document.querySelector('#attendance-form button[type="submit"]');

// Constants and Configuration
const SRN_REGEX = /^PES(2UG23(CS|AM|EC)|2UG24(CS|AM|EC))\d{3}$/;

// Global State
let isProcessing = false;
let currentAttendanceData = null; // Store current data for threshold updates
let isOffline = false;

// Create loading animation container
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
    <div class="loading-logs" id="loading-logs"></div>
`;
document.body.appendChild(loadingContainer);

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

function setLoadingState(isLoading) {
    document.body.classList.toggle('loading', isLoading);
}
function logMessage(message, type = 'info') {
    // Create notification only for errors
    if (type === 'error') {
        const notif = document.createElement('div');
        notif.className = 'notification';
        notif.textContent = message;
        notificationContainer.appendChild(notif);
        setTimeout(() => notif.remove(), 3000);
    }

    // Add timestamp to log entry
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
    
    // Also display on loading screen if visible
    const loadingLogs = document.getElementById('loading-logs');
    if (loadingLogs && document.body.classList.contains('loading')) {
        const loadingLogEntry = document.createElement('div');
        loadingLogEntry.className = 'loading-log-entry';
        loadingLogEntry.innerHTML = `<span style="color: var(--text-tertiary); margin-right: 0.5rem;">[${timestamp}]</span><span style="color: ${type === 'error' ? 'var(--danger)' : 'var(--text-secondary)'}">${message}</span>`;
        loadingLogs.appendChild(loadingLogEntry);
        // Auto-scroll to bottom
        loadingLogs.scrollTop = loadingLogs.scrollHeight;
    }
}

// Clear the logs container
function clearLogs() {
    logsContainer.innerHTML = '';
    logsSummary.textContent = 'Show Logs';
    logsDropdown.open = false;
}

// Generate attendance chart using Chart.js
function generateAttendanceChart(attendanceData, customThreshold = null) {
    const ctx = document.getElementById('attendanceChart').getContext('2d');
    
    // Destroy existing chart if it exists
    if (window.attendanceChart instanceof Chart) {
        window.attendanceChart.destroy();
    }
    
    const subjects = attendanceData.map(item => item.subject);
    const attendedData = attendanceData.map(item => item.attended);
    const skippedData = attendanceData.map(item => item.skipped);
    const totalData = attendanceData.map(item => item.total);
    
    // Use custom threshold if provided, otherwise use the original threshold
    const threshold = customThreshold !== null ? customThreshold : (attendanceData[0]?.threshold || 75);
    
    // Recalculate threshold marks based on current threshold
    const thresholdData = totalData.map(total => Math.ceil((threshold / 100) * total));
    
    window.attendanceChart = new Chart(ctx, {
        type: 'bar',
        data: {
            labels: subjects.map((subject, index) => 
                `${subject}\n${attendedData[index]}/${attendedData[index] + skippedData[index]}`
            ),
            datasets: [
                {
                    label: 'Attended',
                    data: attendedData,
                    backgroundColor: 'rgb(34, 197, 94)',
                    borderColor: 'rgb(34, 197, 94)',
                    borderWidth: 0
                },
                {
                    label: 'Skipped',
                    data: skippedData,
                    backgroundColor: 'rgb(239, 68, 68)',
                    borderColor: 'rgb(239, 68, 68)',
                    borderWidth: 0
                },
                {
                    label: `${threshold}% Threshold`,
                    data: thresholdData,
                    type: 'line',
                    backgroundColor: 'rgba(250, 204, 21, 0.2)',
                    borderColor: 'rgb(250, 204, 21)',
                    borderWidth: 3,
                    fill: false,
                    pointRadius: 5,
                    pointHoverRadius: 7,
                    pointBackgroundColor: 'rgb(250, 204, 21)',
                    pointBorderColor: 'rgb(250, 204, 21)',
                    tension: 0
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                title: {
                    display: false
                },
                legend: {
                    display: true,
                    position: 'top',
                    labels: {
                        color: '#ffffff',
                        padding: 15,
                        font: {
                            size: 13,
                            weight: '500'
                        }
                    }
                }
            },
            scales: {
                x: {
                    stacked: true,
                    title: {
                        display: false,
                        text: 'Subjects',
                        color: '#a1a1aa',
                        font: {
                            size: 12,
                            weight: '500'
                        }
                    },
                    ticks: {
                        color: '#a1a1aa',
                        font: {
                            size: 11
                        }
                    },
                    grid: {
                        color: 'rgba(255, 255, 255, 0.05)',
                        drawBorder: false
                    }
                },
                y: {
                    stacked: true,
                    title: {
                        display: false,
                        text: 'Classes',
                        color: '#a1a1aa',
                        font: {
                            size: 12,
                            weight: '500'
                        }
                    },
                    beginAtZero: true,
                    ticks: {
                        color: '#a1a1aa',
                        font: {
                            size: 11
                        }
                    },
                    grid: {
                        color: 'rgba(255, 255, 255, 0.05)',
                        drawBorder: false
                    }
                }
            },
            interaction: {
                intersect: false,
                mode: 'index'
            }
        }
    });
}

// Update threshold and regenerate chart
function updateThreshold(newThreshold) {
    if (!currentAttendanceData) return;
    
    // Save the new threshold to cookies
    ThresholdManager.saveThreshold(newThreshold);
    
    // Update the threshold display
    const thresholdDisplay = document.getElementById('threshold-display');
    if (thresholdDisplay) {
        thresholdDisplay.textContent = `${newThreshold}%`;
    }
    
    // Regenerate chart with new threshold
    generateAttendanceChart(currentAttendanceData, newThreshold);
    
    // Update the table with recalculated skippable values
    updateskippableValues(newThreshold);
}

// Update skippable values in the table
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

// Parse raw attendance data and convert to expected format
function parseAttendanceData(rawData) {
    if (!rawData || !rawData.attendance) {
        return rawData;
    }

    const threshold = ThresholdManager.getThreshold(); // Use saved threshold
    
    const parsedAttendance = rawData.attendance.map(item => {
        const attendanceParts = item.raw_data.split("/");
        
        if (attendanceParts.length !== 2) {
            console.warn(`Invalid attendance format: ${item.raw_data}`);
            return {
                subject: item.subject,
                attended: 0,
                total: 0,
                skipped: 0,
                percentage: 0,
                skippable: 0,
                threshold: threshold
            };
        }

        const attended = parseInt(attendanceParts[0]);
        const total = parseInt(attendanceParts[1]);
        const skipped = total - attended;
        const percentage = total > 0 ? Math.round((attended / total) * 100 * 100) / 100 : 0;
        
        // Calculate skippable classes (max classes can skip while staying above threshold)
        // If negative, it shows how many classes need to be attended to reach threshold
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

        return {
            subject: item.subject,
            attended: attended,
            total: total,
            skipped: skipped,
            percentage: percentage,
            skippable: skippable,
            threshold: threshold
        };
    });

    return {
        ...rawData,
        attendance: parsedAttendance
    };
}

// Display attendance data
function displayAttendance(data) {
    if (!data || !data.attendance || data.attendance.length === 0) {
        resultDiv.innerHTML = "<p>No attendance data available.</p>";
        return;
    }

    // Parse raw data before processing
    const parsedData = parseAttendanceData(data);

    // Store data globally for threshold updates
    currentAttendanceData = parsedData.attendance;
    const initialThreshold = ThresholdManager.getThreshold(); // Get saved threshold

    // Show the navbar threshold control and set initial values
    const navbarThreshold = document.getElementById('navbar-threshold');
    const thresholdSlider = document.getElementById('threshold-slider');
    const thresholdDisplay = document.getElementById('threshold-display');
    
    if (navbarThreshold && thresholdSlider && thresholdDisplay) {
        navbarThreshold.style.display = 'block';
        thresholdSlider.value = initialThreshold;
        thresholdDisplay.textContent = `${initialThreshold}%`;
    }

    let html = `
        <div class="chart-container">
            <canvas id="attendanceChart" width="400" height="200"></canvas>
        </div>
        <div class="table-container">
            <table id="attendance-table">
                <thead>
                    <tr>
                        <th>Subject</th>
                        <th>Attended</th>
                        <th>Total</th>
                        <th>Percent</th>
                        <th>Buffer</th>
                    </tr>
                </thead>
                <tbody>
    `;

    parsedData.attendance.forEach(item => {
        // Render skippable cell with contextual badge
        let skippableHtml;
        if (item.skippable > 0) {
            skippableHtml = `<span class="skippable-skip">✔ Skip ${item.skippable}</span>`;
        } else if (item.skippable < 0) {
            const need = Math.abs(item.skippable);
            skippableHtml = `<span class="skippable-need">✘ Need ${need}</span>`;
        } else {
            skippableHtml = '0';
        }

        html += `
            <tr>
                <td>${item.subject}</td>
                <td>${item.attended}</td>
                <td>${item.total}</td>
                <td>${item.percentage}%</td>
                <td class="skippable-cell">${skippableHtml}</td>
            </tr>
        `;
    });

    html += `</tbody></table></div>`;
    resultDiv.innerHTML = html;
    
    // Generate the chart after the HTML is inserted
    generateAttendanceChart(parsedData.attendance);
}

// Threshold change handler function
function handleThresholdChange(e) {
    updateThreshold(parseInt(e.target.value));
}

// Update UI based on login state
function updateUIForLoggedInState() {
    const isLoggedIn = Auth.isLoggedIn();
    const navbarThreshold = document.getElementById('navbar-threshold');
    
    form.style.display = isLoggedIn ? 'none' : 'block';
    logoutBtn.style.display = isLoggedIn ? 'block' : 'none';
    
    // Show/hide threshold control based on login state
    if (navbarThreshold) {
        navbarThreshold.style.display = isLoggedIn ? 'block' : 'none';
    }
    const githubLink = document.getElementById('github-link');
    if (githubLink) {
        githubLink.style.display = isLoggedIn ? 'none' : 'inline-flex';
    }

    if (!isLoggedIn) {
        resultDiv.innerHTML = '';
    }
}

// Cookie management
const Cookies = {
    set: (name, value, days) => {
        const date = new Date();
        date.setTime(date.getTime() + (days * 24 * 60 * 60 * 1000));
        document.cookie = `${name}=${value};expires=${date.toUTCString()};path=/`;
    },

    get: (name) => {
        const value = `; ${document.cookie}`;
        const parts = value.split(`; ${name}=`);
        if (parts.length === 2) return parts.pop().split(';').shift();
        return null;
    },

    delete: (name) => {
        document.cookie = `${name}=; expires=Thu, 01 Jan 1970 00:00:00 UTC; path=/;`;
    },

    deleteAll: () => {
        // Get all cookies and delete them
        const cookies = document.cookie.split(";");
        for (let cookie of cookies) {
            const eqPos = cookie.indexOf("=");
            const name = eqPos > -1 ? cookie.substr(0, eqPos).trim() : cookie.trim();
            if (name) {
                Cookies.delete(name);
            }
        }
    }
};

const ThresholdManager = {
    getThreshold: () => {
        const saved = Cookies.get('threshold');
        return saved ? parseInt(saved) : 75;
    },

    saveThreshold: (threshold) => {
        Cookies.set('threshold', threshold.toString(), 365);
    }
};

// Authentication management
const Auth = {
    credentials: {
        srn: null,
        password: null
    },

    loadFromCookies: () => {
        const srn = Cookies.get('srn');
        const password = Cookies.get('password');

        if (srn && password) {
            Auth.credentials.srn = srn;
            Auth.credentials.password = password;
            return true;
        }
        return false;
    },

    save: (srn, password) => {
        // Store in memory
        Auth.credentials.srn = srn.toUpperCase();
        Auth.credentials.password = password;

        // Store in cookies
        Cookies.set('srn', srn.toUpperCase(), 365);
        Cookies.set('password', password, 365);
    },

    clear: () => {
        Auth.credentials.srn = null;
        Auth.credentials.password = null;
        Cookies.delete('srn');
        Cookies.delete('password');
        Cookies.delete('threshold');
    },

    isLoggedIn: () => {
        return Boolean(Auth.credentials.srn && Auth.credentials.password);
    }
};

// Validate SRN format
function validateSRN(srn) {
    return SRN_REGEX.test(srn.toUpperCase());
}

// Check SRN validity and update UI
function checkSRNValidity() {
    const srn = srnInput.value.toUpperCase();
    const isValid = validateSRN(srn);

    if (srn && !isValid) {
        srnInput.classList.add('invalid');
        submitButton.disabled = true;

        // Show message when user types full 13 characters
        if (srn.length === 13) {
            logMessage("SRN not in mapping: open a PR on GitHub", "error");
            setTimeout(() => {
                window.location.href = "https://github.com/polarhive/attend?tab=readme-ov-file#adding-your-branch";
            }, 2000);
        }
    } else {
        srnInput.classList.remove('invalid');
        submitButton.disabled = false;
    }
}

// Handle form submission
async function fetchAttendance(srn, password) {
    if (isProcessing) {
        logMessage("Request already in progress", "error");
        return;
    }

    // Check if offline
    if (isOffline) {
        logMessage("You are offline. Cannot fetch new attendance data.", "error");
        return;
    }

    try {
        clearLogs();
        setLoadingState(true);
        isProcessing = true;
        
        // Clear loading logs
        const loadingLogs = document.getElementById('loading-logs');
        if (loadingLogs) {
            loadingLogs.innerHTML = '';
        }

        // Validate SRN before sending
        if (!validateSRN(srn)) {
            logMessage("Invalid SRN format", "error");
            setLoadingState(false);
            isProcessing = false;
            return;
        }

        logMessage(`Initiating attendance fetch for ${srn}`, "info");
        logMessage("Validating credentials...", "info");
        logMessage("Connecting to PESU Academy...", "info");

        // Start timing the request
        const requestStartTime = performance.now();

        // Make HTTP request to the attendance endpoint
        const response = await fetch('/api/attendance', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Cache-Control': 'no-cache, no-store, must-revalidate',
                'Pragma': 'no-cache',
                'Expires': '0'
            },
            body: JSON.stringify({
                username: srn,
                password: password
            })
        });

        if (!response.ok) {
            const errorData = await response.json();
            const errorMessage = errorData.error?.details || errorData.message || `HTTP error! status: ${response.status}`;
            throw new Error(errorMessage);
        }

        const data = await response.json();
        
        if (!data.success) {
            throw new Error(data.error?.details || data.message || "Unknown error from server");
        }
        
        // Calculate request duration
        const requestEndTime = performance.now();
        const requestDuration = requestEndTime - requestStartTime;
        
        // Format duration for display
        let durationText;
        if (requestDuration >= 1000) {
            durationText = `${(requestDuration / 1000).toFixed(1)} seconds`;
        } else {
            durationText = `${Math.round(requestDuration)}ms`;
        }
        
        logMessage(`✓ Server responded in ${durationText}`, "info");
        logMessage(`✓ Parsing attendance data...`, "info");
        
        const attendanceData = {
            attendance: data.data.attendance || data.data
        };
        
        logMessage(`✓ Found ${attendanceData.attendance.length} subjects`, "info");
        
        // Save credentials and display results
        Auth.save(srn, password);
        logMessage(`✓ Rendering attendance visualization...`, "info");
        displayAttendance(attendanceData);
        updateUIForLoggedInState();
        logMessage(`✓ All done! Attendance loaded successfully`, "info");

    } catch (error) {
        logMessage(`Error: ${error.message}`, "error");
        Auth.clear();
    } finally {
        setLoadingState(false);
        isProcessing = false;
    }
}

// Handle logout
function logout() {
    Auth.clear();
    Cookies.deleteAll(); // Clear all cookies
    location.reload();
}

// Clean URL parameters
function cleanUrlParameters() {
    if (window.location.search) {
        const cleanUrl = window.location.protocol + "//" + window.location.host + window.location.pathname;
        window.history.replaceState({}, document.title, cleanUrl);
    }
}

// Form submission
form.addEventListener('submit', (e) => {
    e.preventDefault();
    const srn = srnInput.value.toUpperCase();
    const password = document.getElementById('password').value;

    if (!validateSRN(srn)) {
        logMessage("Invalid SRN format", "error");
        return;
    }

    // Clean URL parameters
    cleanUrlParameters();
    
    // Fetch attendance data
    fetchAttendance(srn, password);
});

// SRN input validation
srnInput.addEventListener('input', checkSRNValidity);

// Logout button
logoutBtn.addEventListener('click', logout);

// Threshold slider (global listener)
const thresholdSlider = document.getElementById('threshold-slider');
if (thresholdSlider) {
    thresholdSlider.addEventListener('input', handleThresholdChange);
}

// Initialize on page load
window.addEventListener('load', () => {
    cleanUrlParameters();

    if (Auth.loadFromCookies()) {
        updateUIForLoggedInState();
        // Auto-fetch attendance if user was previously logged in
        if (Auth.credentials.srn && Auth.credentials.password) {
            fetchAttendance(Auth.credentials.srn, Auth.credentials.password);
        }
    } else {
        updateUIForLoggedInState();
    }
});

// Handle navigation events
window.addEventListener('popstate', () => {
    updateUIForLoggedInState();
});

// Service Worker Registration for offline caching
if ('serviceWorker' in navigator) {
    window.addEventListener('load', function() {
        navigator.serviceWorker.register('/sw.js')
            .then(function(registration) {
                // Check for service worker updates
                registration.addEventListener('updatefound', function() {
                    const newWorker = registration.installing;
                    newWorker.addEventListener('statechange', function() {
                        if (newWorker.state === 'installed' && navigator.serviceWorker.controller) {
                            // New service worker is available, show update notification
                            logMessage('App updated! Refresh to get the latest version.', 'info');
                        }
                    });
                });
            })
            .catch(function(err) {
                logMessage('ServiceWorker registration failed', 'error');
            });
    });
}

// Online/Offline status monitoring
window.addEventListener('online', function() {
    isOffline = false;
    offlineIndicator.classList.remove('show');
    logMessage('Back online! You can fetch new attendance data.', 'info');
});

window.addEventListener('offline', function() {
    isOffline = true;
    offlineIndicator.classList.add('show');
    logMessage('You are offline. App will work with cached data.', 'info');
});

// Check initial online status
if (!navigator.onLine) {
    isOffline = true;
    offlineIndicator.classList.add('show');
}
