/**
 * chat.js — MET Ride Socket.IO Chat
 * Creates the global `socket` used across dashboard.html and auth_logic.js.
 */

// ── Create socket & expose globally ──────────────────────────────────────────
const socket = io();
window.socket = socket;   // ← make it accessible to auth_logic.js notification panel

let currentChatRoom    = null;
let typingTimer        = null;
let _lastTypingSent    = 0;

// ── Connection lifecycle ──────────────────────────────────────────────────────
socket.on("connect", () => {
  console.log("[MET Ride] Socket.IO connected:", socket.id);
  // Re-join personal notification room
  if (window.MET?.userId) {
    socket.emit("join_user_room", { user_id: window.MET.userId });
  }
  // Re-join ride room after reconnect
  if (currentChatRoom) {
    socket.emit("join_ride", { ride_id: currentChatRoom });
    appendSystemMessage("Reconnected to chat.");
  }
  // Admin joins admin room for SOS broadcasts
  if (window.MET?.isAdmin) {
    socket.emit("join_admin_room");
  }
});

socket.on("disconnect", () => {
  console.log("[MET Ride] Socket.IO disconnected.");
  appendSystemMessage("Disconnected. Reconnecting…");
});

// ── Join a Ride Chat Room ─────────────────────────────────────────────────────
function joinRideChatRoom(rideId) {
  if (currentChatRoom === rideId) {
    // Already in this room — just scroll the panel into view
    document.getElementById("chat-panel")?.scrollIntoView({ behavior: "smooth" });
    return;
  }

  // Leave old room visually
  if (currentChatRoom) {
    appendSystemMessage(`Left ride #${currentChatRoom.slice(-6)}.`);
  }

  currentChatRoom = rideId;
  socket.emit("join_ride", { ride_id: rideId });

  // ── Update chat header ──────────────────────────────────────────────────
  const label = document.getElementById("chat-room-label");
  if (label) {
    label.textContent = `Ride #${rideId.slice(-6)}`;
    label.style.color = "var(--brand-primary)";
  }

  // Clear old messages & remove join prompt
  const messages = document.getElementById("chat-messages");
  if (messages) messages.innerHTML = "";

  const inputArea = document.getElementById("chat-input-area");
  if (inputArea) inputArea.style.display = "flex";

  const input = document.getElementById("chat-input");
  if (input) input.focus();

  // ── Show chat panel (mobile: scroll to it) ─────────────────────────────
  document.getElementById("chat-panel")?.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

// Expose for inline onclick in dashboard.html
window.joinRideChatRoom = joinRideChatRoom;

// ── Receive messages ──────────────────────────────────────────────────────────
socket.on("receive_message", (data) => {
  const isOwn = data.username === (window.MET?.name || window.MET?.email);
  appendChatMessage(data.username, data.message, data.timestamp, isOwn);
  hideTypingIndicator();
});

socket.on("system_message", (data) => {
  appendSystemMessage(data.text);
});

// ── Typing indicator ──────────────────────────────────────────────────────────
socket.on("user_typing", (data) => {
  if (data.username !== window.MET?.name) {
    showTypingIndicator(data.username);
    clearTimeout(typingTimer);
    typingTimer = setTimeout(hideTypingIndicator, 2500);
  }
});

// ── Send message ──────────────────────────────────────────────────────────────
function sendChatMessage() {
  const input = document.getElementById("chat-input");
  if (!input) return;

  const message = input.value.trim();
  if (!message || !currentChatRoom) {
    if (!currentChatRoom) {
      showChatError("Please join a ride first by clicking a ride card → Join Chat.");
    }
    return;
  }

  socket.emit("send_message", {
    ride_id:  currentChatRoom,
    message,
    username: window.MET?.name || window.MET?.email || "Anonymous",
  });

  input.value = "";
  input.focus();
}

// Allow Enter key to send, Shift+Enter for newline
document.getElementById("chat-input")?.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    sendChatMessage();
    return;
  }
  // Emit typing event (throttled to once per second)
  if (currentChatRoom) {
    const now = Date.now();
    if (now - _lastTypingSent > 1000) {
      _lastTypingSent = now;
      socket.emit("user_typing", {
        ride_id:  currentChatRoom,
        username: window.MET?.name || "Someone",
      });
    }
  }
});

// ── DOM Helpers ───────────────────────────────────────────────────────────────
function appendChatMessage(username, message, timestamp, isOwn) {
  const container = document.getElementById("chat-messages");
  if (!container) return;

  const time = timestamp
    ? new Date(timestamp).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
    : new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });

  const initial = (username || "?")[0].toUpperCase();

  const el = document.createElement("div");
  el.className = `chat-msg ${isOwn ? "own" : "other"}`;
  el.innerHTML = isOwn
    ? `<div class="msg-bubble own-bubble">${escapeHtml(message)}</div>
       <div class="msg-meta">${time}</div>`
    : `<div class="msg-avatar">${initial}</div>
       <div class="msg-body">
         <div class="msg-username">${escapeHtml(username)}</div>
         <div class="msg-bubble other-bubble">${escapeHtml(message)}</div>
         <div class="msg-meta">${time}</div>
       </div>`;

  // Remove typing indicator before appending
  hideTypingIndicator();
  container.appendChild(el);

  // Smooth scroll to bottom
  container.scrollTo({ top: container.scrollHeight, behavior: "smooth" });
}

function appendSystemMessage(text) {
  const container = document.getElementById("chat-messages");
  if (!container) return;
  const el = document.createElement("div");
  el.className = "chat-system-msg";
  el.textContent = text;
  container.appendChild(el);
  container.scrollTo({ top: container.scrollHeight, behavior: "smooth" });
}

function showTypingIndicator(username) {
  let indicator = document.getElementById("typing-indicator");
  if (!indicator) {
    indicator = document.createElement("div");
    indicator.id = "typing-indicator";
    indicator.className = "chat-typing";
    indicator.innerHTML = `
      <span class="typing-name">${escapeHtml(username)}</span>
      <span class="typing-dots">
        <span></span><span></span><span></span>
      </span>`;
    document.getElementById("chat-messages")?.appendChild(indicator);
  }
  document.getElementById("chat-messages")?.scrollTo({
    top: document.getElementById("chat-messages").scrollHeight,
    behavior: "smooth",
  });
}

function hideTypingIndicator() {
  document.getElementById("typing-indicator")?.remove();
}

function showChatError(msg) {
  const area = document.getElementById("chat-messages");
  if (!area) return;
  const el = document.createElement("div");
  el.className = "chat-system-msg";
  el.style.color = "var(--brand-danger)";
  el.textContent = `⚠ ${msg}`;
  area.appendChild(el);
  area.scrollTo({ top: area.scrollHeight, behavior: "smooth" });
  setTimeout(() => el.remove(), 4000);
}

function escapeHtml(text) {
  const d = document.createElement("div");
  d.appendChild(document.createTextNode(text));
  return d.innerHTML;
}
