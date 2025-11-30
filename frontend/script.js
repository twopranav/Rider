const BASE_URL = "http://127.0.0.1:8000";
const WS_BASE = "ws://127.0.0.1:8000";

let riderWs = null;
let driverWs = null;

// --- UTILS ---
function log(elementId, msg, type="normal") {
    const box = document.getElementById(elementId);
    const div = document.createElement("div");
    div.className = `log-entry ${type}`;
    div.innerText = `[${new Date().toLocaleTimeString()}] ${msg}`;
    box.prepend(div);
}

// --- REGISTRATION HELPERS (REST) ---
async function registerClient() {
    const id = document.getElementById('riderId').value;
    try {
        await fetch(`${BASE_URL}/clients/register`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name: `Rider ${id}`, email: `rider${id}@test.com` })
        });
        alert(`Rider ${id} registered (or already exists).`);
    } catch (e) { console.error(e); }
}

async function registerDriver() {
    const id = document.getElementById('driverId').value;
    try {
        await fetch(`${BASE_URL}/drivers/register`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name: `Driver ${id}`, email: `driver${id}@test.com`, current_zone: 1 })
        });
        alert(`Driver ${id} registered (or already exists).`);
    } catch (e) { console.error(e); }
}

// --- RIDER WEBSOCKET ---
function connectRider() {
    const id = document.getElementById('riderId').value;
    if(riderWs) riderWs.close();

    riderWs = new WebSocket(`${WS_BASE}/ws/rider/${id}`);

    riderWs.onopen = () => {
        document.getElementById('btnConnRider').innerText = "Connected";
        document.getElementById('btnConnRider').style.backgroundColor = "#28a745";
        log('riderLog', `Rider ${id} connected.`, 'success');
    };

    riderWs.onmessage = (event) => {
        const data = JSON.parse(event.data);
        if (data.type === 'info') log('riderLog', data.message, 'info');
        if (data.type === 'driver_assigned') log('riderLog', `DRIVER FOUND: ${data.driver_name} (Arrives in ${data.arrival_time_minutes} min)`, 'success');
        if (data.type === 'ride_completed') log('riderLog', `RIDE COMPLETE: ${data.message}`, 'success');
    };

    riderWs.onclose = () => {
        log('riderLog', 'Disconnected', 'error');
        document.getElementById('btnConnRider').innerText = "Connect WS";
        document.getElementById('btnConnRider').style.backgroundColor = "#6c757d";
    };
}

function requestRide() {
    if(!riderWs) return alert("Connect Rider WS first");
    const start = parseInt(document.getElementById('startZone').value);
    const drop = parseInt(document.getElementById('dropZone').value);

    riderWs.send(JSON.stringify({
        action: "request_ride",
        start_zone: start,
        drop_zone: drop
    }));
    log('riderLog', `Requesting ride ${start} -> ${drop}...`);
}

// --- DRIVER WEBSOCKET ---
function connectDriver() {
    const id = document.getElementById('driverId').value;
    if(driverWs) driverWs.close();

    driverWs = new WebSocket(`${WS_BASE}/ws/driver/${id}`);

    driverWs.onopen = () => {
        document.getElementById('btnConnDriver').innerText = "Connected";
        document.getElementById('btnConnDriver').style.backgroundColor = "#28a745";
        log('driverLog', `Driver ${id} connected.`, 'success');
    };

    driverWs.onmessage = (event) => {
        const data = JSON.parse(event.data);
        
        if (data.type === 'new_ride') {
            const vipText = data.is_priority ? " [VIP PRIORITY]" : "";
            const msg = `🔔 NEW RIDE AVAILABLE! ID: ${data.ride_id} (${data.start_zone} -> ${data.drop_zone})${vipText}`;
            log('driverLog', msg, data.is_priority ? 'vip' : 'info');
            // Auto-fill the input for easier testing
            document.getElementById('targetRideId').value = data.ride_id;
        }
        else if (data.type === 'ride_taken') {
            log('driverLog', `Ride ${data.ride_id} taken by Driver ${data.accepted_by_driver_id}`, 'error');
        }
        else if (data.type === 'info') {
            log('driverLog', data.message);
        }
    };
}

function acceptRide() {
    if(!driverWs) return alert("Connect Driver WS first");
    const rideId = document.getElementById('targetRideId').value;
    driverWs.send(JSON.stringify({ action: "accept_ride", ride_id: parseInt(rideId) }));
    log('driverLog', `Attempting to accept Normal Ride ${rideId}...`);
}

function acceptPooled() {
    if(!driverWs) return alert("Connect Driver WS first");
    const rideId = document.getElementById('targetRideId').value;
    driverWs.send(JSON.stringify({ action: "accept_pooled", pooled_id: parseInt(rideId) }));
    log('driverLog', `Attempting to accept Pooled Ride ${rideId}...`);
}

function completeRide() {
    if(!driverWs) return alert("Connect Driver WS first");
    const rideId = document.getElementById('targetRideId').value;
    driverWs.send(JSON.stringify({ action: "complete_ride", ride_id: parseInt(rideId) }));
    log('driverLog', `Completing ride ${rideId}...`);
}

// --- QUEUE POLLING ---
async function updateQueue() {
    try {
        const response = await fetch(`${BASE_URL}/rides/queue`);
        const data = await response.json();
        
        const tbody = document.getElementById('queueTableBody');
        tbody.innerHTML = ''; // Clear old data

        if (data.unified_queue.length === 0) {
            tbody.innerHTML = '<tr><td colspan="4" style="text-align:center">No active requests</td></tr>';
            return;
        }

        data.unified_queue.forEach(item => {
            const row = document.createElement('tr');
            if (item.is_vip) row.className = 'vip-row';
            
            row.innerHTML = `
                <td>${item.queue_position}</td>
                <td>${item.ride_id}</td>
                <td>${item.is_vip ? '⭐ YES' : 'No'}</td>
                <td>${item.route}</td>
            `;
            tbody.appendChild(row);
        });
    } catch (e) {
        // console.error("Queue poll failed", e); // Silence errors when server is off
    }
}

// Poll every 2 seconds
setInterval(updateQueue, 2000);