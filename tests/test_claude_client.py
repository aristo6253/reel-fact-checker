import json

import pytest
from unittest.mock import MagicMock

from app.claim_bundle import ClaimBundle
from app.claude_client import (
    Claim,
    ExtractionResult,
    Source,
    Verdict,
    VerdictResult,
    _extract_json_object,
    extract_claims,
    verify_claims,
)


def _stream_ctx(response):
    # verify_claims uses client.messages.stream(...) as a context manager and calls
    # .get_final_message() — mock that shape instead of messages.create's plain return.
    ctx = MagicMock()
    ctx.__enter__.return_value = ctx
    ctx.get_final_message.return_value = response
    return ctx


def test_extract_json_object_strips_leading_markdown_fence():
    text = '```json\n{"claims": []}\n```'
    assert _extract_json_object(text) == '{"claims": []}'


def test_extract_json_object_strips_surrounding_prose():
    text = 'Sure, here you go: {"claims": []} Let me know if you need more.'
    assert _extract_json_object(text) == '{"claims": []}'


def test_extract_claims_returns_parsed_result():
    bundle = ClaimBundle(
        caption="The moon is made of cheese, probably.",
        transcript=None,
        source_url="https://www.instagram.com/reel/abc/",
    )

    expected = ExtractionResult(
        claims=[
            Claim(text="The moon is made of cheese", classification="factual"),
            Claim(text="probably", classification="speculative"),
        ]
    )
    mock_response = MagicMock()
    mock_response.content = [MagicMock(type="text", text=expected.model_dump_json())]
    mock_client = MagicMock()
    mock_client.messages.create.return_value = mock_response

    result = extract_claims(bundle, mock_client)

    assert result == expected
    call_kwargs = mock_client.messages.create.call_args.kwargs
    assert call_kwargs["model"] == "claude-haiku-4-5"
    content = call_kwargs["messages"][0]["content"]
    assert len(content) == 1
    assert "cheese" in content[0]["text"]


def test_extract_claims_includes_image_blocks_when_carousel_images_given():
    bundle = ClaimBundle(caption="See slides", transcript=None, source_url="https://x/")
    expected = ExtractionResult(claims=[])
    mock_response = MagicMock()
    mock_response.content = [MagicMock(type="text", text=expected.model_dump_json())]
    mock_client = MagicMock()
    mock_client.messages.create.return_value = mock_response

    images = [{"media_type": "image/jpeg", "data": "AAAA"}]
    extract_claims(bundle, mock_client, images=images)

    content = mock_client.messages.create.call_args.kwargs["messages"][0]["content"]
    assert len(content) == 2
    assert content[0]["type"] == "image"
    assert content[0]["source"] == {"type": "base64", "media_type": "image/jpeg", "data": "AAAA"}
    assert content[1]["type"] == "text"
    assert "carousel slides" in content[1]["text"]


def test_verify_claims_skips_model_call_when_no_factual_claims():
    bundle = ClaimBundle(caption="I love this song", transcript=None, source_url="https://x/")
    extraction = ExtractionResult(claims=[Claim(text="I love this song", classification="opinion")])
    mock_client = MagicMock()

    result = verify_claims(extraction, bundle, mock_client)

    mock_client.messages.create.assert_not_called()
    assert result.claims[0].verdict == "not_applicable"
    assert result.claims[0].sources == []
    assert result.trustworthiness_score == 100


def test_verify_claims_calls_model_for_factual_claims():
    bundle = ClaimBundle(caption="The moon is made of cheese", transcript=None, source_url="https://x/")
    extraction = ExtractionResult(claims=[Claim(text="The moon is made of cheese", classification="factual")])

    expected = VerdictResult(
        headline_verdict="Contains one false claim",
        trustworthiness_score=15,
        claims=[
            Verdict(
                claim="The moon is made of cheese",
                classification="factual",
                verdict="false",
                explanation="The moon is rock, not cheese.",
                sources=[Source(url="https://nasa.gov", reliability="high", note="official source")],
            )
        ],
    )
    mock_response = MagicMock()
    mock_response.content = [MagicMock(type="text", text=expected.model_dump_json())]
    mock_client = MagicMock()
    mock_client.messages.stream.return_value = _stream_ctx(mock_response)

    result = verify_claims(extraction, bundle, mock_client)

    assert result == expected
    assert result.trustworthiness_score == 15
    call_kwargs = mock_client.messages.stream.call_args.kwargs
    assert call_kwargs["model"] == "claude-haiku-4-5"
    assert call_kwargs["tools"][0]["type"] == "web_search_20250305"
    assert "trustworthiness_score" in call_kwargs["messages"][0]["content"]
    assert "practical_guidance" in call_kwargs["messages"][0]["content"]


