"""All tunable settings in one place. Values can be overridden with environment variables."""
import os
import re
from dataclasses import dataclass, field


def _env(name, default):
    return os.environ.get(name, default)


@dataclass
class Settings:
    # --- Vision model (NVIDIA NIM, OpenAI-compatible chat API) ---
    api_key: str = field(default_factory=lambda: _env("NVIDIA_API_KEY", ""))
    api_url: str = "https://integrate.api.nvidia.com/v1/chat/completions"
    model: str = field(default_factory=lambda: _env("VISION_MODEL", "meta/llama-3.2-90b-vision-instruct"))
    fallback_model: str | None = "meta/llama-3.2-11b-vision-instruct"  # faster model for the LAST try; None = off
    ai_timeout: tuple = (15, 90)               # seconds: (connect, read) per call
    min_seconds_between_ai_calls: float = 1.5  # global rate limit across all worker threads (free tier friendly)
    max_image_b64_chars: int = 180_000         # inline image size limit of the API (approx.)

    # --- What to check ---
    max_pages_to_check: int = 3                # pages shown to the model: first, last, second-last
    esign_counts_as_stamp: bool = True         # Aadhaar eSign / applied digital signature => Stamped = Yes too

    # The company that ISSUES the agreements. Its name appears on every agreement,
    # so it must never be returned as the customer's society name.
    vendor_name: str = field(default_factory=lambda: _env("VENDOR_NAME", "Acme Services Pvt. Ltd."))
    vendor_pattern: str = field(default_factory=lambda: _env("VENDOR_PATTERN", r"acme\s*services"))

    # --- Batch run ---
    max_workers: int = 3
    max_attempts: int = 3                      # errored rows are retried on later runs up to this many times
    retry_errors_same_run: bool = True         # retry timeouts / busy errors once at the end of the run

    @property
    def vendor_regex(self):
        return re.compile(self.vendor_pattern, re.I)


SETTINGS = Settings()
