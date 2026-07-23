/**
 * auth_logic.js — MET Ride Authentication + Nav Utilities
 */

// ── Tab Switching ─────────────────────────────────────────────────────────────
function switchTab(name) {
  const tabs = ["login", "register"];
  tabs.forEach(t => {
    document.getElementById(`tab-${t}`)?.classList.toggle("active", t === name);
    document.getElementById(`tab-${t}-btn`)?.classList.toggle("active", t === name);
    document.getElementById(`tab-${t}-btn`)?.setAttribute("aria-selected", t === name);
  });
  // Reset error messages
  document.getElementById("login-error")?.classList.add("hidden");
  document.getElementById("register-error")?.classList.add("hidden");
  document.getElementById("verify-error")?.classList.add("hidden");
}

// ── OTP Steps ─────────────────────────────────────────────────────────────────
function backToStep1() {
  document.getElementById("reg-step-1").classList.add("active");
  document.getElementById("reg-step-2").classList.remove("active");
}

// ── Login ─────────────────────────────────────────────────────────────────────
async function handleLogin(e) {
  e.preventDefault();
  const err  = document.getElementById("login-error");
  const btn  = document.getElementById("login-submit");
  const email    = document.getElementById("login-email").value.trim();
  const password = document.getElementById("login-password").value;

  if (!email || !password) {
    showErr(err, "Please enter your email and password.");
    return;
  }

  setLoading(btn, true);
  err.classList.add("hidden");

  try {
    const res  = await fetch("/api/login", {
      method:  "POST",
      headers: { "Content-Type": "application/json" },
      body:    JSON.stringify({ email, password }),
    });
    const data = await res.json();

    if (data.success) {
      window.location.href = data.redirect || "/dashboard";
    } else {
      showErr(err, data.message || "Login failed.");
    }
  } catch {
    showErr(err, "Network error. Please try again.");
  } finally {
    setLoading(btn, false);
  }
}

// ── Register Step 1: Send OTP ─────────────────────────────────────────────────
async function handleRegister(e) {
  e.preventDefault();
  const err  = document.getElementById("register-error");
  const btn  = document.getElementById("register-submit");
  const name  = document.getElementById("reg-name").value.trim();
  const email = document.getElementById("reg-email").value.trim();

  if (!name || !email) {
    showErr(err, "Please enter your name and college email.");
    return;
  }

  setLoading(btn, true);
  err.classList.add("hidden");

  try {
    const res  = await fetch("/api/register", {
      method:  "POST",
      headers: { "Content-Type": "application/json" },
      body:    JSON.stringify({ name, email }),
    });
    const data = await res.json();

    if (data.success) {
      // Move to step 2
      document.getElementById("reg-email-display").textContent = email;

      // Show dev OTP hint if email wasn't sent
      const hint = document.getElementById("dev-otp-hint");
      if (data.dev_otp) {
        hint.textContent = `Dev OTP: ${data.dev_otp}`;
        hint.classList.remove("hidden");
      } else {
        hint.classList.add("hidden");
      }

      document.getElementById("reg-step-1").classList.remove("active");
      document.getElementById("reg-step-2").classList.add("active");
    } else {
      showErr(err, data.message || "Registration failed.");
    }
  } catch {
    showErr(err, "Network error. Please try again.");
  } finally {
    setLoading(btn, false);
  }
}

// ── Register Step 2: Verify OTP ───────────────────────────────────────────────
async function handleVerifyOtp(e) {
  e.preventDefault();
  const err      = document.getElementById("verify-error");
  const btn      = document.getElementById("verify-submit");
  const otp      = document.getElementById("otp-input").value.trim();
  const password = document.getElementById("reg-password").value;

  if (!otp || otp.length < 6) {
    showErr(err, "Please enter the 6-digit OTP.");
    return;
  }
  if (!password || password.length < 8) {
    showErr(err, "Password must be at least 8 characters.");
    return;
  }

  setLoading(btn, true);
  err.classList.add("hidden");

  try {
    const res  = await fetch("/api/verify-otp", {
      method:  "POST",
      headers: { "Content-Type": "application/json" },
      body:    JSON.stringify({ otp, password }),
    });
    const data = await res.json();

    if (data.success) {
      window.location.href = data.redirect || "/dashboard";
    } else {
      showErr(err, data.message || "Verification failed.");
    }
  } catch {
    showErr(err, "Network error. Please try again.");
  } finally {
    setLoading(btn, false);
  }
}

