from __future__ import annotations

import httpx


class OllamaError(RuntimeError):
    pass


class OllamaClient:
    def __init__(self, base_url: str, model: str, timeout: float = 90,
                 num_threads: int = 4, num_ctx: int = 2048, num_gpu: int = -1):
        self.base_url, self.model, self.timeout = base_url.rstrip("/"), model, timeout
        self.num_threads, self.num_ctx, self.num_gpu = num_threads, num_ctx, num_gpu

    async def generate_json(self, system: str, prompt: str, schema: dict | None = None) -> str:
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                options = {
                    "temperature": 0,
                    "num_predict": 128,
                    "num_thread": self.num_threads,
                    "num_ctx": self.num_ctx,
                }
                if self.num_gpu >= 0:
                    options["num_gpu"] = self.num_gpu
                response = await client.post(f"{self.base_url}/api/chat", json={
                    "model": self.model, "stream": False, "format": schema or "json",
                    "think": False,
                    "options": options,
                    "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
                })
                response.raise_for_status()
                content = response.json()["message"]["content"]
                if not isinstance(content, str):
                    raise ValueError("non-string model response")
                return content
        except httpx.TimeoutException as exc:
            raise OllamaError(f"Local language model timed out after {self.timeout:g} seconds") from exc
        except (httpx.HTTPError, KeyError, ValueError) as exc:
            raise OllamaError("Local language model is unavailable or returned an invalid response") from exc
