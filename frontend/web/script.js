const form = document.getElementById('attendance-form');
const resultDiv = document.getElementById('result');
const logoutBtn = document.getElementById('logout-btn');
const notificationContainer = document.getElementById('notification-container');
const srnInput = document.getElementById('srn');
const submitButton = document.querySelector('#attendance-form button[type="submit"]');

// SRN validation regex - matching the backend pattern
// Pattern validates:
// PES1UG23: Only CS and AM departments
// PES1UG24: CS, AM, BT, ME, EC departments
// PES2UG23: CS, AM, EC departments
// PES2UG24: CS, AM, EC departments
const SRN_REGEX = /^PES(1UG23(CS|AM)|1UG24(CS|AM|BT|ME|EC)|2UG23(CS|AM|EC)|2UG24(CS|AM|EC))\d{3}$/;

// Function to validate SRN format
function validateSRN(srn) {
    return SRN_REGEX.test(srn.toUpperCase());
}

// Function to check input and update UI
function checkSRNValidity() {
    const srn = srnInput.value.toUpperCase();
    
    // First check if the SRN matches the allowed format
    const isValid = validateSRN(srn);

    if (srn && !isValid) {
        srnInput.classList.add('invalid');
        submitButton.disabled = true;
        
        // Only show "SRN not in mapping" when user types full 13 characters
        if (srn.length === 13) {
            showLogNotification("SRN not in mapping: open a PR on GitHub", "error");
            setTimeout(() => {
                window.location.href = "https://github.com/polarhive/attend?tab=readme-ov-file#adding-your-branch";
            }, 2000);
        }
    } else {
        srnInput.classList.remove('invalid');
        submitButton.disabled = false;
    }
}

// Add event listener for input validation
srnInput.addEventListener('input', checkSRNValidity);

// Function to show a log notification at the top left
function showLogNotification(message, type = 'info') {
    const notif = document.createElement('div');
    notif.className = 'notification';
    notif.style.backgroundColor = (type === 'error') ? '#ff3b30' : '#007aff';
    notif.textContent = message;
    notificationContainer.appendChild(notif);
    setTimeout(() => notif.remove(), 2000);
}

// Display attendance data using backend response structure
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

// Cookie Utilities
function setCookie(name, value, days) {
    const date = new Date();
    date.setTime(date.getTime() + (days * 24 * 60 * 60 * 1000));
    document.cookie = `${name}=${value};expires=${date.toUTCString()};path=/`;
}

function getCookie(name) {
    const value = `; ${document.cookie}`;
    const parts = value.split(`; ${name}=`);
    if (parts.length === 2) return parts.pop().split(';').shift();
}

function deleteCookie(name) {
    document.cookie = `${name}=; expires=Thu, 01 Jan 1970 00:00:00 UTC; path=/;`;
}

function logout() {
    deleteCookie('srn');
    deleteCookie('password');
    location.reload();
}
logoutBtn.addEventListener('click', logout);

async function fetchAttendance(srn, password) {
    try {
        // Validate SRN before sending
        if (!validateSRN(srn)) {
            showLogNotification("Invalid SRN format", "error");
            return;
        }

        showLogNotification("Fetching attendance..", "info");
        srn = srn.toUpperCase();

        const response = await fetch('/api/attendance', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ srn, password })
        });

        if (!response.ok) throw new Error('Failed to fetch attendance');

        const data = await response.json();
        displayAttendance(data);

        setCookie('srn', srn, 7);
        setCookie('password', password, 7);
        form.style.display = 'none';
        logoutBtn.style.display = 'block';
    } catch (error) {
        showLogNotification(`Error: ${error.message}`, "error");
    }
}


form.addEventListener('submit', (e) => {
    e.preventDefault();
    const srn = document.getElementById('srn').value.toUpperCase();
    const password = document.getElementById('password').value;

    // One more validation check before submission
    if (!validateSRN(srn)) {
        showLogNotification("Invalid SRN format", "error");
        return;
    }

    fetchAttendance(srn, password);
});

window.addEventListener('load', () => {
    const savedSRN = getCookie('srn');
    const savedPassword = getCookie('password');

    if (savedSRN && savedPassword) {
        form.style.display = 'none';
        fetchAttendance(savedSRN, savedPassword);
        logoutBtn.style.display = 'block';
    } else {
        showLogNotification("No credentials found – please login", "error");
    }
});
