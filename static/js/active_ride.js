/**
 * active_ride.js — MET Ride 2
 * Handles the active ride page for both driver and passenger roles.
 *
 * Globals injected by active_ride.html:
 *   AR_RIDE_ID     string
 *   AR_IS_DRIVER   bool
 *   AR_IS_PASSENGER bool
 *   AR_OTP_VERIFIED bool
 *   window.MET     {userId, name, ...}
 *   socket         (Socket.IO, from chat.js loaded in base.html → extra_scripts order)
 */

"use strict";

/* ── Constants ──────────────────────────────────────────────────────────────── */
const RIDE_ID       = window.AR_RIDE_ID;
const IS_DRIVER     = window.AR_IS_DRIVER;
const IS_PASSENGER  = window.AR_IS_PASSENGER;
const POLL_INTERVAL = 4000; // ms — passenger polls for location

/* ── Map ────────────────────────────────────────────────────────────────────── */
let arMap         = null;
let driverMarker  = null;
let myMarker      = null;
let locationPollId= null;
let driverWatchId = null;

function initMap() {
  const mapEl = document.getElementById("ar-map");
  if (!mapEl) return;

  arMap = L.map("ar-map", {
    center:      [19.0760, 72.8777],
    zoom:        14,
    zoomControl: true,
  });

  L.tileLayer("https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png", {
    attribution: "© CARTO",
    maxZoom:     19,
  }).addTo(arMap);
}

function makeIcon(color, label) {
  return L.divIcon({
    className: "",
    html: `<div style="
      background:${color};border-radius:50% 50% 50% 0;
      width:28px;height:28px;transform:rotate(-45deg);
      box-shadow:0 0 8px ${color}88;
      display:flex;align-items:center;justify-content:center;">
      <span style="transform:rotate(45deg);font-size:14px;">${label}</span>
    </div>`,
    iconSize:    [28, 28],
    iconAnchor:  [14, 28],
    popupAnchor: [0, -32],
  });
}

function setDriverMarker(lat, lng) {
  if (!arMap) return;
  const latlng = [lat, lng];
  if (driverMarker) {
    driverMarker.setLatLng(latlng);
  } else {
    driverMarker = L.marker(latlng, { icon: makeIcon("#4f8ef7", "🚗") })
      .addTo(arMap)
      .bindPopup("<strong>Driver</strong>");
  }
  arMap.panTo(latlng, { animate: true, duration: 0.6 });
  document.getElementById("map-last-update").textContent = "Updated just now";
}

function setMyMarker(lat, lng) {
  if (!arMap) return;
  const latlng = [lat, lng];
  if (myMarker) {
    myMarker.setLatLng(latlng);
  } else {
    myMarker = L.marker(latlng, { icon: makeIcon("#22c55e", "📍") })
      .addTo(arMap)
      .bindPopup("<strong>Your Location</strong>");
  }
}

/* ── ETA Calculation (distance-based, assume avg 30 km/h urban) ─────────────── */
function calcEta(driverLat, driverLng, myLat, myLng) {
  const R    = 6371; // km
  const dLat = (myLat - driverLat) * Math.PI / 180;
  const dLng = (myLng - driverLng) * Math.PI / 180;
  const a    = Math.sin(dLat / 2) ** 2
             + Math.cos(driverLat * Math.PI / 180) * Math.cos(myLat * Math.PI / 180)
             * Math.sin(dLng / 2) ** 2;
  const dist = 2 * R * Math.asin(Math.sqrt(a)); // km
  const mins = Math.max(1, Math.round(dist / 30 * 60));
  const etaEl = document.getElementById("eta-display");
  const statEl= document.getElementById("driver-status-display");
  if (etaEl) etaEl.textContent = mins < 2 ? "< 1 min" : `~${mins} min`;
  if (statEl) statEl.textContent = dist < 0.1 ? "Arrived 🎉" : dist < 0.5 ? "Very close" : "Approaching";
}

/* ── Passenger: poll REST for driver location ────────────────────────────────── */
let myLat = null, myLng = null;

function startLocationPolling() {
  // First grab passenger's own position to calculate ETA
  if (navigator.geolocation) {
    navigator.geolocation.getCurrentPosition(
      (pos) => { myLat = pos.coords.latitude; myLng = pos.coords.longitude; setMyMarker(myLat, myLng); },
      () => {},
      { enableHighAccuracy: true }
    );
  }

  locationPollId = setInterval(async () => {
    try {
      const res  = await fetch(`/api/ride-location/${RIDE_ID}`, { credentials: "same-origin" });
      const data = await res.json();
      if (data.success && data.lat != null) {
        setDriverMarker(data.lat, data.lng);
        if (myLat && myLng) calcEta(data.lat, data.lng, myLat, myLng);
      }
    } catch { /* silently ignore network blips */ }
  }, POLL_INTERVAL);
}

