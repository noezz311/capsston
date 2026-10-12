"use strict";
const settings = window.CAPSTONE;
const isControl = document.body.dataset.page === "control";
const statusUrl = isControl ? "/api/status" : settings.controlBaseUrl + "/api/status";
let pendingCommand = false;
const monitorLink = document.getElementById("monitorLink");
if (monitorLink) monitorLink.href = settings.monitorBaseUrl;

function setText(id, value) {
    const element = document.getElementById(id);
    if (element) element.textContent = value === undefined || value === null ? "UNKNOWN" : value;
}
function setStatusClass(id, value) {
    const element = document.getElementById(id);
    if (!element) return;
    setText(id, value);
    element.classList.remove("ok", "bad", "warn");
    if (value === "CONNECTED" || value === "ON") element.classList.add("ok");
    else if (value === "DISCONNECTED" || value === "OFF") element.classList.add("bad");
    else element.classList.add("warn");
}
function showStatus(data) {
    const stale = data.status_stale === true || data.stale === true;
    const available = data.ros_available !== false && data.hardware_ready !== false && !stale;
    const banner = document.getElementById("control_status");
    banner.textContent = available ? "Control service / ROS controller running" : "ROS controller unavailable or status stale";
    if (data.hardware_mode === "mock") banner.textContent += " (MOCK hardware)";
    banner.className = "status-main " + (available ? "ok" : "warn");
    ["relay", "direction_status", "door_ble", "direction_ble"].forEach(id => setStatusClass(id, available ? data[id] : "UNKNOWN (stale)"));
    // Until a future sensor reports explicit confirmation, never label a sent
    // OPEN/CLOSE command as an observed physical door position.
    const confirmed = data.door_confirmed === true;
    setStatusClass("door_status", available && confirmed ? data.door_status : "UNKNOWN / unconfirmed");
    setText("door_last_command", data.door_command || data.door_last_command || "NONE");
    setText("last_command", data.last_command);
    setText("detail", "Last Result : " + (data.last_result || "-") + "\n" +
        "Last Time   : " + (data.last_time || "-") + "\n" +
        "Server Time : " + (data.server_time || "-") + "\n" +
        "Logged In   : " + Boolean(data.logged_in) + "\n" +
        "Status stale: " + stale + "\n" +
        "Door delivery: " + (data.door_delivery || "UNKNOWN") + "\n" +
        "LED delivery : " + (data.direction_delivery || "UNKNOWN"));
}
function unavailable(message) {
    showStatus({ros_available: false, status_stale: true, last_result: message});
}
async function fetchJson(url, options = {}) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), settings.fetchTimeoutMs);
    try {
        const response = await fetch(url, {...options, signal: controller.signal, cache: "no-store"});
        const data = await response.json();
        return {response, data};
    } finally { clearTimeout(timer); }
}
async function sendCmd(cmd) {
    if (pendingCommand) return;
    pendingCommand = true;
    document.querySelectorAll("button[data-cmd]").forEach(button => button.disabled = true);
    setText("command_result", "Sending " + cmd + "...");
    try {
        const {response, data} = await fetchJson("/api/cmd", {
            method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({cmd})
        });
        if (data.status) showStatus(data.status);
        setText("command_result", data.message || JSON.stringify(data));
        if (response.status === 401) window.location.assign(settings.monitorBaseUrl + "/login");
    } catch (error) {
        setText("command_result", "Command response unavailable; outcome unknown. Check status before retrying.");
        unavailable("Command response unavailable");
    } finally {
        pendingCommand = false;
        document.querySelectorAll("button[data-cmd]").forEach(button => button.disabled = false);
    }
}
async function loadStatus() {
    try {
        const {response, data} = await fetchJson(statusUrl);
        if (!response.ok) throw new Error("Status request failed");
        showStatus(data);
    } catch (error) { unavailable("Cannot reach control service / ROS status"); }
    // Schedule after completion to prevent accumulated overlapping requests.
    setTimeout(loadStatus, settings.pollIntervalMs);
}
if (isControl) {
    document.querySelectorAll("button[data-cmd]").forEach(button => button.addEventListener("click", () => sendCmd(button.dataset.cmd)));
    document.addEventListener("keydown", event => {
        if (event.repeat || event.target.matches("input, textarea, button")) return;
        const cmd = {ArrowLeft: "left", ArrowRight: "right", " ": "stop"}[event.key];
        if (cmd) {event.preventDefault(); sendCmd(cmd);}
    });
}
loadStatus();
