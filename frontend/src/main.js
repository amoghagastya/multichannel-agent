import { Device } from "@twilio/voice-sdk";

let device;
let activeCall;
let initializing = false;

const statusEl = document.getElementById("status");
const logEl = document.getElementById("log");
const callBtn = document.getElementById("callBtn");
const hangupBtn = document.getElementById("hangupBtn");

function log(msg) {
  statusEl.textContent = msg;
  const line = document.createElement("div");
  line.textContent = msg;
  logEl.prepend(line);
  console.log("[DealSmart] " + msg);
}

window.addEventListener("error", (e) => {
  log("Window error: " + (e.message || e.type));
});

async function initDevice() {
  if (initializing) return false;
  initializing = true;
  try {
    await navigator.mediaDevices.getUserMedia({ audio: true });
  } catch (err) {
    log("Mic permission denied");
    initializing = false;
    return false;
  }

  const resp = await fetch("/token");
  if (!resp.ok) {
    log("Token error: " + (await resp.text()));
    initializing = false;
    return false;
  }
  const data = await resp.json();
  log(`Token OK (len=${data.token?.length || "na"}), initializing device...`);

  device = new Device(data.token, { debug: true });
  device.on("registered", () => log("Registered (for inbound)"));
  device.on("registering", () => log("Registering device..."));
  device.on("error", (err) => log("Error: " + err.message));
  device.on("connect", () => log("Call connected"));
  device.on("disconnect", () => log("Call disconnected"));

  log("Device initialized");
  initializing = false;
  return true;
}

callBtn.onclick = async () => {
  log("Call button clicked");
  if (!device) {
    const ok = await initDevice();
    if (!ok || !device) {
      log("Device not ready");
      return;
    }
  }
  log("Calling...");
  try {
    activeCall = await device.connect({ params: { To: "agent" } });
    activeCall.on("error", (err) => log("Call error: " + err.message));
    activeCall.on("accept", () => log("Call accepted"));
  } catch (err) {
    log("Connect failed: " + (err && err.message ? err.message : String(err)));
    return;
  }
  hangupBtn.disabled = false;
  callBtn.disabled = true;
  activeCall.on("disconnect", () => {
    log("Call ended");
    callBtn.disabled = false;
    hangupBtn.disabled = true;
  });
};

hangupBtn.onclick = () => {
  if (activeCall) activeCall.disconnect();
};
