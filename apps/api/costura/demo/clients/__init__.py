"""Stand-ins for the provider API clients that answer from the manifest instead of the network.

Each class offers the methods its provider's sync and inventory call and yields that
provider's own `FetchedPage`, paginated the way the live API pages, so the sample goes
through the same normalizers, raw pages, runs and allocation as a connected account. `as_of`
is the day of the sync: reports cover the days before it and listings show what existed by
then. A `failures` entry answers HTTP 503 for that many calls of one method."""

from costura.demo.clients.anthropic import AnthropicSampleClient
from costura.demo.clients.base import SampleClient
from costura.demo.clients.cursor import CursorSampleClient
from costura.demo.clients.openai import OpenAISampleClient
from costura.demo.clients.openrouter import OpenRouterSampleClient
from costura.providers.anthropic import PROVIDER as ANTHROPIC
from costura.providers.cursor import PROVIDER as CURSOR
from costura.providers.openai import PROVIDER as OPENAI
from costura.providers.openrouter import PROVIDER as OPENROUTER

CLIENTS: dict[str, type[SampleClient]] = {
    ANTHROPIC: AnthropicSampleClient,
    OPENAI: OpenAISampleClient,
    OPENROUTER: OpenRouterSampleClient,
    CURSOR: CursorSampleClient,
}

__all__ = [
    "CLIENTS",
]