// ── Nav: Mobile Hamburger ─────────────────────────────────────────────────────
const hamburger = document.getElementById("nav-hamburger");
const navLinks  = document.getElementById("nav-links");
if (hamburger && navLinks) {
  hamburger.addEventListener("click", () => {
    navLinks.classList.toggle("open");
    hamburger.classList.toggle("open");
  });
  // Close on outside click
  document.addEventListener("click", (e) => {
    if (!hamburger.contains(e.target) && !navLinks.contains(e.target)) {
      navLinks.classList.remove("open");
    }
  });
}

// ── Nav: SOS Button ───────────────────────────────────────────────────────────
let sosLat = null, sosLng = null;

const sosBtn = document.getElementById("sos-btn");
if (sosBtn) {
  sosBtn.addEventListener("click", openSosModal);
}

// ── 🔔 Notification Panel ─────────────────────────────────────────────────────
(function initNotificationPanel() {
  const btn        = document.getElementById("notif-btn");
  const panel      = document.getElementById("notif-panel");
  const list       = document.getElementById("notif-list");
  const loading    = document.getElementById("notif-loading");
  const countBadge = document.getElementById("notif-count");
  const markAllBtn = document.getElementById("notif-mark-all");

  if (!btn || !panel) return;

  let isOpen      = false;
  let notifData   = [];
  let hasFetched  = false;

  // ── Toggle panel ──────────────────────────────────────────────────────────
  btn.addEventListener("click", (e) => {
    e.stopPropagation();
    isOpen = !isOpen;
    panel.classList.toggle("hidden", !isOpen);
    btn.setAttribute("aria-expanded", String(isOpen));

    if (isOpen && !hasFetched) {
      fetchNotifications();
    }
    if (isOpen) {
      shakeEl?.(btn); // tiny shake on open for feedback
    }
  });

  // ── Close on outside click ────────────────────────────────────────────────
  document.addEventListener("click", (e) => {
    const wrapper = document.getElementById("notif-wrapper");
    if (isOpen && wrapper && !wrapper.contains(e.target)) {
      isOpen = false;
      panel.classList.add("hidden");
      btn.setAttribute("aria-expanded", "false");
    }
  });

  // ── Close on Escape ───────────────────────────────────────────────────────
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && isOpen) {
      isOpen = false;
      panel.classList.add("hidden");
      btn.setAttribute("aria-expanded", "false");
    }
  });

  // ── Mark all read ─────────────────────────────────────────────────────────
  markAllBtn?.addEventListener("click", () => {
    document.querySelectorAll(".notif-item.unread").forEach(el => el.classList.remove("unread"));
    updateBadge(0);
  });

  // ── Fetch from API ────────────────────────────────────────────────────────
  async function fetchNotifications() {
    hasFetched = true;
    if (loading) loading.style.display = "block";

    try {
      const res  = await fetch("/api/notifications");
      if (!res.ok) throw new Error("Not OK");
      notifData  = await res.json();
    } catch {
      notifData = [];
    }

    if (loading) loading.style.display = "none";
    renderNotifications(notifData);
    updateBadge(notifData.length);
  }

  // ── Render notifications list ─────────────────────────────────────────────
  function renderNotifications(items) {
    // Remove skeleton
    if (loading) loading.remove();

    if (!items.length) {
      list.innerHTML = `
        <div class="notif-empty">
          <div class="notif-empty-icon">🔕</div>
          <div>No new notifications</div>
          <div style="font-size:.75rem;margin-top:.25rem">Ride requests will appear here</div>
        </div>`;
      return;
    }

    list.innerHTML = "";
    items.forEach((n, idx) => {
      const initial = (n.name || "?")[0].toUpperCase();
      const el      = document.createElement("div");
      el.className  = `notif-item ${n.is_read ? '' : 'unread'}`;
      el.style.animationDelay = `${idx * 0.05}s`;

      let actionHtml = "";
      if (n.type === "join_request") {
        actionHtml = `
          <div class="notif-actions">
            <button class="notif-accept" onclick="respondToRequest('${n.ride_id}', '${n.from_user_id}', 'accept', this.closest('.notif-item'))">✓ Accept</button>
            <button class="notif-reject" onclick="respondToRequest('${n.ride_id}', '${n.from_user_id}', 'reject', this.closest('.notif-item'))">✗ Decline</button>
          </div>
        `;
      } else if (n.type === "request_accepted") {
        actionHtml = `
          <div class="notif-actions">
            <button class="btn btn-primary btn-sm" onclick="openTrackingModal('${n.ride_id}')">🗺️ Track Ride</button>
          </div>
        `;
      }

      el.innerHTML = `
        <div class="notif-item-top">
          <div class="notif-avatar">${initial}</div>
          <div class="notif-content">
            <div class="notif-msg">${escHtml(n.message)}</div>
          </div>
          <div class="notif-time">${n.created_at ? new Date(n.created_at).toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'}) : 'now'}</div>
        </div>
        ${actionHtml}`;

      list.appendChild(el);
    });
  }

  // Expose respondToRequest globally for onclick
  window.respondToRequest = async function(rideId, requesterId, action, el) {
    const btns = el.querySelectorAll("button");
    btns.forEach(b => b.disabled = true);

    try {
      const res  = await fetch(`/api/accept-ride/${rideId}/${requesterId}`, {
        method:  "POST",
        headers: { "Content-Type": "application/json" },
        body:    JSON.stringify({ action }),
      });
      const data = await res.json();

      if (data.success) {
        el.classList.remove("unread");
        const actionsEl = el.querySelector(".notif-actions");
        if (actionsEl) {
          actionsEl.innerHTML = `<span style="font-size:.78rem;color:var(--${action === 'accept' ? 'brand-success' : 'brand-danger'})">
            ${action === 'accept' ? '✓ Accepted' : '✗ Declined'}</span>`;
        }
        // Decrease badge
        const remaining = list.querySelectorAll(".notif-item.unread").length;
        updateBadge(remaining);
        // Refresh notifications to show the update or just mark read
        fetchNotifications();
      } else {
        btns.forEach(b => b.disabled = false);
        alert(data.message || "Action failed.");
      }
    } catch {
      btns.forEach(b => b.disabled = false);
    }
  }

  // ── Update badge count ────────────────────────────────────────────────────
  function updateBadge(count) {
    if (!countBadge) return;
    if (count > 0) {
      countBadge.textContent = count > 99 ? "99+" : String(count);
      countBadge.classList.remove("hidden");
    } else {
      countBadge.classList.add("hidden");
    }
  }

  // Wire up Socket.IO listener
  window.addEventListener("load", () => {
    const sock = window.socket || (typeof socket !== "undefined" ? socket : null);
    if (sock) {
      sock.on("new_notification", (data) => {
        updateBadge(data.count);
        shakeEl?.(btn);
        // If panel is open, refresh
        if (isOpen) fetchNotifications();
      });
    }
  });

  // ── Kick off initial badge fetch ──────────────────────────────────────
  fetch("/api/notifications")
    .then(r => r.json())
    .then(notifs => {
      const unreadCount = notifs.filter(n => !n.is_read).length;
      updateBadge(unreadCount);
    })
    .catch(() => {});

})();

