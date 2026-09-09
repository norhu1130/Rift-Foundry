"""Enforce the package boundaries of the recommendation engine."""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "src/lol_build"

ALLOWED_DEPENDENCIES = {
    "core": {"core"},
    "buildtime": {"buildtime", "core"},
    "items": {"items", "core"},
    "scenarios": {"scenarios", "buildtime", "core"},
    "simulation": {"simulation", "core", "items"},
    "recommendation": {"recommendation", "core", "scenarios"},
    # Cogs own champion behavior exclusively; no matchup pair or application
    # service may be special-cased here.
    "cogs": {"cogs", "core", "items"},
    # Application services are the composition root and may depend on every layer.
    "application": {
        "application",
        "buildtime",
        "cogs",
        "core",
        "items",
        "recommendation",
        "scenarios",
        "simulation",
    },
}


def _lol_build_dependencies(path: Path) -> set[str]:
    """Collect first-level ``lol_build`` package dependencies from one module.

    :param path: Python source file whose imports are inspected.
    :return: First package segment referenced by every absolute ``lol_build`` import.
    """

    dependencies: set[str] = set()
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        modules: tuple[str, ...] = ()
        if isinstance(node, ast.ImportFrom) and node.module:
            modules = (node.module,)
        elif isinstance(node, ast.Import):
            modules = tuple(alias.name for alias in node.names)
        for module in modules:
            if module.startswith("lol_build."):
                dependencies.add(module.split(".", 2)[1])
    return dependencies


def test_package_root_contains_no_feature_modules() -> None:
    """Keep feature code inside an explicit architectural package.

    :return: None.
    """

    feature_modules = sorted(
        path.name for path in PACKAGE.glob("*.py") if path.name != "__init__.py"
    )
    assert feature_modules == []


def test_package_dependencies_follow_declared_boundaries() -> None:
    """Prevent lower-level packages from importing orchestration layers.

    :return: None.
    """

    violations: list[str] = []
    for area, allowed in ALLOWED_DEPENDENCIES.items():
        for path in sorted((PACKAGE / area).rglob("*.py")):
            unexpected = _lol_build_dependencies(path) - allowed
            if unexpected:
                violations.append(f"{path.relative_to(PACKAGE)} -> {sorted(unexpected)}")
    assert violations == []
