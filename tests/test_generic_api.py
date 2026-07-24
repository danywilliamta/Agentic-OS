"""Unit tests for agent_harness.tools.generic_api."""

import hashlib
import hmac
import json

import pytest
import requests

from agent_harness.tools import generic_api


class FakeResponse:
    def __init__(self, status_code=200, ok=True, json_data=None, text="", content=b"x", headers=None):
        self.status_code = status_code
        self.ok = ok
        self._json_data = json_data
        self.text = text
        self.content = content
        self.headers = headers or {}

    def json(self):
        return self._json_data


class TestGenericApiCall:
    def test_success_returns_status_data_and_headers(self, monkeypatch):
        response = FakeResponse(status_code=200, ok=True, json_data={"hello": "world"}, headers={"X-Req": "1"})
        monkeypatch.setattr(generic_api.requests, "request", lambda **kwargs: response)

        result = generic_api.generic_api_call(endpoint="https://api.example.com/x")

        assert result == {
            "status_code": 200,
            "success": True,
            "data": {"hello": "world"},
            "error": None,
            "headers": {"X-Req": "1"},
        }

    @pytest.mark.parametrize(
        "auth_type,kwargs,expected_header,expected_value",
        [
            ("bearer", {"auth_token": "tok123"}, "Authorization", "Bearer tok123"),
            ("api_key", {"auth_key": "key123"}, "X-API-Key", "key123"),
            ("basic", {"auth_token": "creds123"}, "Authorization", "Basic creds123"),
        ],
    )
    def test_auth_types_set_expected_header(self, monkeypatch, auth_type, kwargs, expected_header, expected_value):
        captured = {}

        def fake_request(**call_kwargs):
            captured.update(call_kwargs)
            return FakeResponse()

        monkeypatch.setattr(generic_api.requests, "request", fake_request)

        generic_api.generic_api_call(endpoint="https://api.example.com/x", auth_type=auth_type, **kwargs)

        assert captured["headers"][expected_header] == expected_value

    def test_non_ok_response_returns_error_text_and_no_data(self, monkeypatch):
        response = FakeResponse(status_code=404, ok=False, text="Not Found")
        monkeypatch.setattr(generic_api.requests, "request", lambda **kwargs: response)

        result = generic_api.generic_api_call(endpoint="https://api.example.com/missing")

        assert result["success"] is False
        assert result["data"] is None
        assert result["error"] == "Not Found"

    def test_ok_response_with_empty_content_skips_json_parsing(self, monkeypatch):
        response = FakeResponse(status_code=204, ok=True, content=b"")
        monkeypatch.setattr(generic_api.requests, "request", lambda **kwargs: response)

        result = generic_api.generic_api_call(endpoint="https://api.example.com/x")

        assert result["data"] is None

    def test_timeout_returns_408(self, monkeypatch):
        def raise_timeout(**kwargs):
            raise requests.exceptions.Timeout()

        monkeypatch.setattr(generic_api.requests, "request", raise_timeout)

        result = generic_api.generic_api_call(endpoint="https://api.example.com/slow")

        assert result == {"status_code": 408, "success": False, "data": None, "error": "Request timeout"}

    def test_request_exception_returns_500(self, monkeypatch):
        def raise_conn_error(**kwargs):
            raise requests.exceptions.ConnectionError("dns failure")

        monkeypatch.setattr(generic_api.requests, "request", raise_conn_error)

        result = generic_api.generic_api_call(endpoint="https://api.example.com/x")

        assert result["status_code"] == 500
        assert result["success"] is False
        assert "dns failure" in result["error"]


class TestGenericWebhookSender:
    def test_secret_produces_correct_hmac_signature_header(self, monkeypatch):
        captured = {}

        def fake_request(**kwargs):
            captured.update(kwargs)
            return FakeResponse()

        monkeypatch.setattr(generic_api.requests, "request", fake_request)

        payload = {"event": "created"}
        generic_api.generic_webhook_sender(webhook_url="https://hooks.example.com/x", payload=payload, secret="s3cr3t")

        expected_signature = hmac.new(b"s3cr3t", json.dumps(payload).encode(), hashlib.sha256).hexdigest()
        assert captured["headers"]["X-Webhook-Signature"] == expected_signature

    def test_delegates_method_and_payload_to_generic_api_call(self, monkeypatch):
        captured = {}

        def fake_request(**kwargs):
            captured.update(kwargs)
            return FakeResponse()

        monkeypatch.setattr(generic_api.requests, "request", fake_request)

        generic_api.generic_webhook_sender(
            webhook_url="https://hooks.example.com/x", payload={"a": 1}, method="PUT"
        )

        assert captured["method"] == "PUT"
        assert captured["url"] == "https://hooks.example.com/x"
        assert captured["json"] == {"a": 1}
