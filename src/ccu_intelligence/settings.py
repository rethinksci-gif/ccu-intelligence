"""Load only the repository-local environment; never execute or expand its values."""

from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]


def load_environment(path: Path | None = None) -> None:
    load_dotenv(path or ROOT / ".env", override=False, interpolate=False)
