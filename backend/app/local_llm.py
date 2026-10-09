"""Optional explanation adapter. It cannot modify or approve a training plan."""
import ipaddress
import os
from urllib.parse import urlparse
import httpx


def local_endpoint() -> str:
    url = os.getenv("LOCAL_LLM_URL", "http://127.0.0.1:8080").rstrip("/")
    parsed = urlparse(url)
    try:
        is_loopback = ipaddress.ip_address(parsed.hostname or "").is_loopback
    except ValueError:
        is_loopback = parsed.hostname == "localhost"
    if not is_loopback or parsed.scheme not in ("http", "https") or parsed.username or parsed.password:
        raise ValueError("Local LLM endpoint must be a loopback URL without credentials")
    return url


async def explain(report: dict) -> str | None:
    if os.getenv("LOCAL_LLM_ENABLED", "false").lower() != "true":
        return None
    async with httpx.AsyncClient(timeout=20, trust_env=False, follow_redirects=False) as client:
        response = await client.post(local_endpoint() + "/v1/chat/completions", json={
            "messages": [{"role": "system", "content": "用中文简短解释给定训练记录。只解释已提供事实，不诊断，不新增训练处方。"},
                         {"role": "user", "content": str({"coverage": report["coverage"], "proposal": report["proposal"]})}],
            "temperature": 0.2, "max_tokens": 240})
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"]
