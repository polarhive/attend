// DOM Elements
const form = document.getElementById('attendance-form');
const resultDiv = document.getElementById('result');
const logoutBtn = document.getElementById('logout-btn');
const notificationContainer = document.getElementById('notification-container');
const srnInput = document.getElementById('srn');
const submitButton = document.querySelector('#attendance-form button[type="submit"]');

// Constants and Configuration
const MAX_RECONNECT_ATTEMPTS = 3;
const SRN_REGEX = /^PES(1UG23(CS|AM)|1UG24(CS|AM|BT|ME|EC)|2UG23(CS|AM|EC)|2UG24(CS|AM|EC))\d{3}$/;

// Global State
let socket = null;
let pingInterval = null;
let reconnectAttempts = 0;

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
`;
document.body.appendChild(loadingContainer);

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
    // Create notification
    const notif = document.createElement('div');
    notif.className = 'notification';
    notif.style.backgroundColor = (type === 'error') ? 'var(--danger-color)' : 'var(--primary-color)';
    notif.textContent = message;
    notificationContainer.appendChild(notif);
    setTimeout(() => notif.remove(), 3000);

    const logEntry = document.createElement('div');
    logEntry.className = 'log-entry';
    logEntry.textContent = message;
    logEntry.style.color = (type === 'error') ? 'var(--danger-color)' : 'var(--primary-color)';
    logsContainer.appendChild(logEntry);
    logsSummary.textContent = `Show Logs (${logsContainer.childElementCount})`;
}

// Clear the logs container
function clearLogs() {
    logsContainer.innerHTML = '';
    logsSummary.textContent = 'Show Logs';
    logsDropdown.open = false;
}

// Display attendance data
function displayAttendance(data) {
    if (!data || !data.attendance || data.attendance.length === 0) {
        resultDiv.innerHTML = "<p>No attendance data available.</p>";
        return;
    }

    let tableHTML = `
        <h2>Attendance Graph</h2>
        <img src="data:image/png;base64,${data.graph}" alt="Attendance Graph" />
        <div class="table-container">
            <table>
                <thead>
                    <tr>
                        <th>Subject</th>
                        <th>Attended</th>
                        <th>Total</th>
                        <th>Percentage</th>
                        <th>Bunkable</th>
                    </tr>
                </thead>
                <tbody>
    `;

    data.attendance.forEach(item => {
        tableHTML += `
            <tr>
                <td>${item.subject}</td>
                <td>${item.attended}</td>
                <td>${item.total}</td>
                <td>${item.percentage}%</td>
                <td>${item.bunkable}</td>
            </tr>
        `;
    });

    tableHTML += `</tbody></table></div>`;
    resultDiv.innerHTML = tableHTML;
}

// Update UI based on login state
function updateUIForLoggedInState() {
    const isLoggedIn = Auth.isLoggedIn();
    form.style.display = isLoggedIn ? 'none' : 'block';
    logoutBtn.style.display = isLoggedIn ? 'block' : 'none';

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
    },

    isLoggedIn: () => {
        return Boolean(Auth.credentials.srn && Auth.credentials.password);
    },

    authenticate: (socket) => {
        if (!Auth.isLoggedIn()) {
            logMessage("No credentials available for authentication", "error");
            return false;
        }

        // Send authentication if socket is open
        if (socket && socket.readyState === WebSocket.OPEN) {
            socket.send(JSON.stringify({
                type: "auth",
                data: {
                    srn: Auth.credentials.srn,
                    password: Auth.credentials.password
                }
            }));
            return true;
        }
        return false;
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

// Setup WebSocket connection
function setupWebSocket() {
    // Close existing connection if any
    if (socket) {
        clearInterval(pingInterval);
        if (socket.readyState === WebSocket.OPEN) {
            socket.close();
        }
    }

    // Determine WebSocket URL
    const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsBase = window.location.host;
    const wsUrl = `${wsProtocol}//${wsBase}/api/ws/attendance`;

    // Create new WebSocket connection
    socket = new WebSocket(wsUrl);

    socket.onopen = handleSocketOpen;
    socket.onmessage = handleSocketMessage;
    socket.onclose = handleSocketClose;
    socket.onerror = handleSocketError;

    return socket;
}

