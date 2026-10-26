"""Settings, read from environment variables and a local `.env` file.

Model IDs and their prices live here and nowhere else (decisions.md D-005). Run `lab models` to
check that the defaults below exist for your API key, and override them in `.env` if they don't.
"""

import os
from dataclasses import dataclass

from dotenv import load_dotenv

# Confirmed with `lab models` on 2026-10-27. Flash-Lite is the default tier (decisions.md D-014).
DEFAULT_FLASH_MODEL = "gemini-3.8-flash"
DEFAULT_FLASH_LITE_MODEL = "gemini-3.5-flash-lite"
DEFAULT_DB_PATH = ".agentlab/lab.db"

# USD per 1M tokens as (input, output), Gemini API paid tier, Standard. From
# ai.google.dev/gemini-api/docs/pricing on 2026-10-27. Output prices include thinking tokens.
# Free-tier keys aren't billed; costs are then what the run *would* cost on the paid tier.
PRICES_PER_MILLION = {
    "gemini-3.5-flash-lite": (0.30, 2.50),
    "gemini-3.8-flash": (0.75, 3.75),  # rises to (1.50, 7.50) on 2027-01-01
}


@dataclass(frozen=True)
class Settings:
    gemini_api_key: str | None
    flash_model: str
    flash_lite_model: str
    db_path: str

    def model_for(self, tier: str) -> str:
        """Map a tier name ("flash" or "flash-lite") to its configured model ID."""
        return {"flash": self.flash_model, "flash-lite": self.flash_lite_model}[tier]


def load_settings() -> Settings:
    load_dotenv()
    return Settings(
        gemini_api_key=os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"),
        flash_model=os.environ.get("AGENTLAB_FLASH_MODEL", DEFAULT_FLASH_MODEL),
        flash_lite_model=os.environ.get("AGENTLAB_FLASH_LITE_MODEL", DEFAULT_FLASH_LITE_MODEL),
        db_path=os.environ.get("AGENTLAB_DB", DEFAULT_DB_PATH),
    )