def test_verdict_round_trips_practical_guidance():
    bundle = ClaimBundle(caption="Air fresheners release phthalates", transcript=None, source_url="https://x/")
    extraction = ExtractionResult(claims=[Claim(text="Air fresheners disrupt hormone levels", classification="factual")])

    expected = VerdictResult(
        headline_verdict="Mechanism is real; typical exposure is low risk",
        trustworthiness_score=85,
        claims=[
            Verdict(
                claim="Air fresheners disrupt hormone levels",
                classification="factual",
                verdict="verified",
                explanation="Phthalates in air fresheners are documented endocrine disruptors.",
                sources=[Source(url="https://nrdc.org", reliability="high", note="NRDC testing")],
                practical_guidance="Typical household exposure is far below doses shown to affect hormones; ventilate when using and prefer fragrance-free products if concerned.",
            )
        ],
    )
    mock_response = MagicMock()
    mock_response.content = [MagicMock(type="text", text=expected.model_dump_json())]
    mock_client = MagicMock()
    mock_client.messages.stream.return_value = _stream_ctx(mock_response)

    result = verify_claims(extraction, bundle, mock_client)

    assert result == expected
    assert result.claims[0].practical_guidance.startswith("Typical household exposure")


def test_verify_claims_uses_last_text_block_not_first():
    bundle = ClaimBundle(caption="The moon is made of cheese", transcript=None, source_url="https://x/")
    extraction = ExtractionResult(claims=[Claim(text="The moon is made of cheese", classification="factual")])

    expected = VerdictResult(
        headline_verdict="Contains one false claim",
        claims=[
            Verdict(
                claim="The moon is made of cheese",
                classification="factual",
                verdict="false",
                explanation="The moon is rock, not cheese.",
                sources=[Source(url="https://nasa.gov", reliability="high", note="official source")],
            )
        ],
    )
    mock_response = MagicMock()
    mock_response.stop_reason = "end_turn"
    mock_response.content = [
        MagicMock(type="text", text="Let me search for this..."),
        MagicMock(type="server_tool_use"),
        MagicMock(type="web_search_tool_result"),
        MagicMock(type="text", text=expected.model_dump_json()),
    ]
    mock_client = MagicMock()
    mock_client.messages.stream.return_value = _stream_ctx(mock_response)

    result = verify_claims(extraction, bundle, mock_client)

    assert result == expected


def test_verify_claims_raises_clear_error_on_refusal():
    bundle = ClaimBundle(caption="The moon is made of cheese", transcript=None, source_url="https://x/")
    extraction = ExtractionResult(claims=[Claim(text="The moon is made of cheese", classification="factual")])

    mock_response = MagicMock()
    mock_response.stop_reason = "refusal"
    mock_response.content = []
    mock_client = MagicMock()
    mock_client.messages.stream.return_value = _stream_ctx(mock_response)

    with pytest.raises(RuntimeError, match="refusal"):
        verify_claims(extraction, bundle, mock_client)


def test_verify_claims_raises_clear_error_when_truncated_by_max_tokens():
    bundle = ClaimBundle(caption="The moon is made of cheese", transcript=None, source_url="https://x/")
    extraction = ExtractionResult(claims=[Claim(text="The moon is made of cheese", classification="factual")])

    mock_response = MagicMock()
    mock_response.stop_reason = "max_tokens"
    mock_response.content = [MagicMock(type="text", text='{"headline_verdict": "truncated...')]
    mock_client = MagicMock()
    mock_client.messages.stream.return_value = _stream_ctx(mock_response)

    with pytest.raises(RuntimeError, match="cut off"):
        verify_claims(extraction, bundle, mock_client)


def test_verify_claims_resumes_after_pause_turn():
    bundle = ClaimBundle(caption="The moon is made of cheese", transcript=None, source_url="https://x/")
    extraction = ExtractionResult(claims=[Claim(text="The moon is made of cheese", classification="factual")])

    expected = VerdictResult(
        headline_verdict="Contains one false claim",
        trustworthiness_score=10,
        claims=[
            Verdict(
                claim="The moon is made of cheese",
                classification="factual",
                verdict="false",
                explanation="The moon is rock, not cheese.",
                sources=[Source(url="https://nasa.gov", reliability="high", note="official source")],
            )
        ],
    )

    paused_response = MagicMock()
    paused_response.stop_reason = "pause_turn"
    paused_response.content = [MagicMock(type="text", text="I now have comprehensive research, let me complete...")]

    final_response = MagicMock()
    final_response.stop_reason = "end_turn"
    final_response.content = [MagicMock(type="text", text=expected.model_dump_json())]

    mock_client = MagicMock()
    mock_client.messages.stream.side_effect = [_stream_ctx(paused_response), _stream_ctx(final_response)]

    result = verify_claims(extraction, bundle, mock_client)

    assert result == expected
    assert mock_client.messages.stream.call_count == 2
    second_call_messages = mock_client.messages.stream.call_args_list[1].kwargs["messages"]
    assert second_call_messages[1]["role"] == "assistant"
    assert second_call_messages[1]["content"] == paused_response.content


def test_verify_claims_gives_up_after_max_restarts_on_persistent_pause_turn():
    bundle = ClaimBundle(caption="The moon is made of cheese", transcript=None, source_url="https://x/")
    extraction = ExtractionResult(claims=[Claim(text="The moon is made of cheese", classification="factual")])

    paused_response = MagicMock()
    paused_response.stop_reason = "pause_turn"
    paused_response.content = [MagicMock(type="text", text="Still searching...")]

    mock_client = MagicMock()
    mock_client.messages.stream.return_value = _stream_ctx(paused_response)

    with pytest.raises(RuntimeError, match="paused"):
        verify_claims(extraction, bundle, mock_client)