function stopLocationPolling() {
  if (locationPollId) { clearInterval(locationPollId); locationPollId = null; }
}

/* ── Driver: stream GPS via Socket.IO ────────────────────────────────────────── */
function startDriverGps() {
  if (!navigator.geolocation) {
    showToast("Geolocation not available.", "danger");
    return;
  }
  const sock = getSocket();
  if (!sock) return;

  driverWatchId = navigator.geolocation.watchPosition(
    (pos) => {
      const lat = pos.coords.latitude;
      const lng = pos.coords.longitude;
      sock.emit("location_update", { ride_id: RIDE_ID, lat, lng });
      setDriverMarker(lat, lng); // show own location on driver map
    },
    (err) => { console.warn("[ActiveRide] GPS error:", err.message); },
    { enableHighAccuracy: true, maximumAge: 3000, timeout: 8000 }
  );

  // Show location sharing banner
  const banner = document.getElementById("location-sharing-banner");
  if (banner) banner.classList.remove("hidden");
}

function stopDriverGps() {
  if (driverWatchId != null) { navigator.geolocation.clearWatch(driverWatchId); driverWatchId = null; }
  const banner = document.getElementById("location-sharing-banner");
  if (banner) banner.classList.add("hidden");
}

/* ── OTP Numpad — Driver ──────────────────────────────────────────────────────── */
function initOtpBoxes() {
  const boxes = document.querySelectorAll(".otp-box");
  if (!boxes.length) return;

  boxes.forEach((box, i) => {
    box.addEventListener("input", (e) => {
      const val = e.target.value.replace(/\D/g, "");
      e.target.value = val ? val[0] : "";
      if (val && i < boxes.length - 1) boxes[i + 1].focus();
      box.classList.toggle("filled", !!val);
    });

    box.addEventListener("keydown", (e) => {
      if (e.key === "Backspace" && !box.value && i > 0) boxes[i - 1].focus();
      if (e.key === "Enter") submitOtp();
    });
  });

  // Auto-focus first box
  boxes[0]?.focus();
}

window.submitOtp = async function () {
  const boxes  = document.querySelectorAll(".otp-box");
  const otp    = [...boxes].map(b => b.value).join("");
  const errEl  = document.getElementById("otp-err-msg");
  const btnLbl = document.getElementById("otp-btn-label");
  const btn    = document.getElementById("otp-submit-btn");

  if (otp.length < 4) {
    errEl.textContent = "Please enter all 4 digits.";
    shakeBoxes();
    return;
  }
  errEl.textContent  = "";
  btnLbl.textContent = "Verifying…";
  btn.disabled       = true;

  try {
    const res  = await fetch(`/api/verify-otp/${RIDE_ID}`, {
      method:  "POST",
      headers: { "Content-Type": "application/json" },
      body:    JSON.stringify({ otp }),
    });
    const data = await res.json();
    if (data.success) {
      showOtpVerifiedState();
      if (typeof showToast === "function") showToast("✅ OTP Verified! Starting live tracking…", "success");
    } else {
      errEl.textContent  = data.message || "Incorrect OTP.";
      shakeBoxes();
      setTimeout(() => {
        boxes.forEach(b => { b.value = ""; b.classList.remove("filled"); });
        boxes[0].focus();
      }, 1400);
    }
  } catch {
    errEl.textContent = "Network error. Try again.";
  } finally {
    btnLbl.textContent = "Verify OTP";
    btn.disabled       = false;
  }
};

function shakeBoxes() {
  const boxes = document.querySelectorAll(".otp-box");
  boxes.forEach(b => {
    b.classList.remove("shake");
    void b.offsetWidth; // reflow
    b.classList.add("shake");
    b.addEventListener("animationend", () => b.classList.remove("shake"), { once: true });
  });
}

function showOtpVerifiedState() {
  document.getElementById("otp-entry-area")?.classList.add("hidden");
  document.getElementById("otp-verified-banner")?.classList.remove("hidden");
  setStatusPill("progress", "🟢 In Progress");
  showLiveBadge();
  startDriverGps();
}

/* ── Passenger OTP Display ───────────────────────────────────────────────────── */
function showPassengerOtp(otp) {
  const digits = String(otp).split("");
  for (let i = 0; i < 4; i++) {
    const el = document.getElementById(`pd${i}`);
    if (el) {
      el.textContent = digits[i] || "—";
      el.style.animationDelay = `${i * 0.07}s`;
    }
  }
}

function setPassengerVerifiedStatus() {
  const statLine = document.getElementById("otp-status-line");
  if (statLine) {
    statLine.innerHTML = `<span style="color:#22c55e;font-weight:700;">✓ Driver verified! Ride started.</span>`;
  }
  setStatusPill("progress", "🟢 In Progress");
  showLiveBadge();
  startLocationPolling();
}

