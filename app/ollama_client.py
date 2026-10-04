from __future__ import annotations

import httpx
import json
import logging
import sys

logger = logging.getLogger(__name__)


class OllamaError(RuntimeError):
    pass


class OllamaClient:
    def __init__(self, base_url: str, model: str, timeout: float = 90):
        self.base_url, self.model, self.timeout = base_url.rstrip("/"), model, timeout
        self.debug_enabled = False

    async def generate_json(self, system: str, prompt: str) -> str:
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                payload = {
                    "model": self.model, "stream": self.debug_enabled, "format": "json",
                    "options": {"temperature": 0},
                    "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
                }
                if self.debug_enabled:
                    logger.info("TRACE Ollama request model=%s prompt=%s", self.model, prompt)
                    logger.info("TRACE model thinking (if available):")
                    # Leave the model's thinking default unchanged to avoid forcing slower inference.
                    parts = []
                    done = False
                    async with client.stream("POST", f"{self.base_url}/api/chat", json=payload) as response:
                        response.raise_for_status()
                        async for line in response.aiter_lines():
                            if not line.strip():
                                continue
                            chunk = json.loads(line)
                            if chunk.get("error"):
                                raise ValueError("Ollama stream failed")
                            message = chunk.get("message", {})
                            thinking = message.get("thinking", "")
                            content = message.get("content", "")
                            if not isinstance(thinking, str) or not isinstance(content, str):
                                raise ValueError("Invalid stream text")
                            if thinking:
                                print(thinking, end="", file=sys.stderr, flush=True)
                            parts.append(content)
                            if chunk.get("done"):
                                done = True
                        print(file=sys.stderr, flush=True)
                    if not done:
                        raise ValueError("Incomplete Ollama stream")
                    content = "".join(parts)
                    logger.info("TRACE Ollama final JSON=%s", content)
                    return content
                response = await client.post(f"{self.base_url}/api/chat", json=payload)
                response.raise_for_status()
                content = response.json()["message"]["content"]
                if not isinstance(content, str):
                    raise ValueError("non-string model response")
                return content
        except (httpx.HTTPError, KeyError, ValueError) as exc:
            raise OllamaError("Local language model is unavailable or returned an invalid response") from exc
