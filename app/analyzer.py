import json
from typing import Any, Dict, List, Optional


def _safe_parse_json(payload_text: str) -> Optional[Any]:
    """
    Safely parse JSON text. Returns parsed object if valid, otherwise None.
    """
    if not payload_text or not payload_text.strip():
        return None

    try:
        return json.loads(payload_text)
    except json.JSONDecodeError:
        return None


def _find_missing_field_name(text: str) -> Optional[str]:
    """
    Try to extract a field name from common missing-field error formats.
    """
    if not text:
        return None

    lowered = text.lower()

    patterns = [
        'missing required field "',
        "missing required field '",
        'required field "',
        "required field '",
        'missing field "',
        "missing field '",
        'field "',
        "field '",
    ]

    for pattern in patterns:
        start = lowered.find(pattern)
        if start != -1:
            actual_start = start + len(pattern)
            remainder = text[actual_start:]
            for quote_char in ['"', "'"]:
                end_index = remainder.find(quote_char)
                if end_index != -1:
                    return remainder[:end_index].strip()

    return None


def _analyze_payload_structure(parsed_payload: Any) -> List[str]:
    """
    Look for obvious payload quality issues.
    """
    issues: List[str] = []

    if not isinstance(parsed_payload, dict):
        return issues

    for key, value in parsed_payload.items():
        if value is None:
            issues.append(f'Field "{key}" is null')
        elif isinstance(value, str) and value.strip() == "":
            issues.append(f'Field "{key}" is empty')

    return issues


def _collect_signals(error_text: str, api_response_text: str) -> Dict[str, List[str]]:
    """
    Collect keyword-based signals from both error text and API response text.
    """
    combined = f"{error_text} {api_response_text}".lower()

    signal_map = {
        "Authentication": [
            "401", "unauthorized", "invalid api key", "expired token",
            "forbidden", "authentication", "auth failed", "access denied",
            "invalid token", "token expired"
        ],
        "Schema": [
            "missing required field", "required field", "missing field",
            "schema", "bad request", "400", "invalid payload",
            "request body validation", "malformed request"
        ],
        "Data Type": [
            "invalid type", "type error", "expected type", "must be",
            "not a valid", "cannot convert", "invalid value",
            "expected integer", "expected string", "expected boolean",
            "expected number"
        ],
        "Rate Limit": [
            "429", "rate limit", "too many requests", "quota exceeded",
            "throttled", "throttle"
        ],
        "Server/Timeout": [
            "500", "502", "503", "504", "timeout", "timed out",
            "server error", "internal server error", "gateway",
            "service unavailable", "bad gateway"
        ],
    }

    found_signals: Dict[str, List[str]] = {}

    for issue_type, keywords in signal_map.items():
        matches = [keyword for keyword in keywords if keyword in combined]
        if matches:
            found_signals[issue_type] = matches

    return found_signals


def _determine_issue_type(found_signals: Dict[str, List[str]]) -> str:
    """
    Choose the strongest issue type based on signal count and priority.
    """
    if not found_signals:
        return "Unknown"

    priority_order = [
        "Authentication",
        "Rate Limit",
        "Server/Timeout",
        "Data Type",
        "Schema",
    ]

    best_issue_type = None
    best_score = -1

    for issue_type in priority_order:
        score = len(found_signals.get(issue_type, []))
        if score > best_score:
            best_score = score
            best_issue_type = issue_type

    return best_issue_type or "Unknown"


def _calculate_confidence(
    issue_type: str,
    found_signals: Dict[str, List[str]],
    parsed_payload: Optional[Any],
    missing_field: Optional[str],
    payload_issues: List[str],
) -> int:
    """
    Calculate confidence based on how much evidence we have.
    """
    if issue_type == "Unknown":
        return 45

    confidence = 70

    signal_count = len(found_signals.get(issue_type, []))
    confidence += min(signal_count * 8, 20)

    if issue_type == "Schema" and missing_field:
        confidence += 8
        if isinstance(parsed_payload, dict) and missing_field not in parsed_payload:
            confidence += 8

    if issue_type == "Data Type" and payload_issues:
        confidence += 4

    if issue_type in ["Authentication", "Rate Limit", "Server/Timeout"]:
        confidence += 5

    return min(confidence, 98)


