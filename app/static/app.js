if ("serviceWorker" in navigator) {
  navigator.serviceWorker.register("/sw.js");
}

function formatDuration(seconds) {
  if (seconds == null) return null;
  const total = Math.round(seconds);
  const m = Math.floor(total / 60);
  const s = total % 60;
  return `${m}:${String(s).padStart(2, "0")}`;
}

function formatProductType(productType) {
  const labels = { clips: "Reel", feed: "Post", igtv: "IGTV", carousel: "Carousel" };
  return labels[productType] || productType;
}

function trustworthinessTier(score) {
  if (score >= 80) return "high";
  if (score >= 50) return "moderate";
  return "low";
}

function formatCheckedAt(isoString) {
  const date = new Date(isoString);
  return Number.isNaN(date.getTime()) ? isoString : date.toLocaleString();
}

function sourceDomain(url) {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return url;
  }
}

// Standard MDN conversion: browsers require the VAPID key as a Uint8Array, but it's
// easiest to hand around as the base64url string the server generates it as.
function urlBase64ToUint8Array(base64String) {
  const padding = "=".repeat((4 - (base64String.length % 4)) % 4);
  const base64 = (base64String + padding).replace(/-/g, "+").replace(/_/g, "/");
  const rawData = atob(base64);
  return Uint8Array.from([...rawData].map((char) => char.charCodeAt(0)));
}

// Returns null (rather than throwing) on any failure — permission denied, no VAPID key
// configured, unsupported browser — so callers can fall back to the foreground flow.
async function subscribeToPush() {
  if (!("serviceWorker" in navigator) || !("PushManager" in window) || !window.VAPID_PUBLIC_KEY) {
    return null;
  }
  if (Notification.permission === "denied") return null;
  if (Notification.permission !== "granted") {
    const permission = await Notification.requestPermission();
    if (permission !== "granted") return null;
  }

  try {
    const registration = await navigator.serviceWorker.ready;
    const existing = await registration.pushManager.getSubscription();
    const subscription =
      existing ||
      (await registration.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: urlBase64ToUint8Array(window.VAPID_PUBLIC_KEY),
      }));
    return subscription.toJSON();
  } catch {
    return null;
  }
}

const statusTextEl = document.getElementById("status-text");
const statusSpinnerEl = document.getElementById("status-spinner");
const resultsEl = document.getElementById("results");
const headlineEl = document.getElementById("headline");
const scoreBadgeEl = document.getElementById("score-badge");
const reelInfoEl = document.getElementById("reel-info");
const thumbnailEl = document.getElementById("reel-thumbnail");
const galleryEl = document.getElementById("reel-gallery");
const transcriptSectionEl = document.getElementById("transcript-section");
const cacheWarningEl = document.getElementById("cache-warning");
const cacheWarningTextEl = document.getElementById("cache-warning-text");
const recheckButtonEl = document.getElementById("recheck-button");
const notifyButtonEl = document.getElementById("notify-button");

function setStatus(text, inProgress) {
  statusTextEl.textContent = text;
  statusSpinnerEl.hidden = !inProgress;
}

// Unhides an element with a fade+slide-in transition — flipping `hidden` off and
// adding `.revealed` in the same tick wouldn't transition, since the browser needs
// a layout pass in between to see the "before" state.
function reveal(el) {
  el.hidden = false;
  requestAnimationFrame(() => el.classList.add("revealed"));
}

function resetReveal(el) {
  el.hidden = true;
  el.classList.remove("revealed");
}

function renderResult(data) {
  headlineEl.textContent = data.headline_verdict;
  resultsEl.replaceChildren();

  if (data.trustworthiness_score != null) {
    const tier = trustworthinessTier(data.trustworthiness_score);
    scoreBadgeEl.textContent = data.trustworthiness_score;
    scoreBadgeEl.className = `score-badge ${tier}`;
    scoreBadgeEl.hidden = false;
  }

  (data.claims || []).forEach((c, index) => {
    const card = document.createElement("div");
    card.className = `claim-card reveal ${c.verdict}`;
    card.style.transitionDelay = `${Math.min(index, 8) * 50}ms`;

    const header = document.createElement("div");
    header.className = "claim-header";

    const claimText = document.createElement("span");
    claimText.className = "claim-text";
    claimText.textContent = c.claim;

    const badge = document.createElement("span");
    badge.className = `badge ${c.verdict}`;
    badge.textContent = c.verdict.replace("_", " ");

    const classificationTag = document.createElement("span");
    classificationTag.className = "classification-tag";
    classificationTag.textContent = c.classification;

    header.append(claimText, badge, classificationTag);

    const explanation = document.createElement("p");
    explanation.className = "explanation";
    explanation.textContent = c.explanation;

    card.append(header, explanation);

    if (c.practical_guidance) {
      const guidance = document.createElement("p");
      guidance.className = "practical-guidance";

      const label = document.createElement("strong");
      label.textContent = "Should you be concerned? ";

      guidance.append(label, document.createTextNode(c.practical_guidance));
      card.appendChild(guidance);
    }

    if (c.sources && c.sources.length) {
      const sourcesList = document.createElement("ul");
      sourcesList.className = "sources";
      c.sources.forEach((s) => {
        const li = document.createElement("li");
        li.className = "source-item";

        const row = document.createElement("div");
        row.className = "source-row";

        const badge = document.createElement("span");
        badge.className = `reliability-badge ${s.reliability}`;
        badge.textContent = s.reliability;

        const link = document.createElement("a");
        link.href = s.url;
        link.target = "_blank";
        link.rel = "noopener noreferrer";
        link.title = s.url;
        link.textContent = sourceDomain(s.url);

        row.append(badge, link);

        const note = document.createElement("p");
        note.className = "source-note";
        note.textContent = s.note;

        li.append(row, note);
        sourcesList.appendChild(li);
      });
      card.appendChild(sourcesList);
    }

    resultsEl.appendChild(card);
  });

  requestAnimationFrame(() => {
    resultsEl.querySelectorAll(".claim-card.reveal").forEach((card) => card.classList.add("revealed"));
  });
}