/* ── Helpers ─────────────────────────────────────────────────────────────────── */
function setStatusPill(cls, text) {
  const pill = document.getElementById("ar-status-pill");
  if (!pill) return;
  pill.className = `ar-status-pill ${cls}`;
  pill.textContent = text;
}

function showLiveBadge() {
  document.getElementById("ar-live-badge")?.classList.remove("hidden");
}

function getSocket() {
  return window.socket || (typeof socket !== "undefined" ? socket : null);
}

/* ── Socket.IO Event Wiring ──────────────────────────────────────────────────── */
function wireSocket() {
  const sock = getSocket();
  if (!sock) {
    // Retry until chat.js / base.html script has initialized the socket
    setTimeout(wireSocket, 300);
    return;
  }

  // Join the private ride tracking room
  sock.emit("join_ride_room", { ride_id: RIDE_ID });

  // ── Passenger receives OTP when accepted ─────────────────────────────────
  sock.on("ride_accepted", (data) => {
    if (IS_PASSENGER && data.otp && data.ride_id === RIDE_ID) {
      showPassengerOtp(data.otp);
    }
  });

  // ── Both sides hear this once OTP is verified ─────────────────────────────
  sock.on("otp_verified", (data) => {
    if (data.ride_id !== RIDE_ID) return;
    if (IS_DRIVER) {
      showOtpVerifiedState();
    } else if (IS_PASSENGER) {
      setPassengerVerifiedStatus();
    }
  });

  // ── ride_started is extra signal sent only to passenger ───────────────────
  sock.on("ride_started", (data) => {
    if (data.ride_id !== RIDE_ID) return;
    if (IS_PASSENGER) setPassengerVerifiedStatus();
  });

  // ── Live location from driver (received by passengers via socket) ─────────
  sock.on("driver_location", (data) => {
    if (data.ride_id !== RIDE_ID) return;
    setDriverMarker(data.lat, data.lng);
    if (myLat && myLng) calcEta(data.lat, data.lng, myLat, myLng);
  });

  // ── Ride cancelled ─────────────────────────────────────────────────────────
  sock.on("ride_cancelled", (data) => {
    if (data.ride_id !== RIDE_ID) return;
    if (typeof showToast === "function") showToast("🚫 The ride was cancelled.", "danger");
    setTimeout(() => { window.location.href = "/dashboard"; }, 2500);
  });
}

/* ── Complete / Cancel Ride ─────────────────────────────────────────────────── */
window.completeRide = async function () {
  if (!confirm("Mark this ride as completed?")) return;
  const btn = document.getElementById("complete-btn");
  if (btn) { btn.disabled = true; btn.textContent = "Completing…"; }
  stopDriverGps();
  stopLocationPolling();

  try {
    const res  = await fetch(`/api/complete-ride/${RIDE_ID}`, { method: "POST" });
    const data = await res.json();
    if (data.success) {
      const sock = getSocket();
      sock?.emit("ride_completed_signal", { ride_id: RIDE_ID });
      if (typeof showToast === "function") showToast(`🎉 Ride complete! ⛽ ${data.fuel_saved}L saved.`, "success");
      setTimeout(() => { window.location.href = "/dashboard"; }, 2200);
    } else {
      if (typeof showToast === "function") showToast(data.message, "danger");
      if (btn) { btn.disabled = false; btn.textContent = "✅ Complete Ride"; }
    }
  } catch {
    if (typeof showToast === "function") showToast("Network error.", "danger");
    if (btn) { btn.disabled = false; btn.textContent = "✅ Complete Ride"; }
  }
};

window.cancelRide = async function () {
  if (!confirm("Are you sure you want to cancel this ride?")) return;
  stopDriverGps();
  stopLocationPolling();
  try {
    const res  = await fetch("/api/rides/cancel", {
      method:  "POST",
      headers: { "Content-Type": "application/json" },
      body:    JSON.stringify({ ride_id: RIDE_ID, reason: "Cancelled from active ride page" }),
    });
    const data = await res.json();
    if (data.success) { window.location.href = "/dashboard"; }
    else if (typeof showToast === "function") showToast(data.message, "danger");
  } catch {
    if (typeof showToast === "function") showToast("Network error.", "danger");
  }
};

/* ── Init ────────────────────────────────────────────────────────────────────── */
document.addEventListener("DOMContentLoaded", () => {
  initMap();

  // If OTP already verified when page loads (e.g. page refresh after verification)
  if (window.AR_OTP_VERIFIED) {
    if (IS_DRIVER) {
      showOtpVerifiedState();
    } else if (IS_PASSENGER) {
      // OTP not shown on reload (security) but map and tracking kick in
      document.getElementById("otp-status-line").innerHTML =
        `<span style="color:#22c55e;font-weight:700;">✓ Driver verified! Ride started.</span>`;
      setStatusPill("progress", "🟢 In Progress");
      showLiveBadge();
      startLocationPolling();
    }
  }

  if (IS_DRIVER) initOtpBoxes();
  wireSocket();
});