def _build_response(
    issue_type: str,
    error_text: str,
    api_response_text: str,
    parsed_payload: Optional[Any],
    payload_issues: List[str],
    found_signals: Dict[str, List[str]],
) -> Dict[str, Any]:
    """
    Return a structured diagnosis object.
    """
    combined_text = f"{error_text}\n{api_response_text}".strip()
    missing_field = _find_missing_field_name(combined_text)
    confidence = _calculate_confidence(
        issue_type=issue_type,
        found_signals=found_signals,
        parsed_payload=parsed_payload,
        missing_field=missing_field,
        payload_issues=payload_issues,
    )

    if issue_type == "Authentication":
        return {
            "issue_type": "Authentication",
            "root_cause": "The request likely failed because credentials were invalid, missing, expired, or lacked permission.",
            "confidence": confidence,
            "why_this_happened": "The target system rejected the request during authentication or authorization.",
            "next_steps": [
                "Verify the API key, token, username, or password being used.",
                "Check whether the token expired and needs to be refreshed.",
                "Confirm the connection still has the correct permissions."
            ],
            "suggested_fix_example": "Reconnect the integration or refresh the token, then retry the request.",
            "fields_involved": [],
            "matched_signals": found_signals.get(issue_type, []),
        }

    if issue_type == "Schema":
        fields_involved: List[str] = []
        root_cause = "The request payload does not match the target system's required structure."
        why_this_happened = "A required field may be missing, incorrectly named, or not being mapped into the payload."

        if missing_field:
            fields_involved.append(missing_field)
            root_cause = f'The payload is missing the required field "{missing_field}".'
            why_this_happened = f'The target API expects "{missing_field}", but it was not found in the request.'

        return {
            "issue_type": "Schema",
            "root_cause": root_cause,
            "confidence": confidence,
            "why_this_happened": why_this_happened,
            "next_steps": [
                "Review the required fields expected by the target API.",
                "Check your field mapping from the source system.",
                "Add or correct the missing field, then retry the request."
            ],
            "suggested_fix_example": (
                f'Add "{missing_field}" to the payload and confirm it is populated before sending.'
                if missing_field else
                "Compare the outgoing payload to the API documentation and correct the structure."
            ),
            "fields_involved": fields_involved,
            "matched_signals": found_signals.get(issue_type, []),
        }

    if issue_type == "Data Type":
        return {
            "issue_type": "Data Type",
            "root_cause": "A field value is likely being sent in the wrong format or data type.",
            "confidence": confidence,
            "why_this_happened": "The receiving system expected a different type, such as an integer instead of text, or a valid date format instead of a freeform string.",
            "next_steps": [
                "Check the field definitions in the target API documentation.",
                "Review the payload for numbers, booleans, dates, and null values.",
                "Convert the value to the expected type and retry."
            ],
            "suggested_fix_example": "If a field expects an integer, send 123 instead of \"123\" if the API requires a numeric type.",
            "fields_involved": [],
            "matched_signals": found_signals.get(issue_type, []),
        }

    if issue_type == "Rate Limit":
        return {
            "issue_type": "Rate Limit",
            "root_cause": "The integration is sending too many requests in a short period.",
            "confidence": confidence,
            "why_this_happened": "The target service temporarily blocked or throttled requests because the allowed request limit was exceeded.",
            "next_steps": [
                "Wait and retry after the cooldown period.",
                "Add retry logic with backoff if it does not already exist.",
                "Reduce request frequency or batch requests where possible."
            ],
            "suggested_fix_example": "Use exponential backoff and respect the API provider's retry-after guidance.",
            "fields_involved": [],
            "matched_signals": found_signals.get(issue_type, []),
        }

    if issue_type == "Server/Timeout":
        return {
            "issue_type": "Server/Timeout",
            "root_cause": "The target service or network path likely failed to respond in time or returned a server-side error.",
            "confidence": confidence,
            "why_this_happened": "The issue may be caused by a temporary outage, slow downstream processing, or unstable connectivity between systems.",
            "next_steps": [
                "Retry the request to rule out a temporary failure.",
                "Check whether the target system is experiencing downtime.",
                "Review timeout settings and monitor response times."
            ],
            "suggested_fix_example": "Increase timeout settings if appropriate and add safe retry behavior for transient failures.",
            "fields_involved": [],
            "matched_signals": found_signals.get(issue_type, []),
        }

    return {
        "issue_type": "Unknown",
        "root_cause": "The app could not confidently classify this error yet.",
        "confidence": confidence,
        "why_this_happened": "The error message and API response do not currently match one of the supported detection patterns in version 2.",
        "next_steps": [
            "Review the raw error message closely.",
            "Compare the payload to the target API requirements.",
            "Capture more detailed logs or response data for deeper analysis."
        ],
        "suggested_fix_example": "Add more log details or the full API response to improve diagnosis.",
        "fields_involved": [],
        "matched_signals": [],
    }


def analyze_integration(
    error_text: str,
    payload_text: str = "",
    api_response_text: str = "",
) -> Dict[str, Any]:
    """
    Main entry point for analyzing an integration issue.
    """
    cleaned_error = (error_text or "").strip()
    cleaned_payload = (payload_text or "").strip()
    cleaned_api_response = (api_response_text or "").strip()

    parsed_payload = _safe_parse_json(cleaned_payload)
    payload_issues = _analyze_payload_structure(parsed_payload) if parsed_payload else []

    found_signals = _collect_signals(cleaned_error, cleaned_api_response)
    issue_type = _determine_issue_type(found_signals)

    result = _build_response(
        issue_type=issue_type,
        error_text=cleaned_error,
        api_response_text=cleaned_api_response,
        parsed_payload=parsed_payload,
        payload_issues=payload_issues,
        found_signals=found_signals,
    )

    result["raw_error"] = cleaned_error
    result["raw_api_response"] = cleaned_api_response
    result["payload_valid_json"] = parsed_payload is not None if cleaned_payload else False
    result["payload_warnings"] = payload_issues

    return result