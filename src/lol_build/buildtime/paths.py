"""Repository-layout paths used by local build-time commands and fixtures."""

from __future__ import annotations

from pathlib import Path


def repository_root() -> Path:
    """Resolve the source checkout that contains schemas and locked fixtures.

    Runtime callers should pass an explicit root. This fallback exists for local
    validation commands and deliberately centralizes knowledge of the ``src`` layout.

    :return: Repository root containing ``pyproject.toml`` and ``schemas``.
    """

    root = Path(__file__).resolve().parents[3]
    if not (root / "pyproject.toml").is_file() or not (root / "schemas").is_dir():
        raise RuntimeError("cannot resolve repository root from installed source layout")
    return root