function escHtml(str) {
  return String(str).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;");
}



function openSosModal() {
  document.getElementById("sos-modal-overlay")?.classList.remove("hidden");
  const text = document.getElementById("sos-location-text");
  if (!text) return;
  text.textContent = "📍 Fetching your location…";
  sosLat = null; sosLng = null;

  if (navigator.geolocation) {
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        sosLat = pos.coords.latitude.toFixed(6);
        sosLng = pos.coords.longitude.toFixed(6);
        text.textContent = `📍 Location: ${sosLat}, ${sosLng}`;
      },
      () => {
        text.textContent = "⚠ Could not get location. Alert will be sent without coordinates.";
      }
    );
  } else {
    text.textContent = "⚠ Geolocation not supported. Alert sent without location.";
  }
}

function closeSosModal() {
  document.getElementById("sos-modal-overlay")?.classList.add("hidden");
}

function confirmSos() {
  const btn = document.getElementById("sos-confirm-btn");
  if (btn) btn.disabled = true;

  const form = new FormData();
  if (sosLat) form.append("lat", sosLat);
  if (sosLng) form.append("lng", sosLng);

  fetch("/sos-alert", { method: "POST", body: form })
    .then(r => r.json())
    .then(d => {
      closeSosModal();
      alert(d.message || "SOS sent!");
    })
    .catch(() => {
      closeSosModal();
      alert("SOS sent (network fallback).");
    })
    .finally(() => { if (btn) btn.disabled = false; });
}

