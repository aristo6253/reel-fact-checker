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
