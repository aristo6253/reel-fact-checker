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
    extract_claims,
    verify_claims,
)


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
    mock_client = MagicMock()
    mock_client.messages.parse.return_value = MagicMock(parsed_output=expected)

    result = extract_claims(bundle, mock_client)

    assert result == expected
    call_kwargs = mock_client.messages.parse.call_args.kwargs
    assert call_kwargs["model"] == "claude-opus-5"
    assert "cheese" in call_kwargs["messages"][0]["content"]


def test_verify_claims_skips_model_call_when_no_factual_claims():
    bundle = ClaimBundle(caption="I love this song", transcript=None, source_url="https://x/")
    extraction = ExtractionResult(claims=[Claim(text="I love this song", classification="opinion")])
    mock_client = MagicMock()

    result = verify_claims(extraction, bundle, mock_client)

    mock_client.messages.create.assert_not_called()
    assert result.claims[0].verdict == "not_applicable"
    assert result.claims[0].sources == []


def test_verify_claims_calls_model_for_factual_claims():
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
    mock_response.content = [MagicMock(type="text", text=expected.model_dump_json())]
    mock_client = MagicMock()
    mock_client.messages.create.return_value = mock_response

    result = verify_claims(extraction, bundle, mock_client)

    assert result == expected
    call_kwargs = mock_client.messages.create.call_args.kwargs
    assert call_kwargs["model"] == "claude-opus-5"
    assert call_kwargs["tools"][0]["type"] == "web_search_20260209"


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
    mock_client.messages.create.return_value = mock_response

    result = verify_claims(extraction, bundle, mock_client)

    assert result == expected


def test_verify_claims_raises_clear_error_on_refusal():
    bundle = ClaimBundle(caption="The moon is made of cheese", transcript=None, source_url="https://x/")
    extraction = ExtractionResult(claims=[Claim(text="The moon is made of cheese", classification="factual")])

    mock_response = MagicMock()
    mock_response.stop_reason = "refusal"
    mock_response.content = []
    mock_client = MagicMock()
    mock_client.messages.create.return_value = mock_response

    with pytest.raises(RuntimeError, match="refusal"):
        verify_claims(extraction, bundle, mock_client)