// Close SOS on overlay click
document.getElementById("sos-modal-overlay")?.addEventListener("click", function(e) {
  if (e.target === this) closeSosModal();
});

// ── Helpers ───────────────────────────────────────────────────────────────────
/**
 * showErr — display an error message in el and shake it for attention.
 * Used by handleLogin, handleRegister, handleVerifyOtp
 */
function showErr(el, msg) {
  if (!el) return;
  el.textContent = msg;
  el.classList.remove("hidden");
  shakeEl(el);   // animate-shake on error
}

function setLoading(btn, loading) {
  if (!btn) return;
  btn.disabled = loading;
  if (loading) {
    btn.classList.add("btn-loading");
    btn.style.position = "relative";
  } else {
    btn.classList.remove("btn-loading");
  }
}


// Auto-dismiss flash messages after 5s
document.querySelectorAll(".flash").forEach(el => {
  setTimeout(() => el?.remove(), 5000);
});

// ── 🌊 Ripple Effect on all .btn elements ─────────────────────────────────────
document.addEventListener("click", (e) => {
  const btn = e.target.closest(".btn");
  if (!btn || btn.disabled) return;

  const ripple = document.createElement("span");
  ripple.className = "ripple";

  const rect   = btn.getBoundingClientRect();
  const size   = Math.max(rect.width, rect.height);
  ripple.style.width  = ripple.style.height = `${size}px`;
  ripple.style.left   = `${e.clientX - rect.left  - size / 2}px`;
  ripple.style.top    = `${e.clientY - rect.top   - size / 2}px`;

  btn.appendChild(ripple);
  ripple.addEventListener("animationend", () => ripple.remove());
});

// ── 📳 Shake helper — call shakeEl(element) to trigger shake animation ────────
function shakeEl(el) {
  if (!el) return;
  el.classList.remove("animate-shake");
  // Force reflow so re-adding the class restarts the animation
  void el.offsetWidth;
  el.classList.add("animate-shake");
  el.addEventListener("animationend", () => el.classList.remove("animate-shake"), { once: true });
}
window.shakeEl = shakeEl;

// ── 🎢 Scroll-reveal: slide-up cards as they enter viewport ──────────────────
(function initScrollReveal() {
  const targets = document.querySelectorAll(
    ".card, .stat-card, .ride-card, .auth-card"
  );
  if (!targets.length || !("IntersectionObserver" in window)) return;

  targets.forEach(el => {
    // Don't re-animate cards that already have a CSS animation assigned
    const computed = getComputedStyle(el).animationName;
    if (computed && computed !== "none") return;
    el.style.opacity = "0";
    el.style.transform = "translateY(28px)";
    el.style.transition = "opacity 0.45s ease, transform 0.45s ease";
  });

  const observer = new IntersectionObserver((entries) => {
    entries.forEach(entry => {
      if (entry.isIntersecting) {
        entry.target.style.opacity  = "1";
        entry.target.style.transform = "translateY(0)";
        observer.unobserve(entry.target);
      }
    });
  }, { threshold: 0.12 });

  targets.forEach(el => observer.observe(el));
})();

