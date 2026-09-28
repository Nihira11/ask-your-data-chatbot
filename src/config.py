"""Explicit AI configuration. Secrets never appear in reprs or saved chat payloads."""
from dataclasses import dataclass, field
import os


@dataclass(frozen=True)
class AIConfig:
    api_key: str = field(default='', repr=False)
    model: str = ''

    @classmethod
    def from_env(cls):
        return cls(os.getenv('OPENAI_API_KEY', '').strip(), os.getenv('OPENAI_MODEL', '').strip())

    def validate(self) -> None:
        if not self.api_key or self.api_key == 'your_api_key_here':
            raise ValueError('Add OPENAI_API_KEY in AI setup or your local .env file.')
        if not self.model:
            raise ValueError('Add OPENAI_MODEL: the exact model ID available to your API account.')
        if len(self.model) > 150 or any(c.isspace() for c in self.model):
            raise ValueError('The model ID must not contain spaces and must be under 150 characters.')


def provider_error(exc: Exception) -> str:
    """Actionable messages without exposing raw provider bodies or credentials."""
    kind = type(exc).__name__
    messages = {
        'AuthenticationError': 'The API key was not accepted. Check the key in AI setup.',
        'PermissionDeniedError': 'This API account does not have permission to use the selected model.',
        'NotFoundError': 'The model was not found for this account. Check the exact API model ID.',
        'RateLimitError': 'The API limit or quota was reached. Check your API billing and usage limits.',
        'APIConnectionError': 'Could not reach OpenAI. Check your internet connection and try again.',
        'APITimeoutError': 'OpenAI took too long to respond. Please try again.',
        'BadRequestError': 'The model rejected this request. Check that it supports Responses, function tools and structured output.',
        'MaxTurnsExceeded': 'The assistant reached its step limit without completing an answer. Try a more specific question.',
    }
    return messages.get(kind, 'The AI request could not be completed. Check your connection and model access, then try again.')
