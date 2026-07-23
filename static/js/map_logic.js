/**
 * map_logic.js — MET Ride Leaflet Map
 * Initializes the ride map and handles real-time location updates via SocketIO.
 */

let rideMap    = null;
let rideMarkers = {};   // ride_id → L.marker

(function initMap() {
  const mapEl = document.getElementById("ride-map");
  if (!mapEl) return;

  // Mumbai center
  rideMap = L.map("ride-map", {
    center:    [19.0760, 72.8777],
    zoom:      12,
    zoomControl: true,
  });

  // Tile layer — CartoDB dark (matches dark theme)
  const darkTile = "https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png";
  const lightTile= "https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png";

  function getTileUrl() {
    return document.documentElement.getAttribute("data-theme") === "light" ? lightTile : darkTile;
  }

  let tileLayer = L.tileLayer(getTileUrl(), {
    attribution: '&copy; <a href="https://carto.com/">CARTO</a>',
    maxZoom:     19,
  }).addTo(rideMap);

  // Update tiles on theme change
  const observer = new MutationObserver(() => {
    tileLayer.setUrl(getTileUrl());
  });
  observer.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });

  // Custom SVG marker
  function makeIcon(color = "#8b5cf6") {
    return L.divIcon({
      className: "",
      html: `<svg width="28" height="38" viewBox="0 0 28 38" fill="none" xmlns="http://www.w3.org/2000/svg">
        <path d="M14 0C6.27 0 0 6.27 0 14c0 10.5 14 24 14 24s14-13.5 14-24C28 6.27 21.73 0 14 0z" fill="${color}"/>
        <circle cx="14" cy="14" r="6" fill="white"/>
      </svg>`,
      iconSize:   [28, 38],
      iconAnchor: [14, 38],
      popupAnchor: [0, -40],
    });
  }

  window._rideMapMakeIcon = makeIcon;

  // Attempt to add existing ride locations
  addExistingRideMarkers();

  // Listen for live location updates
  // (socket is declared in chat.js, loaded before this file on dashboard)
  if (window.socket) {
    bindLocationEvents();
  } else {
    window.addEventListener("load", () => {
      if (window.socket) bindLocationEvents();
    });
  }
})();

// ── Add markers for rides that already have a known location ──────────────────
function addExistingRideMarkers() {
  const rideCards = document.querySelectorAll(".ride-card[id]");
  rideCards.forEach(card => {
    const rideId = card.id.replace("ride-", "");
    // Fetch ride details to check for a current_location
    fetch(`/api/ride/${rideId}`)
      .then(r => r.json())
      .then(ride => {
        if (ride.current_location && ride.current_location.coordinates) {
          const [lng, lat] = ride.current_location.coordinates;
          addOrUpdateMarker(rideId, lat, lng, `${ride.source} → ${ride.destination}`);
        }
      })
      .catch(() => {}); // silently ignore
  });
}

// ── Live location updates from SocketIO ───────────────────────────────────────
function bindLocationEvents() {
  const sock = window.socket || (typeof socket !== "undefined" ? socket : null);
  if (!sock) return;

  sock.on("location_updated", (data) => {
    const { ride_id, lat, lng } = data;
    addOrUpdateMarker(ride_id, lat, lng);
    const status = document.getElementById("map-status");
    if (status) status.textContent = "Live tracking";
  });
}

function addOrUpdateMarker(rideId, lat, lng, label = "") {
  if (!rideMap) return;

  if (rideMarkers[rideId]) {
    rideMarkers[rideId].setLatLng([lat, lng]);
  } else {
    const marker = L.marker([lat, lng], { icon: window._rideMapMakeIcon?.() })
      .addTo(rideMap);
    if (label) marker.bindPopup(`<strong>${label}</strong>`);
    rideMarkers[rideId] = marker;
  }

  // Pan map to latest updated ride
  rideMap.panTo([lat, lng]);
}

// ── Share My Location (for a ride owner) ─────────────────────────────────────
function shareMyLocation(rideId) {
  if (!navigator.geolocation) {
    alert("Geolocation is not supported by your browser.");
    return;
  }

  const sock = window.socket || (typeof socket !== "undefined" ? socket : null);
  if (!sock) return;

  const watchId = navigator.geolocation.watchPosition(
    (pos) => {
      const { latitude: lat, longitude: lng } = pos.coords;
      sock.emit("update_location", { ride_id: rideId, lat, lng });
      console.log(`[Map] Sent location: ${lat}, ${lng}`);
    },
    (err) => { console.warn("[Map] Geolocation error:", err.message); },
    { enableHighAccuracy: true, maximumAge: 5000, timeout: 10000 }
  );

  // Return watchId so caller can cancel later
  return watchId;
}

window.shareMyLocation = shareMyLocation;
