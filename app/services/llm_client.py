import os
import httpx
from app.services.exceptions import LLMServiceError

class LLMClient:
    def __init__(self):
        self.api_key = os.getenv("LLM_API_KEY")
        self.base_url = os.getenv("LLM_BASE_URL")
        self.model = os.getenv("LLM_MODEL")

        if not self.api_key or not self.base_url or not self.model:
            raise ValueError(
                "Missing LLM environment variables. "
                "Ensure LLM_API_KEY, LLM_BASE_URL, and LLM_MODEL are set."
            )

    async def chat(
        self,
        messages: list[dict[str, str]],
        *,
        response_format: dict | None = None,
    ) -> str:
        """Send a chat-completion request.

        Args:
            messages:        Conversation turns in OpenAI message format.
            response_format: Optional OpenAI-compatible response_format dict,
                             e.g. {"type": "json_object"}.  When provided it is
                             forwarded verbatim to the provider — callers are
                             responsible for choosing a value their provider
                             supports.  Defaults to None (no constraint).
        """
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.1,  # Keep it low for structured output
        }
        if response_format is not None:
            payload["response_format"] = response_format
        
        try:
            async with httpx.AsyncClient(
                base_url=self.base_url,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json"
                },
                timeout=30.0
            ) as client:
                response = await client.post("/chat/completions", json=payload)
                response.raise_for_status()
                data = response.json()
                return data["choices"][0]["message"]["content"]
        except httpx.HTTPStatusError as e:
            raise LLMServiceError(f"LLM API Error: {e.response.text}")
        except Exception as e:
            if isinstance(e, LLMServiceError):
                raise
            raise LLMServiceError(f"Failed to communicate with LLM: {str(e)}")
