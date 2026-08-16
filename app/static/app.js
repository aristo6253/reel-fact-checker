document.getElementById("check-form").addEventListener("submit", (event) => {
  event.preventDefault();
  const url = document.getElementById("reel-url").value;
  const statusEl = document.getElementById("status");
  const resultsEl = document.getElementById("results");
  resultsEl.innerHTML = "";

  const source = new EventSource(`/api/v1/check?url=${encodeURIComponent(url)}`);

  source.addEventListener("fetching", () => (statusEl.textContent = "Fetching reel..."));
  source.addEventListener("transcribing", () => (statusEl.textContent = "Transcribing audio..."));
  source.addEventListener("extracting_claims", () => (statusEl.textContent = "Extracting claims..."));
  source.addEventListener("verifying_claims", () => (statusEl.textContent = "Verifying claims..."));

  source.addEventListener("failed", (e) => {
    const data = JSON.parse(e.data);
    statusEl.textContent = data.message || "Something went wrong.";
    source.close();
  });

  // Native EventSource error (dropped connection, non-2xx, etc.) — no e.data, don't parse it.
  source.onerror = () => {
    statusEl.textContent = "Connection error. Please try again.";
    source.close();
  };

  source.addEventListener("done", (e) => {
    const data = JSON.parse(e.data);
    statusEl.textContent = data.headline_verdict;
    resultsEl.replaceChildren();
    (data.claims || []).forEach((c) => {
      const div = document.createElement("div");
      div.className = "claim";

      const p1 = document.createElement("p");
      const strong = document.createElement("strong");
      strong.textContent = c.claim;
      p1.appendChild(strong);
      p1.appendChild(document.createTextNode(` — ${c.verdict}`));

      const p2 = document.createElement("p");
      p2.textContent = c.explanation;

      div.appendChild(p1);
      div.appendChild(p2);
      resultsEl.appendChild(div);
    });
    source.close();
  });
});
