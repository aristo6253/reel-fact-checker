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
        "'speculative' (a prediction or guess), or 'opinion' (a value judgment).\n\n"
        "This content may be a personal anecdote about unnamed private individuals (a "
        "neighbor, a friend, a family member). Do NOT extract the private, unfalsifiable "
        "biographical details of that anecdote as factual claims — someone's exact age, a "
        "private medical diagnosis, the number of items in a personal list, or the content "
        "of a private conversation cannot be independently verified and are not useful "
        "fact-checking targets. Instead, when the anecdote illustrates or asserts a "
        "generalizable claim (a technique, a health or scientific claim, a demographic "
        "pattern, advice presented as broadly true), extract THAT underlying generalizable "
        "claim, rephrased so it stands on its own without referencing the private "
        "individual — for example, from 'my neighbor, who has ADHD, told me writing lists "
        "helps him remember things' extract 'making written lists is a helpful memory "
        "strategy for people with ADHD', not 'the neighbor has ADHD'. If a detail carries "
        "no generalizable checkable assertion beyond personal narrative color, don't turn "
        "it into a factual claim at all — classify it as 'opinion' or omit it.\n\n"
        "If there are no claims, return an empty list."
    )
    return "\n\n".join(parts)


# ponytail: this org's Anthropic gateway silently ignores output_config/messages.parse()'s
# server-enforced JSON schema (confirmed via direct testing — Claude answers in free-form
# prose regardless), so structured output is done the pre-structured-outputs way: embed the
# schema as text in the prompt and parse+validate the response client-side.
def _extract_json_object(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text
        text = text.rsplit("```", 1)[0]
    start, end = text.find("{"), text.rfind("}")
    return text[start : end + 1] if start != -1 and end != -1 else text


def extract_claims(
    bundle: ClaimBundle, client: anthropic.Anthropic, images: list[dict] | None = None
) -> ExtractionResult:
    schema = json.dumps(ExtractionResult.model_json_schema())
    prompt = _extraction_prompt(bundle)
    if images:
        prompt += (
            "\n\nThe attached images are this post's carousel slides, in order. Extract "
            "every claim shown in their text or graphics too, not just the caption."
        )
    prompt += (
        f"\n\nRespond with ONLY a single JSON object matching this schema — no markdown code "
        f"fences, no explanation before or after:\n{schema}"
    )

    content = [
        {"type": "image", "source": {"type": "base64", "media_type": img["media_type"], "data": img["data"]}}
        for img in (images or [])
    ]
    content.append({"type": "text", "text": prompt})

    response = client.messages.create(
        model="claude-sonnet-5",
        max_tokens=16000,
        messages=[{"role": "user", "content": content}],
    )
    text_block = next(b for b in response.content if b.type == "text")
    return ExtractionResult.model_validate_json(_extract_json_object(text_block.text))


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
    practical_guidance: str | None = None


class VerdictResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    headline_verdict: str
    trustworthiness_score: int | None = None
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
        "summarizing the overall findings.\n\n"
        "For each claim, also decide whether practical_guidance is worth giving — "
        "this is most relevant for health, safety, medical, or financial claims. "
        "When the claim has a real-world action dimension, answer plainly: is this "
        "something to actually be concerned about, and under what circumstances "
        "(e.g. dose, frequency, exposure level, pre-existing conditions) would "
        "concern be warranted versus not? Where relevant, name a concrete, low-cost "
        "action a reader could take (e.g. 'ventilate the space' or 'consult a "
        "doctor if symptoms persist'), but don't invent an action when none is "
        "needed. Ground this strictly in the evidence found — do not extrapolate "
        "beyond what your sources support, and explicitly say when a mechanism is "
        "real but typical/casual exposure is not a meaningful risk. Leave "
        "practical_guidance null for claims with no actionable safety, health, or "
        "practical dimension (trivia, historical facts, opinions).\n\n"
        "Finally, give a trustworthiness_score from 0 to 100 for this post's factual "
        "content: 100 means every factual claim checks out and nothing is misleading. "
        "Lower the score for 'false' claims, weighted more heavily when the claim is "
        "central to the post's main point. 'unverified' claims should only modestly "
        "lower the score — absence of evidence is not evidence of falsehood."
    )


def _create_message(client: anthropic.Anthropic, **kwargs):
    # Streaming (not .create()) is required here: the SDK refuses a non-streaming
    # request it estimates could run past ~10 minutes, which a 32000-max_tokens
    # web-search turn can — confirmed live via ValueError: "Streaming is required
    # for operations that may take longer than 10 minutes".
    with client.messages.stream(**kwargs) as stream:
        return stream.get_final_message()


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
            trustworthiness_score=100,
            claims=non_factual_verdicts,
        )

    schema = json.dumps(VerdictResult.model_json_schema())
    prompt = (
        f"{_verification_prompt(factual_claims, bundle)}\n\n"
        f"Respond with ONLY a single JSON object matching this schema — no markdown code "
        f"fences, no explanation before or after:\n{schema}"
    )
    # web_search_20250305 (not the newer _20260209): this org's LogiQ gateway routes through
    # Vertex AI, which only recognizes the older tool version — confirmed via a live 400 error
    # listing accepted tool types. Also valid against the direct Anthropic API, so no downside.
    tools = [{"type": "web_search_20250305", "name": "web_search"}]
    messages = [{"role": "user", "content": prompt}]
    # 32000, not 16000: a claim-heavy reel's JSON (many claims x many sources each) can
    # run long, and a truncated response fails JSON parsing with a cryptic error rather
    # than a clear one — confirmed live against a reel with a genuinely large verdict.
    verify_max_tokens = 32000
    response = _create_message(
        client, model="claude-sonnet-5", max_tokens=verify_max_tokens, tools=tools, messages=messages
    )

    # A long web-search turn (many claims, heavy research) can stop at an internal
    # checkpoint with stop_reason="pause_turn" instead of finishing — the response is
    # mid-narration, not the final JSON. Resend the paused assistant turn to let Claude
    # continue; cap restarts so a persistently-stuck turn fails loudly instead of looping.
    restarts = 0
    max_restarts = 5
    while response.stop_reason == "pause_turn":
        restarts += 1
        if restarts > max_restarts:
            raise RuntimeError(f"Claude's verification turn stayed paused after {max_restarts} restarts")
        messages = [
            {"role": "user", "content": prompt},
            {"role": "assistant", "content": response.content},
        ]
        response = _create_message(
            client, model="claude-sonnet-5", max_tokens=verify_max_tokens, tools=tools, messages=messages
        )

    if response.stop_reason == "max_tokens":
        raise RuntimeError(
            f"Claude's verification response was cut off at the {verify_max_tokens}-token limit "
            "before finishing the JSON — too many claims/sources for this budget"
        )

    if response.stop_reason == "refusal":
        raise RuntimeError("Claude declined to verify claims for this reel (stop_reason=refusal)")

    text_block = next(b for b in reversed(response.content) if b.type == "text")
    verified = VerdictResult.model_validate_json(_extract_json_object(text_block.text))
    verified.claims.extend(non_factual_verdicts)
    return verified
