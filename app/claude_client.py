import json
from typing import Literal

import anthropic
from pydantic import BaseModel, ConfigDict

from app.claim_bundle import ClaimBundle


class Claim(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str
    classification: Literal["factual", "speculative", "opinion"]


class ExtractionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claims: list[Claim]


def _extraction_prompt(bundle: ClaimBundle) -> str:
    parts = [f"Caption: {bundle.caption}"]
    if bundle.transcript:
        parts.append(f"Spoken narration transcript: {bundle.transcript}")
    parts.append(
        "Extract every discrete factual, speculative, or opinion claim made in this "
        "content. Classify each one as 'factual' (a checkable claim about reality), "
        "'speculative' (a prediction or guess), or 'opinion' (a value judgment). "
        "If there are no claims, return an empty list."
    )
    return "\n\n".join(parts)


def extract_claims(bundle: ClaimBundle, client: anthropic.Anthropic) -> ExtractionResult:
    response = client.messages.parse(
        model="claude-opus-5",
        max_tokens=16000,
        messages=[{"role": "user", "content": _extraction_prompt(bundle)}],
        output_format=ExtractionResult,
    )
    return response.parsed_output


class Source(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str
    reliability: Literal["high", "medium", "low", "questionable"]
    note: str


class Verdict(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claim: str
    classification: Literal["factual", "speculative", "opinion"]
    verdict: Literal["verified", "false", "unverified", "not_applicable"]
    explanation: str
    sources: list[Source]


class VerdictResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    headline_verdict: str
    claims: list[Verdict]


def _verification_prompt(factual_claims: list[Claim], bundle: ClaimBundle) -> str:
    claim_list = "\n".join(f"- {c.text}" for c in factual_claims)
    return (
        f"Source content (from {bundle.source_url}):\n{bundle.caption}\n\n"
        f"Verify each of these factual claims using web search:\n{claim_list}\n\n"
        "For each claim, give a verdict (verified, false, or unverified — use "
        "unverified when no source confirms or denies it, never assume false), a "
        "short explanation, and every source you used with a reliability tier "
        "(high, medium, low, questionable) and a one-line note on why. If the "
        "only available source is questionable, the verdict must be 'unverified', "
        "never a clean 'verified'. Also give a one-sentence headline_verdict "
        "summarizing the overall findings."
    )


def verify_claims(extraction: ExtractionResult, bundle: ClaimBundle, client: anthropic.Anthropic) -> VerdictResult:
    factual_claims = [c for c in extraction.claims if c.classification == "factual"]
    non_factual = [c for c in extraction.claims if c.classification != "factual"]

    non_factual_verdicts = [
        Verdict(
            claim=c.text,
            classification=c.classification,
            verdict="not_applicable",
            explanation="Not a factual claim; not eligible for verification.",
            sources=[],
        )
        for c in non_factual
    ]

    if not factual_claims:
        return VerdictResult(
            headline_verdict="No factual claims detected." if not non_factual_verdicts else "Contains no checkable factual claims.",
            claims=non_factual_verdicts,
        )

    schema = VerdictResult.model_json_schema()
    # ponytail: stop_reason == "pause_turn" (10+ search iterations) is not handled — would need a
    # resend-the-conversation loop; revisit if reels with many factual claims hit this in practice.
    response = client.messages.create(
        model="claude-opus-5",
        max_tokens=16000,
        tools=[{"type": "web_search_20260209", "name": "web_search"}],
        output_config={"format": {"type": "json_schema", "schema": schema}},
        messages=[{"role": "user", "content": _verification_prompt(factual_claims, bundle)}],
    )

    if response.stop_reason == "refusal":
        raise RuntimeError("Claude declined to verify claims for this reel (stop_reason=refusal)")

    text_block = next(b for b in reversed(response.content) if b.type == "text")
    verified = VerdictResult.model_validate(json.loads(text_block.text))
    verified.claims.extend(non_factual_verdicts)
    return verified
