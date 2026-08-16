# Reel Fact-Checker — Webapp v1 Design

This spec supersedes the client/fetch decisions in the top-level `README.md`
("System Design Guide") for the v1 build. That document was written assuming
an Android app with an OS share-sheet intent as the client; this spec covers
the **webapp-first** version that will be built now, with Android planned as
a later phase reusing the same backend. Everything in the README not
explicitly revised below (response schema, stateless data model, general
infra scaling path) still applies.

## 1. Scope for v1

- **Client:** a webapp. A user pastes a public Instagram reel URL into a
  form — no OS share intent, no account, no history.
- **Backend:** fetches the reel, transcribes/reads its content, extracts and
  fact-checks claims via Claude, returns a structured verdict.
- **Android app is out of scope for v1**, but the API contract (§4) is
  designed so Android can call the same backend unchanged when built.

## 2. Compliance framing (revised from README §1)

The original doc leaned on two things that don't fully carry over to a
webapp and should not be repeated as guarantees:

- **Provenance.** A share-sheet action is evidence the user was viewing that
  specific reel. A pasted URL is not — it could come from anywhere. The
  compliance argument no longer rests on "the user was just looking at
  this," only on the properties below.
- **App Store precedent.** Irrelevant with no distribution gatekeeper on
  the web. This lowers distribution risk but doesn't reduce ToS exposure —
  a public webapp is more discoverable than an unlisted APK.

**What still holds, and is the actual compliance argument going forward:**
explicit user action, one on-demand fetch per request, public content only,
no background crawling, no bulk/scheduled scraping.

**Fetch mechanism is compliant by construction, not just by intent.**
Verified during design: the backend fetches exclusively through Instagram's
own official `/embed/captioned/` endpoint — the same public, sanctioned
surface Meta provides for third-party sites to embed a post. This is
different from scraping the main app or simulating an authenticated
session (headless browser, private API clients, logged-in session cookies)
— all of which were considered and rejected specifically because they
convert "fetch a public page" into "impersonate an authenticated human,"
which is the behavior Instagram's ToS and bot detection are built to catch.
If this endpoint ever stops working, the correct response is to revisit
scope (e.g. require the user to upload the video) — not to escalate to a
simulated session.

## 3. Fetch mechanism

**Endpoint:** `https://www.instagram.com/{shortcode}/embed/captioned/`
(shortcode extracted from any of `/p/`, `/reel/`, `/tv/` URL forms; strip
tracking params like `utm_source`, `igsh` before use — the normalized
shortcode is also the cache key if caching is added later per README §5).

**Verified behavior (tested against real reels during design):**
- Returns full, untruncated caption text (`edge_media_to_caption`) and
  post metadata (`product_type`, `video_duration`, `username`, engagement
  counts) — no login wall, no auth.
- For actual video reels (`product_type: "clips"`), also returns a direct,
  fetchable CDN `video_url` (verified: HTTP 200, `video/mp4`, h264+aac,
  no session required).
- **`/p/` posts that are images/carousels have no `video_url`** — this is
  expected, not a failure; route on `product_type`/presence of `video_url`.
- **No subtitle/caption-track data exists in any form**, native or
  otherwise — confirmed empirically. Instagram's native caption sticker
  (when present) is rendered by the app as a client-side overlay at
  playback time and is not part of the downloadable file. Creator-added
  burned-in captions (e.g. CapCut-style text edited into the video before
  upload) *are* part of the file, since they're baked into the pixels —
  but this is incidental and creator-dependent, never guaranteed.
- `accessibility_caption` is Meta's auto-generated alt-text image
  description for screen readers (static image content, not a transcript)
  — not usable for claims extraction, typically `null` on video posts.

**Implication:** transcription cannot be skipped or made optional. It's the
only reliable path to spoken claims. See §5.

## 4. Stack & API contract

- **Backend:** FastAPI (Python) — matches the self-hosted `faster-whisper`
  requirement (Python-native) and ffmpeg/frame-extraction needs.
- **Frontend:** no separate JS framework for v1. A single Jinja-rendered
  shell + vanilla JS calling the API via `fetch()`/`EventSource`. One
  deployable container, one language, no CORS, no second hosting cost.
- **Hard rule:** `POST /api/v1/check` (or its SSE equivalent, §6) is the
  **only** producer of verdict data. The Jinja template renders zero
  business data — just the page shell that calls the API. This costs
  nothing extra now and means the future Android app calls the identical
  endpoint with no backend changes.

## 5. Transcription: self-hosted `faster-whisper`

Decision (evaluated against a hosted free-tier alternative, e.g. Groq):
**self-hosted `faster-whisper`**, matching the original README §3.4 choice.

