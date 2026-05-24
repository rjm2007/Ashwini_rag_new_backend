import logging
from openai import OpenAI
from ..config import settings

logger = logging.getLogger("llm")
logger.setLevel(logging.INFO)


class LlmService:
    """This class centralizes small and large model calls."""

    def __init__(self) -> None:
        self.client = OpenAI(api_key=settings.openai_api_key)

    def _chat(self, model: str, prompt: str, system_message: str, preferred_temperature: float | None) -> str:
        """Generic chat-completion wrapper that retries without temperature if the model rejects it."""
        messages = [
            {"role": "system", "content": system_message},
            {"role": "user", "content": prompt},
        ]
        kwargs: dict = {"model": model, "messages": messages}
        if preferred_temperature is not None:
            kwargs["temperature"] = preferred_temperature
        try:
            response = self.client.chat.completions.create(**kwargs)
        except Exception as error:
            # Some newer models (e.g. gpt-5.x reasoning) only allow the default temperature.
            # Retry once without it before giving up.
            if preferred_temperature is not None and "temperature" in str(error).lower():
                logger.warning(
                    "model=%s rejected temperature=%s, retrying without it (%s)",
                    model,
                    preferred_temperature,
                    error,
                )
                kwargs.pop("temperature", None)
                try:
                    response = self.client.chat.completions.create(**kwargs)
                except Exception as retry_error:
                    logger.exception("LLM call FAILED on retry model=%s error=%s", model, retry_error)
                    raise
            else:
                logger.exception("LLM call FAILED model=%s error=%s", model, error)
                raise
        return response.choices[0].message.content or ""

    def small_model_call(self, prompt: str, system_message: str) -> str:
        """This function calls the configured low-cost model for extraction tasks."""
        logger.info("LLM small call model=%s prompt_chars=%d", settings.small_model, len(prompt))
        content = self._chat(settings.small_model, prompt, system_message, preferred_temperature=0)
        if not content:
            content = "{}"
        logger.info("LLM small call ok response_chars=%d", len(content))
        return content

    def large_model_call(self, prompt: str, system_message: str) -> str:
        """This function calls the configured reasoning model for final responses."""
        logger.info("LLM large call model=%s prompt_chars=%d", settings.large_model, len(prompt))
        # gpt-5.* reasoning models reject explicit temperature values and force default.
        # Skip sending temperature for those models to avoid a guaranteed 400 + retry delay.
        preferred_temperature = None if settings.large_model.startswith("gpt-5") else 0.1
        content = self._chat(
            settings.large_model,
            prompt,
            system_message,
            preferred_temperature=preferred_temperature,
        )
        logger.info("LLM large call ok response_chars=%d", len(content))
        return content
