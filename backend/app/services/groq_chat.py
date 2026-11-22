from flask import current_app
from groq import APIConnectionError, APIError, APITimeoutError, AuthenticationError, Groq, RateLimitError


class GroqError(RuntimeError):
    def __init__(self, message, status):
        super().__init__(message)
        self.status = status


def complete(system, messages, *, structured=False, max_tokens=3000):
    config = current_app.config
    key = config.get("GROQ_API_KEY")
    if not key:
        raise GroqError("Groq is unavailable. Set GROQ_API_KEY on the backend.", 503)
    model = config["GROQ_CHAT_MODEL"]
    options = {"response_format": {"type": "json_object"}} if structured else {}
    if model in {"openai/gpt-oss-20b", "openai/gpt-oss-120b"}:
        options.update(reasoning_effort="low", reasoning_format="hidden")
    try:
        with Groq(api_key=key, timeout=config["GROQ_TIMEOUT_SECONDS"], max_retries=0) as client:
            response = client.chat.completions.create(
                model=model,
                messages=[{"role": "system", "content": system}, *messages],
                temperature=0,
                max_completion_tokens=max_tokens,
                **options,
            )
    except RateLimitError:
        raise GroqError("Groq is rate limited. Wait a moment and retry.", 429) from None
    except APITimeoutError:
        raise GroqError("Groq took too long to respond. Please retry.", 504) from None
    except AuthenticationError:
        raise GroqError("Groq rejected the backend API key. Check GROQ_API_KEY and restart the backend.", 503) from None
    except APIConnectionError:
        raise GroqError("Could not connect to Groq. Please retry.", 503) from None
    except APIError:
        raise GroqError("Groq is unavailable. Please retry or check the backend configuration.", 503) from None
    answer = response.choices[0].message.content if response.choices else None
    if not answer or not answer.strip():
        raise GroqError("Groq returned an empty response. Please retry.", 502)
    return answer.strip()
