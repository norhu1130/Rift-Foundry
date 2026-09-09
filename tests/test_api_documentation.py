"""Documentation-contract tests for the extensible Cog runtime surface."""

from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE_MODULES = tuple(sorted((ROOT / "src/lol_build").rglob("*.py")))
FORBIDDEN_DOCSTRING_PATTERNS = (
    r"Value supplied for",
    r"Result produced by this callable",
    r"Represent .+ domain data",
    r"used to compute",
    r"Value processed while computing",
    r"containing the .+ output",
    r"Store the fields required to model",
    r"required by this operation",
    r"Computed .+ for",
    r"Calculated .+ for",
    r"Structured result for",
    r"Stable text representation produced by",
    r"Validate the requested operation",
    r"Rank the requested operation",
    r"Load the requested operation",
    r"Whether .+ is satisfied",
    r"expressed in milliseconds",
    r"Enumerate supported .+ values",
    r"Store the outputs of .+ calculation",
    r"Define the inputs and assumptions for",
    r"Define the constraints used by",
    r"Stable identifier for",
    r"Evaluation inputs and encounter state required by the operation",
    r"Named field or grouping dimension being inspected",
)


def test_every_source_definition_has_structured_english_docstrings() -> None:
    """Require class docs and Sphinx fields on every source callable."""
    failures: list[str] = []
    for path in SOURCE_MODULES:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and not ast.get_docstring(node):
                failures.append(f"{path.name}:{node.lineno}:{node.name}:missing docstring")
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            docstring = ast.get_docstring(node) or ""
            arguments = [
                argument.arg
                for argument in (
                    *node.args.posonlyargs,
                    *node.args.args,
                    *node.args.kwonlyargs,
                )
                if argument.arg not in {"self", "cls"}
            ]
            if not docstring:
                failures.append(f"{path.name}:{node.lineno}:{node.name}:missing docstring")
                continue
            for pattern in FORBIDDEN_DOCSTRING_PATTERNS:
                if re.search(pattern, docstring):
                    failures.append(
                        f"{path.name}:{node.lineno}:{node.name}:placeholder prose {pattern!r}"
                    )
            for argument in arguments:
                if f":param {argument}:" not in docstring:
                    failures.append(
                        f"{path.name}:{node.lineno}:{node.name}:missing :param {argument}:"
                    )
            if ":return:" not in docstring:
                failures.append(f"{path.name}:{node.lineno}:{node.name}:missing :return:")
    assert failures == []
