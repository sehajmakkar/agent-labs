"""Settings, read from environment variables and a local `.env` file.

Model IDs live here and nowhere else (decisions.md D-005). Run `lab models` to check that the
defaults below exist for your API key, and override them in `.env` if they don't.
"""

import os
from dataclasses import dataclass

from dotenv import load_dotenv

# Confirmed with `lab models` on 2026-10-27. Flash-Lite is the default tier (decisions.md D-014).
DEFAULT_FLASH_MODEL = "gemini-3.8-flash"
DEFAULT_FLASH_LITE_MODEL = "gemini-3.5-flash-lite"


@dataclass(frozen=True)
class Settings:
    gemini_api_key: str | None
    flash_model: str
    flash_lite_model: str

    def model_for(self, tier: str) -> str:
        """Map a tier name ("flash" or "flash-lite") to its configured model ID."""
        return {"flash": self.flash_model, "flash-lite": self.flash_lite_model}[tier]


def load_settings() -> Settings:
    load_dotenv()
    return Settings(
        gemini_api_key=os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"),
        flash_model=os.environ.get("AGENTLAB_FLASH_MODEL", DEFAULT_FLASH_MODEL),
        flash_lite_model=os.environ.get("AGENTLAB_FLASH_LITE_MODEL", DEFAULT_FLASH_LITE_MODEL),
    )
