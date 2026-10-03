from __future__ import annotations

import httpx


class OllamaError(RuntimeError):
    pass


class OllamaClient:
    def __init__(self, base_url: str, model: str, timeout: float = 90):
        self.base_url, self.model, self.timeout = base_url.rstrip("/"), model, timeout

    async def generate_json(self, system: str, prompt: str) -> str:
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(f"{self.base_url}/api/chat", json={
                    "model": self.model, "stream": False, "format": "json",
                    "options": {"temperature": 0},
                    "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
                })
                response.raise_for_status()
                content = response.json()["message"]["content"]
                if not isinstance(content, str):
                    raise ValueError("non-string model response")
                return content
        except (httpx.HTTPError, KeyError, ValueError) as exc:
            raise OllamaError("Local language model is unavailable or returned an invalid response") from exc
