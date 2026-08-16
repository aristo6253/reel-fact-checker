from unittest.mock import MagicMock

from app.claim_bundle import ClaimBundle
from app.claude_client import Claim, ExtractionResult, extract_claims


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
