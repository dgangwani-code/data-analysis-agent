from google import genai
from google.genai import types


class GeminiProvider:
    # NOTE: spec/architecture.md documents "gemini-3.1-pro" as the model ID,
    # but that exact ID 404s against the live Gemini API (only
    # "gemini-3.1-pro-preview" is currently served under that model family per
    # `client.models.list()`). Using the closest live equivalent so real-key
    # tests can run at all; flagged back as a spec-vs-reality drift to sync
    # spec/architecture.md once "gemini-3.1-pro" GAs.
    DEFAULT_MODEL = "gemini-3.1-pro-preview"

    def __init__(self, api_key: str, model: str) -> None:
        self._client = genai.Client(api_key=api_key)
        self._model = model or self.DEFAULT_MODEL

    def call_model(self, prompt: str, *, system: str | None = None) -> str:
        config = types.GenerateContentConfig(
            system_instruction=system,
        ) if system else None
        response = self._client.models.generate_content(
            model=self._model,
            contents=prompt,
            config=config,
        )
        return response.text