function resetResultsUI() {
  resultsEl.replaceChildren();
  headlineEl.replaceChildren();
  scoreBadgeEl.hidden = true;
  scoreBadgeEl.className = "score-badge";
  resetReveal(reelInfoEl);
  thumbnailEl.hidden = true;
  galleryEl.replaceChildren();
  resetReveal(galleryEl);
  resetReveal(transcriptSectionEl);
  resetReveal(cacheWarningEl);
}

function runCheck(url, force) {
  // Show progress immediately, before the EventSource even connects — a slow network or a
  // buffering proxy between us and the server can delay every SSE event (including the
  // first "fetching" one) well past the moment the user expects to see something happen.
  setStatus("Starting check...", true);
  resetResultsUI();

  const params = new URLSearchParams({ url });
  if (force) params.set("force", "true");
  const source = new EventSource(`/api/v1/check?${params.toString()}`);

  source.addEventListener("fetching", () => setStatus("Fetching reel...", true));
  source.addEventListener("transcribing", () => setStatus("Transcribing audio...", true));
  source.addEventListener("extracting_claims", () => setStatus("Extracting claims...", true));
  source.addEventListener("verifying_claims", () => setStatus("Verifying claims...", true));

  source.addEventListener("reel_info", (e) => {
    const data = JSON.parse(e.data);

    if (data.image_urls && data.image_urls.length) {
      data.image_urls.forEach((src) => {
        const img = document.createElement("img");
        img.src = src;
        img.alt = "";
        galleryEl.appendChild(img);
      });
      reveal(galleryEl);
    } else if (data.thumbnail_url) {
      thumbnailEl.src = data.thumbnail_url;
      thumbnailEl.hidden = false;
    }

    document.getElementById("reel-username").textContent = data.username ? `@${data.username}` : "";
    document.getElementById("reel-caption").textContent = data.caption || "";

    const tagParts = [formatProductType(data.product_type)];
    const duration = formatDuration(data.video_duration);
    if (duration) tagParts.push(duration);
    document.getElementById("reel-tags").textContent = tagParts.filter(Boolean).join(" · ");

    reveal(reelInfoEl);
  });

  source.addEventListener("transcript", (e) => {
    const data = JSON.parse(e.data);
    const textEl = document.getElementById("transcript-text");
    textEl.textContent = data.transcript || "No spoken narration detected.";
    reveal(transcriptSectionEl);
  });

  source.addEventListener("failed", (e) => {
    const data = JSON.parse(e.data);
    setStatus(data.message || "Something went wrong.", false);
    source.close();
  });

  // Native EventSource error (dropped connection, non-2xx, etc.) — no e.data, don't parse it.
  source.onerror = () => {
    setStatus("Connection error. Please try again.", false);
    source.close();
  };

  source.addEventListener("cached", (e) => {
    const data = JSON.parse(e.data);
    setStatus("", false);
    cacheWarningTextEl.textContent = `This reel was already checked on ${formatCheckedAt(data.checked_at)}.`;
    reveal(cacheWarningEl);
    renderResult(data);
    source.close();
  });

  source.addEventListener("done", (e) => {
    const data = JSON.parse(e.data);
    setStatus("", false);
    renderResult(data);
    source.close();
  });
}

function updateNotifyButtonLabel() {
  const enabled = "Notification" in window && Notification.permission === "granted";
  notifyButtonEl.textContent = enabled ? "Notifications enabled ✓" : "Enable notifications";
  notifyButtonEl.disabled = enabled;
}

async function enableNotifications() {
  setStatus("Requesting notification permission...", true);
  notifyButtonEl.textContent = "Requesting...";

  const subscription = await subscribeToPush();
  if (!subscription) {
    updateNotifyButtonLabel();
    setStatus("Couldn't enable notifications — check your browser's notification permission for this site.", false);
    return;
  }

  try {
    await fetch("/api/v1/subscribe", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ subscription }),
    });
    setStatus("Notifications enabled — shared reels will notify you when ready.", false);
  } catch {
    // Subscription exists locally even if this save failed.
    setStatus("Enabled, but couldn't save it to the server — try again.", false);
  }
  updateNotifyButtonLabel();
}

notifyButtonEl.addEventListener("click", enableNotifications);

updateNotifyButtonLabel();

// Try automatically on load rather than waiting for the button — browsers still show
// their own native permission dialog regardless (no site can skip that), and some
// browsers specifically suppress a prompt that isn't triggered by a click, in which
// case this attempt silently does nothing and the button remains as a manual fallback.
if ("Notification" in window && Notification.permission === "default") {
  enableNotifications();
}

document.getElementById("check-form").addEventListener("submit", (event) => {
  event.preventDefault();
  runCheck(document.getElementById("reel-url").value, false);
});

recheckButtonEl.addEventListener("click", () => {
  runCheck(document.getElementById("reel-url").value, true);
});

const prefillUrl = new URLSearchParams(window.location.search).get("url");
if (prefillUrl) {
  document.getElementById("reel-url").value = prefillUrl;
  runCheck(prefillUrl, false);
}
