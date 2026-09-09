import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME_ROOT = ROOT / "src/lol_build"
FORBIDDEN_NETWORK_ROOTS = {"aiohttp", "http", "httpx", "requests", "socket", "urllib"}


def test_runtime_modules_do_not_import_network_or_buildtime_code() -> None:
    violations: list[str] = []
    for path in sorted(RUNTIME_ROOT.glob("*.py")):
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                roots = {alias.name.split(".")[0] for alias in node.names}
                if roots & FORBIDDEN_NETWORK_ROOTS:
                    violations.append(f"{path.name}:{node.lineno}:network")
            elif isinstance(node, ast.ImportFrom) and node.module:
                root = node.module.split(".")[0]
                if root in FORBIDDEN_NETWORK_ROOTS:
                    violations.append(f"{path.name}:{node.lineno}:network")
                if node.module.startswith("lol_build.buildtime"):
                    violations.append(f"{path.name}:{node.lineno}:buildtime")
    assert violations == []
