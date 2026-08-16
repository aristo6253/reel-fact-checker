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

  source.addEventListener("error", (e) => {
    const data = JSON.parse(e.data);
    statusEl.textContent = data.message || "Something went wrong.";
    source.close();
  });

  source.addEventListener("done", (e) => {
    const data = JSON.parse(e.data);
    statusEl.textContent = data.headline_verdict;
    resultsEl.innerHTML = (data.claims || [])
      .map(
        (c) => `
        <div class="claim">
          <p><strong>${c.claim}</strong> — ${c.verdict}</p>
          <p>${c.explanation}</p>
        </div>`
      )
      .join("");
    source.close();
  });
});
