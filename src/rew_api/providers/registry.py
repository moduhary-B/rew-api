from __future__ import annotations

from rew_api.config import Settings
from rew_api.providers.base import ProviderError, ReviewProvider
from rew_api.providers.twogis import TwoGisProvider
from rew_api.providers.yandex import YandexMapsProvider


class ProviderRegistry:
    def __init__(self, settings: Settings) -> None:
        self._providers: dict[str, ReviewProvider] = {}
        self.register(TwoGisProvider(settings))
        self.register(YandexMapsProvider(settings))

    def register(self, provider: ReviewProvider) -> None:
        self._providers[provider.code] = provider

    def get(self, code: str) -> ReviewProvider:
        try:
            return self._providers[code]
        except KeyError as exc:
            raise ProviderError(f"Unsupported provider: {code}") from exc

    @property
    def supported(self) -> tuple[str, ...]:
        return tuple(sorted(self._providers))