Rationale:
- Transcription has no fallback data source (§3) — it should therefore have
  the fewest moving parts outside our control. A free-tier third-party API
  is not a dependency with an SLA; its failure is total for exactly the
  reels that matter (spoken claims, no on-screen text).
- SSE streaming (§6) already absorbs the UX cost of cold-start latency —
  a "transcribing... 0:24" progress message makes self-hosting's main
  downside tolerable, which removes most of the original motivation to
  reconsider a hosted API.
- Keeps the compliance/privacy story to one sentence ("fetch public
  content, process transiently, discard") instead of a paragraph about a
  second processor handling the same data.
- Easier to reverse later (swap in an HTTP call) than to unwind a
  dependency built around a rate-limited free tier.

Deferred, not rejected: a hosted API (Groq or otherwise) as an optional
fallback behind an env var, only if self-hosted cold starts prove annoying
in real usage — not built preemptively.

## 6. Pipeline & async handling

```
User pastes reel URL
  -> normalize URL, extract shortcode
  -> GET {shortcode}/embed/captioned/  (caption text + video_url, or no video_url for image/carousel posts)
  -> Content Router: does video_url exist AND does it have an audio track with signal?
       -> yes: extract audio -> faster-whisper transcript
       -> no / silent: skip transcription
  -> Frame sampling (video: frame-difference heuristic; carousel: each image is a frame)
  -> Claim Bundle: {caption, transcript?, frames?, source_url}
  -> Claude stage 1: extract + classify claims (factual | speculative | opinion)
  -> Claude stage 2: verify factual claims only (web search + source reliability tiers)
  -> Structured Verdict JSON (README §4 schema, unchanged)
  -> streamed to the client as it progresses
```

**Async handling:** the full chain (fetch → transcribe → 2-stage Claude
reasoning with search) can take 30-120s. A plain synchronous HTTP response
risks being killed by browsers/proxies before completion. `POST
/api/v1/check` responds via **Server-Sent Events** from the same request —
no queue, no separate infra — streaming progress (`fetching`,
`transcribing`, `checking claim 2 of 4`, `done`) so the wait is visible and
tolerable instead of a silent multi-minute hang.

## 7. Abuse & cost control

No accounts in v1 (README §5 stands), but a public form in front of
metered Claude spend needs a floor:
- Per-IP rate limiting.
- A hard daily spend cap (kill switch, not graceful degradation — fail
  closed with a clear message once hit).
- Revisit only if real usage shows this insufficient; do not build an
  invite-code/auth system preemptively.

## 8. Failure modes (additions to README §7)

- **`/p/` or `/tv/` URL with no `video_url`** (image/carousel post) →
  proceed on caption + frames only, no transcription attempted.
- **`embed/captioned/` returns non-200 or the post is deleted/private** →
  same "couldn't access this reel" message as README §7.
- **Daily spend cap reached** → fail closed with a clear message, not a
  silent queue or degraded response.
- **Rate limit hit** → a clear retry message.
  **Revised (final review, post-build):** the original wording specified
  a "standard 429" — but `GET /api/v1/check`'s transport is SSE, and a
  browser `EventSource` cannot read the body of a non-2xx response, so a
  literal 429/503 makes the message it carries undeliverable to the only
  client that exists. The delivery mechanism is HTTP 200 with a single
  `failed` SSE event carrying the message; the enforcement (denying the
  request) is unchanged. This is the transport-correct form of the same
  requirement, not a weakening of it.

## 9. What's explicitly deferred

- Android app (reuses §4's API contract unchanged, once built).
- Hosted transcription API as a fallback (§5), only if cold starts are a
  real problem in practice.
- Caption-sufficiency short-circuit (skip transcription when the caption
  alone already contains checkable claims) — a plausible cost optimization
  building on the Content Router, but not needed to ship v1; revisit once
  real usage shows how often it would actually apply.
- Everything already deferred in README §6 (caching, queueing, managed
  transcription, GPU inference, multi-region) — unchanged.
- **Video-frame/visual-claim analysis** (added mid-build, after this spec
  was written): §3's frame sampling and §5/§7's OCR-via-Claude-vision
  reasoning are cut from v1 entirely, at the user's request. v1 works from
  caption text + spoken-audio transcript only — no frames, no images sent
  to Claude. See the implementation plan's "Scope Revision" section
  (`docs/superpowers/plans/2026-08-15-webapp-v1.md`) for what changed and
  how to re-add it. This spec's body text above still describes the
  original frame-inclusive design and was not rewritten — treat this note
  as the authoritative statement of current v1 scope where the two
  disagree.
