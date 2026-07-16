"""
Generic API Tools - Work with any REST API.
"""

import requests
from typing import Dict, Any, Optional
from agent_harness.tool_registry import tool_registry


@tool_registry.register(category="api")
def generic_api_call(
    endpoint: str,
    method: str = "GET",
    headers: Optional[Dict[str, str]] = None,
    body: Optional[Dict[str, Any]] = None,
    params: Optional[Dict[str, Any]] = None,
    auth_type: Optional[str] = None,
    auth_token: Optional[str] = None,
    auth_key: Optional[str] = None,
    timeout: int = 30
) -> Dict[str, Any]:
    """
    Generic REST API call - works with ANY API.

    Supports:
    - All HTTP methods (GET, POST, PUT, DELETE, PATCH)
    - Multiple auth types (bearer, api_key, basic)
    - Headers, body, query params
    - Timeout configuration

    Args:
        endpoint: Full API endpoint URL
        method: HTTP method
        headers: Request headers
        body: Request body (JSON)
        params: Query parameters
        auth_type: Authentication type ('bearer', 'api_key', 'basic')
        auth_token: Auth token (for bearer/basic)
        auth_key: API key (for api_key auth)
        timeout: Request timeout in seconds

    Returns:
        Dict with status_code, data, error
    """
    headers = headers or {}

    # Handle authentication
    if auth_type == "bearer" and auth_token:
        headers["Authorization"] = f"Bearer {auth_token}"
    elif auth_type == "api_key" and auth_key:
        headers["X-API-Key"] = auth_key
    elif auth_type == "basic" and auth_token:
        headers["Authorization"] = f"Basic {auth_token}"

    try:
        response = requests.request(
            method=method.upper(),
            url=endpoint,
            headers=headers,
            json=body,
            params=params,
            timeout=timeout
        )

        return {
            "status_code": response.status_code,
            "success": response.ok,
            "data": response.json() if response.ok and response.content else None,
            "error": None if response.ok else response.text,
            "headers": dict(response.headers)
        }

    except requests.exceptions.Timeout:
        return {
            "status_code": 408,
            "success": False,
            "data": None,
            "error": "Request timeout"
        }
    except requests.exceptions.RequestException as e:
        return {
            "status_code": 500,
            "success": False,
            "data": None,
            "error": str(e)
        }


@tool_registry.register(category="api")
def generic_webhook_sender(
    webhook_url: str,
    payload: Dict[str, Any],
    method: str = "POST",
    headers: Optional[Dict[str, str]] = None,
    secret: Optional[str] = None
) -> Dict[str, Any]:
    """
    Send webhook to external service.

    Args:
        webhook_url: Webhook endpoint URL
        payload: Data to send
        method: HTTP method (POST or PUT)
        headers: Additional headers
        secret: Webhook secret for signature

    Returns:
        Dict with success status and response
    """
    headers = headers or {}
    headers["Content-Type"] = "application/json"

    if secret:
        import hmac
        import hashlib
        import json

        signature = hmac.new(
            secret.encode(),
            json.dumps(payload).encode(),
            hashlib.sha256
        ).hexdigest()
        headers["X-Webhook-Signature"] = signature

    return generic_api_call(
        endpoint=webhook_url,
        method=method,
        headers=headers,
        body=payload
    )