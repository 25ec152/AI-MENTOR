/* chat.js — handles message sending and stage switching for the chat view */

const messagesEl = document.getElementById("chat-messages");
const form       = document.getElementById("chat-form");
const input      = document.getElementById("chat-input");
const sendBtn    = document.getElementById("send-btn");

/** Scroll the message pane to the bottom. */
function scrollBottom() {
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

/**
 * Append a message bubble to the chat pane.
 * @param {"user"|"assistant"} role
 * @param {string} content
 */
function appendMessage(role, content) {
  const wrapper = document.createElement("div");
  wrapper.className = `message message-${role}`;

  const label = document.createElement("span");
  label.className = "message-role";
  label.innerHTML = role === "user"
    ? '<i class="fa-solid fa-circle-user"></i> You'
    : '<i class="fa-solid fa-robot"></i> Aria';

  const bubble = document.createElement("div");
  bubble.className = "message-content";
  bubble.textContent = content;

  wrapper.appendChild(label);
  wrapper.appendChild(bubble);

  // Remove welcome banner on first real message
  const welcome = messagesEl.querySelector(".chat-welcome");
  if (welcome) welcome.remove();

  messagesEl.appendChild(wrapper);
  scrollBottom();
}

/** Show a temporary animated "typing…" indicator. */
function showTyping() {
  const el = document.createElement("div");
  el.id = "typing-indicator";
  el.className = "message message-assistant";
  el.innerHTML = `
    <span class="message-role"><i class="fa-solid fa-robot"></i> Aria</span>
    <div class="message-content">
      <span style="color:var(--text-muted);font-style:italic;margin-right:8px;">Typing</span>
      <span class="typing-dots"><span></span><span></span><span></span></span>
    </div>
  `;
  messagesEl.appendChild(el);
  scrollBottom();
}

function removeTyping() {
  const el = document.getElementById("typing-indicator");
  if (el) el.remove();
}

/* ── Form submit ────────────────────────────────────── */
form.addEventListener("submit", async function (e) {
  e.preventDefault();
  const text = input.value.trim();
  if (!text) return;

  appendMessage("user", text);
  input.value = "";
  sendBtn.disabled = true;
  showTyping();

  try {
    const res = await fetch(`/mentor/chat/${SESSION_ID}/send`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: text }),
    });

    removeTyping();

    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      appendMessage("assistant", `Error: ${err.error || res.statusText}`);
      return;
    }

    const data = await res.json();
    appendMessage("assistant", data.assistant_message.content);
  } catch (err) {
    removeTyping();
    appendMessage("assistant", "Network error — please try again.");
  } finally {
    sendBtn.disabled = false;
    input.focus();
  }
});

/* ── Textarea Enter key (Shift+Enter = newline) ─────── */
input.addEventListener("keydown", function (e) {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    form.dispatchEvent(new Event("submit"));
  }
});

/* ── Stage switching ────────────────────────────────── */
async function setStage(stage) {
  try {
    const res = await fetch(`/mentor/chat/${SESSION_ID}/stage`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ stage }),
    });
    if (!res.ok) return;

    // Update active button styles
    document.querySelectorAll(".stage-btn").forEach(btn => {
      btn.classList.toggle("active", btn.dataset.stage === stage);
    });
  } catch (_) { /* silent fail */ }
}

/* ── Init ───────────────────────────────────────────── */
scrollBottom();
