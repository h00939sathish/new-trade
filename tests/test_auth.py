import hmac

import pytest

from src.middleware.auth import verify_bearer_token


class TestVerifyBearerToken:
    def test_valid_token(self):
        assert verify_bearer_token("Bearer my-secret-token", "my-secret-token") is True

    def test_invalid_token(self):
        assert verify_bearer_token("Bearer wrong-token", "my-secret-token") is False

    def test_missing_header(self):
        assert verify_bearer_token(None, "my-secret-token") is False

    def test_empty_header(self):
        assert verify_bearer_token("", "my-secret-token") is False

    def test_malformed_header(self):
        assert verify_bearer_token("Basic dXNlcjpwYXNz", "my-secret-token") is False

    def test_empty_token_in_config(self):
        assert verify_bearer_token("Bearer something", "") is False

    def test_constant_time_comparison(self):
        result = verify_bearer_token("Bearer token-a", "token-b")
        expected = "Bearer token-b"
        actual = "Bearer token-a"
        assert result == (hmac.compare_digest(actual, expected))

    def test_trailing_spaces_handled(self):
        assert verify_bearer_token("  Bearer my-secret-token  ", "my-secret-token") is True

    def test_wrong_scheme(self):
        assert verify_bearer_token("Digest my-secret-token", "my-secret-token") is False