// WebSocket event handlers
function handleSocketOpen() {
    logMessage("WebSocket connection established", "info");
    reconnectAttempts = 0;

    // Authenticate if credentials exist
    if (Auth.isLoggedIn()) {
        // Small delay to ensure the server is ready
        setTimeout(() => Auth.authenticate(socket), 100);
    }

    // Setup ping interval to keep connection alive
    pingInterval = setInterval(() => {
        if (socket.readyState === WebSocket.OPEN) {
            socket.send(JSON.stringify({ type: "ping" }));
        }
    }, 1000);
}

function handleSocketMessage(event) {
    const data = JSON.parse(event.data);

    switch (data.type) {
        case "auth_success":
            logsDropdown.open = false;
            break;

        case "log":
            setTimeout(() => {
                const logEntry = document.createElement('div');
                logEntry.className = 'log-entry server-log';
                logEntry.textContent = data.data;
                logsContainer.appendChild(logEntry);

                logsSummary.textContent = `Show Logs (${logsContainer.childElementCount})`;

                // Check if this is the final log message
                if (data.data.includes("Logged out successfully")) {
                    logMessage("Process complete, closing connection", "info");
                    // Close the WebSocket connection after a short delay
                    setTimeout(() => {
                        if (socket && socket.readyState === WebSocket.OPEN) {
                            socket.close();
                        }
                    }, 500);
                }
            }, 10);
            break;

        case "result":
            const resultData = data.data;
            if (resultData.status === "complete") {
                displayAttendance(resultData);
                setLoadingState(false);
                updateUIForLoggedInState();
            }
            break;

        case "error":
            logMessage(`Error: ${data.data}`, "error");
            setLoadingState(false);
            break;

        case "ping":
        case "pong":
            break;

        default:
            console.log("Unknown message type:", data.type);
    }
}

function handleSocketClose(event) {
    clearInterval(pingInterval);

    if (!event.wasClean && reconnectAttempts < MAX_RECONNECT_ATTEMPTS) {
        // Try to reconnect
        reconnectAttempts++;
        logMessage(`Connection lost. Reconnecting (${reconnectAttempts}/${MAX_RECONNECT_ATTEMPTS})...`, "error");
        setTimeout(() => setupWebSocket(), 2000);
    } else if (!event.wasClean) {
        logMessage("Connection lost. Please refresh the page to reconnect.", "error");
        setLoadingState(false);
    }
}

function handleSocketError(error) {
    logMessage("WebSocket error. Please check your connection.", "error");
    setLoadingState(false);
}

// Handle form submission
async function fetchAttendance(srn, password) {
    try {
        clearLogs();
        setLoadingState(true);

        // Validate SRN before sending
        if (!validateSRN(srn)) {
            logMessage("Invalid SRN format", "error");
            setLoadingState(false);
            return;
        }

        // Save credentials
        Auth.save(srn, password);
        setupWebSocket();
        updateUIForLoggedInState();

    } catch (error) {
        logMessage(`Error: ${error.message}`, "error");
        setLoadingState(false);
    }
}

// Handle logout
function logout() {
    if (socket && socket.readyState === WebSocket.OPEN) {
        socket.close();
    }
    Auth.clear();
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

    // Save credentials and clean URL
    Auth.save(srn, password);
    cleanUrlParameters();

    clearLogs();
    setLoadingState(true);
    updateUIForLoggedInState();
    setupWebSocket();
});

// SRN input validation
srnInput.addEventListener('input', checkSRNValidity);

// Logout button
logoutBtn.addEventListener('click', logout);

// Initialize on page load
window.addEventListener('load', () => {
    cleanUrlParameters();

    if (Auth.loadFromCookies()) {
        updateUIForLoggedInState();
        setLoadingState(true);
        setupWebSocket();
    } else {
        updateUIForLoggedInState();
        setupWebSocket();
    }
});

// Handle navigation events
window.addEventListener('popstate', () => {
    updateUIForLoggedInState();
});
