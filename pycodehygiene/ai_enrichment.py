from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib import error, request


OPENAI_KEY = "OPENAI_API_KEY"
ANTHROPIC_KEY = "ANTHROPIC_API_KEY"

OPENAI_URL = "https://api.openai.com/v1/chat/completions"
ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"

REQUEST_TIMEOUT_SECONDS = 8
REQUEST_RETRIES = 2


def enrich_findings(
    findings: List[Dict[str, object]],
    env_path: Optional[Path] = None,
) -> Dict[str, object]:
    resolved_env_path = env_path or _default_env_path()
    env_values = read_env_file(resolved_env_path)
    provider, api_key = detect_provider(env_values)

    if provider is None or api_key is None:
        return {
            "enabled": False,
            "provider": "none",
            "reason": f"No supported AI key found in {resolved_env_path}; working without AI guidance",
            "enriched_count": 0,
        }

    enriched_count = 0
    failed_count = 0

    for finding in findings:
        guidance = generate_guidance_for_finding(provider=provider, api_key=api_key, finding=finding)
        if guidance is None:
            failed_count += 1
            continue

        explanation = str(guidance.get("explanation", "")).strip()
        improvement = str(guidance.get("improvement", "")).strip()

        if explanation:
            finding["ai_explanation"] = explanation
        if improvement:
            finding["ai_improvement"] = improvement

        if explanation or improvement:
            enriched_count += 1

    if enriched_count > 0:
        reason = f"AI enrichment enabled via {provider} from {resolved_env_path}"
    elif failed_count > 0:
        reason = f"AI key detected ({provider}), but enrichment calls failed; working without AI guidance"
    else:
        reason = f"AI key detected ({provider}), but there were no findings to enrich"

    return {
        "enabled": True,
        "provider": provider,
        "reason": reason,
        "enriched_count": enriched_count,
    }


def _default_env_path() -> Path:
    # Keys are loaded from this tool repository's .env, not the scan target.
    return Path(__file__).resolve().parent.parent / ".env"


def read_env_file(path: Path) -> Dict[str, str]:
    if not path.exists():
        return {}

    values: Dict[str, str] = {}
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return {}

    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue

        key, value = stripped.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            continue

        if value and len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        values[key] = value

    return values


def detect_provider(env_values: Dict[str, str]) -> Tuple[Optional[str], Optional[str]]:
    openai_key = env_values.get(OPENAI_KEY, "").strip()
    if openai_key:
        return "openai", openai_key

    anthropic_key = env_values.get(ANTHROPIC_KEY, "").strip()
    if anthropic_key:
        return "anthropic", anthropic_key

    return None, None


def generate_guidance_for_finding(
    *,
    provider: str,
    api_key: str,
    finding: Dict[str, object],
) -> Optional[Dict[str, str]]:
    payload = _build_user_payload(finding)

    for attempt in range(REQUEST_RETRIES):
        try:
            if provider == "openai":
                response_data = _call_openai(api_key=api_key, payload=payload)
            elif provider == "anthropic":
                response_data = _call_anthropic(api_key=api_key, payload=payload)
            else:
                return None

            parsed = _parse_guidance_json(response_data)
            if parsed is not None:
                return parsed
        except Exception:
            if attempt < REQUEST_RETRIES - 1:
                time.sleep(0.2)
            continue

    return None


def _build_user_payload(finding: Dict[str, object]) -> Dict[str, object]:
    return {
        "category": str(finding.get("category", "")),
        "kind": str(finding.get("kind", "")),
        "confidence": str(finding.get("confidence", "")),
        "file": str(finding.get("file", "")),
        "line_start": int(finding.get("line_start", 0)),
        "line_end": int(finding.get("line_end", 0)),
        "symbol": str(finding.get("symbol", "")),
        "message": str(finding.get("message", "")),
        "evidence": [str(item) for item in finding.get("evidence", [])],
        "suggested_action": str(finding.get("suggested_action", "")),
    }


def _call_openai(*, api_key: str, payload: Dict[str, object]) -> Dict[str, object]:
    body = {
        "model": "gpt-4o-mini",
        "temperature": 0.2,
        "response_format": {"type": "json_object"},
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are a Python code quality assistant. Return strict JSON with keys "
                    "'explanation' and 'improvement'. Keep each concise (<= 2 sentences)."
                ),
            },
            {
                "role": "user",
                "content": (
                    "Analyze this finding and explain what is wrong and how to improve it.\n"
                    f"{json.dumps(payload, ensure_ascii=True)}"
                ),
            },
        ],
    }
    response_data = _post_json(
        OPENAI_URL,
        {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        body,
    )

    choices = response_data.get("choices", [])
    if not choices:
        return {}
    first_choice = choices[0] if isinstance(choices[0], dict) else {}
    message = first_choice.get("message", {}) if isinstance(first_choice, dict) else {}
    content = message.get("content", "") if isinstance(message, dict) else ""
    if not isinstance(content, str):
        return {}
    return {"raw_text": content}


def _call_anthropic(*, api_key: str, payload: Dict[str, object]) -> Dict[str, object]:
    body = {
        "model": "claude-3-5-haiku-latest",
        "max_tokens": 300,
        "temperature": 0.2,
        "system": (
            "You are a Python code quality assistant. Return strict JSON with keys "
            "'explanation' and 'improvement'. Keep each concise (<= 2 sentences)."
        ),
        "messages": [
            {
                "role": "user",
                "content": (
                    "Analyze this finding and explain what is wrong and how to improve it.\n"
                    f"{json.dumps(payload, ensure_ascii=True)}"
                ),
            }
        ],
    }
    response_data = _post_json(
        ANTHROPIC_URL,
        {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        },
        body,
    )

    content_items = response_data.get("content", [])
    if not content_items:
        return {}
    first_item = content_items[0] if isinstance(content_items[0], dict) else {}
    text = first_item.get("text", "") if isinstance(first_item, dict) else ""
    if not isinstance(text, str):
        return {}
    return {"raw_text": text}


def _parse_guidance_json(response_data: Dict[str, object]) -> Optional[Dict[str, str]]:
    raw_text = response_data.get("raw_text", "")
    if not isinstance(raw_text, str) or not raw_text.strip():
        return None

    try:
        parsed = json.loads(raw_text)
    except json.JSONDecodeError:
        return None

    if not isinstance(parsed, dict):
        return None

    explanation = str(parsed.get("explanation", "")).strip()
    improvement = str(parsed.get("improvement", "")).strip()

    if not explanation and not improvement:
        return None

    return {
        "explanation": explanation,
        "improvement": improvement,
    }


def _post_json(url: str, headers: Dict[str, str], payload: Dict[str, object]) -> Dict[str, object]:
    body = json.dumps(payload).encode("utf-8")
    req = request.Request(url=url, data=body, headers=headers, method="POST")
    try:
        with request.urlopen(req, timeout=REQUEST_TIMEOUT_SECONDS) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except error.HTTPError as exc:
        try:
            detail = exc.read().decode("utf-8")
        except Exception:
            detail = ""
        raise RuntimeError(f"HTTP error {exc.code}: {detail}") from exc
