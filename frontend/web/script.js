const form = document.getElementById('attendance-form');
const resultDiv = document.getElementById('result');
const logoutBtn = document.getElementById('logout-btn');
const notificationContainer = document.getElementById('notification-container');

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
