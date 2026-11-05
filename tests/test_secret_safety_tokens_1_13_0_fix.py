"""1.13.0: AWS idempotency / pagination tokens are not credentials."""

from __future__ import annotations

import pytest

from rule_engine import secret_safety as ss


@pytest.mark.parametrize(
    "key",
    ["ClientToken", "LockToken", "NextToken", "IdempotencyToken",
     "ContinuationToken", "NextContinuationToken", "PaginationToken", "client_token"],
)
def test_request_tokens_are_metadata(key):
    assert not ss.is_credential_key(key)
    assert ss.find_secrets({key: "8c1b0c34-0d5e-4b5e-9b35-b3a2a3e8f001"}) == []


@pytest.mark.parametrize(
    "key", ["SessionToken", "AccessToken", "RefreshToken", "Token", "aws_secret_access_key"]
)
def test_credential_tokens_still_flagged(key):
    assert ss.is_credential_key(key)
    hits = ss.find_secrets({key: "opaque-value-123"})
    assert [h.kind for h in hits] == [f"credential-key:{ss.normalize_key(key)}"]


def test_secret_shaped_value_under_client_token_still_flagged():
    data = {
        "AccessKeyId": "AKIAABCDEFGHIJKLMNOP",
        "ClientToken": "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
    }
    kinds = [h.kind for h in ss.find_secrets(data)]
    assert "value:aws-secret-key" in kinds


def test_pem_value_under_client_token_still_flagged():
    hits = ss.find_secrets({"ClientToken": "-----BEGIN RSA PRIVATE KEY-----\nabc"})
    assert [h.kind for h in hits] == ["value:pem-private-key"]


def test_text_scan_allows_client_token():
    assert ss.scan_text("ClientToken: 8c1b0c34-0d5e") == []
    assert ss.scan_text("SessionToken: abc") != []
