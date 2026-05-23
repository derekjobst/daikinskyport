"""Unit tests for optimistic hold-merge helpers."""
from __future__ import annotations

from daikinskyport.daikinskyport import (
    DaikinSkyport,
    _extract_temp_fields,
    _parse_response_json,
    _safe_body_for_log,
)
from daikinskyport.sync_helpers import pending_values_match


class TestPendingValuesMatch:
    def test_none_pairs(self) -> None:
        assert pending_values_match(None, None) is True

    def test_bool_exact(self) -> None:
        assert pending_values_match(True, True) is True
        assert pending_values_match(True, False) is False

    def test_float_within_threshold(self) -> None:
        assert pending_values_match(21.0, 21.1) is True
        assert pending_values_match(21.0, 21.2) is False

    def test_string_equality(self) -> None:
        assert pending_values_match("wake", "wake") is True


class TestHttpClient:
    def test_daikin_skyport_creates_reusable_session(self) -> None:
        api = DaikinSkyport(
            config={
                "EMAIL": "a@b.com",
                "PASSWORD": "secret",
                "ACCESS_TOKEN": "access",
                "REFRESH_TOKEN": "refresh",
            }
        )
        assert api._session is not None

    def test_parse_response_json_empty_body(self) -> None:
        class _Response:
            text = ""

        assert _parse_response_json(_Response()) is None


class TestApiLoggingHelpers:
    def test_extract_temp_fields(self) -> None:
        data = {
            "hspHome": 20.0,
            "cspHome": 24.0,
            "schedMonPart1hsp": 19.0,
            "mode": 3,
        }
        temps = _extract_temp_fields(data)
        assert temps["hspHome"] == 20.0
        assert temps["schedMonPart1hsp"] == 19.0
        assert "mode" not in temps

    def test_safe_body_for_log_redacts_secrets(self) -> None:
        body = {"email": "a@b.com", "password": "secret", "refreshToken": "tok"}
        safe = _safe_body_for_log(body)
        assert safe["password"] == "***"
        assert safe["refreshToken"] == "***"
        assert safe["email"] == "a@b.com"
