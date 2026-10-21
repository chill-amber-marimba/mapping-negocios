"""Runtime configuration read from the environment."""

import os
from dataclasses import dataclass

API_KEY_ENV = "GOOGLE_MAPS_API_KEY"


class ConfigError(Exception):
    """Raised when required configuration is missing."""


@dataclass(frozen=True, slots=True)
class Settings:
    """Application settings."""

    google_maps_api_key: str

    @classmethod
    def from_env(cls) -> "Settings":
        """Load settings from environment variables.

        Returns:
            The settings.

        Raises:
            ConfigError: If ``GOOGLE_MAPS_API_KEY`` is not set.
        """
        api_key = os.environ.get(API_KEY_ENV, "").strip()
        if not api_key:
            raise ConfigError(f"Environment variable {API_KEY_ENV} is not set.")
        return cls(google_maps_api_key=api_key)
