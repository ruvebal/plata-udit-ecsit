"""
Ollama service for marker-pdf (Ollama 0.17+ compatible).

marker-pdf 1.10.x's built-in OllamaService raises KeyError when Ollama's
response omits the optional ``prompt_eval_count`` / ``eval_count`` fields
(common with vision models and structured output on Ollama 0.17+).

This implementation uses ``.get()`` so the response data is not
discarded when those token-counting fields are absent.

Usage with plata-extract:
    plata-extract file.pdf --backend neural --use-llm \\
        --llm-service plata_extract.ollama_service.OllamaService
"""

import json
import logging
from typing import Annotated, List

import PIL
import requests
from pydantic import BaseModel

from marker.schema.blocks import Block
from marker.services import BaseService

logger = logging.getLogger(__name__)


class OllamaService(BaseService):
    """Ollama 0.17+ compatible; uses safe .get() for token counts and a longer timeout for vision models."""
    ollama_base_url: Annotated[
        str, "The base url to use for ollama.  No trailing slash."
    ] = "http://localhost:11434"
    ollama_model: Annotated[str, "The model name to use for ollama."] = (
        "llama3.2-vision"
    )
    # Vision models often need >30s per request; BaseService defaults to 30.
    timeout: Annotated[int, "Timeout in seconds for /api/generate (vision models need more)."] = 300

    def process_images(self, images: List[PIL.Image.Image]) -> list:
        return [self.img_to_base64(img) for img in images]

    def __call__(
        self,
        prompt: str,
        image: PIL.Image.Image | List[PIL.Image.Image] | None,
        block: Block | None,
        response_schema: type[BaseModel],
        max_retries: int | None = None,
        timeout: int | None = None,
    ):
        url = f"{self.ollama_base_url}/api/generate"
        headers = {"Content-Type": "application/json"}

        schema = response_schema.model_json_schema()
        format_schema = {
            "type": "object",
            "properties": schema["properties"],
            "required": schema.get("required", []),
        }

        image_bytes = self.format_image_for_llm(image)

        payload = {
            "model": self.ollama_model,
            "prompt": prompt,
            "stream": False,
            "format": format_schema,
            "images": image_bytes,
        }

        try:
            response = requests.post(
                url, json=payload, headers=headers,
                timeout=timeout if timeout is not None else self.timeout,
            )
            response.raise_for_status()
            response_data = response.json()

            total_tokens = (
                response_data.get("prompt_eval_count", 0)
                + response_data.get("eval_count", 0)
            )

            if block:
                block.update_metadata(llm_request_count=1, llm_tokens_used=total_tokens)

            data = response_data.get("response", "{}")
            return json.loads(data)
        except Exception as e:
            logger.warning("Ollama inference failed: %s", e)

        return {}


# Backward compatibility: old name referred to the same class.
PatchedOllamaService = OllamaService
