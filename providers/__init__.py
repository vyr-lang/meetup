"""Provider implementations and registry."""

from providers.claude import ClaudeProvider
from providers.deepseek import DeepSeekProvider
from providers.gemini import GeminiProvider
from providers.grok import GrokProvider
from providers.mistral import MistralProvider
from providers.mock import MockProvider
from providers.openai_provider import OpenAIProvider
from providers.simple_http import SimpleHttpProvider

PROVIDERS = {
    "simple_http": SimpleHttpProvider(),
    "openai": OpenAIProvider(),
    "gemini": GeminiProvider(),
    "grok": GrokProvider(),
    "claude": ClaudeProvider(),
    "deepseek": DeepSeekProvider(),
    "mistral": MistralProvider(),
    "mock": MockProvider(),
}
