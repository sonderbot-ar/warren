"""Which reading rules a run was made with (backlog #365).

The reading rules are the code that turns filed and downloaded data into a run's assumption rows:
`facts.py` and `math_engine.py` and every Warren module they import, directly or not
(`rules_modules()`), except the few in NOT_RULES, which compute no value. Every run stores
READING_RULES_VERSION beside its concept map's fingerprint, so two runs of one company and date
that read the filings differently can be told apart even when the map is the same.

The version is bumped by hand, and a test keeps it honest: `rules_fingerprint()` detects a change
to the modules' code (not to their comments, docstrings or layout), and `reading_rules.md` must
list that fingerprint under the current version. A change that can change what a run reads adds a
row with the next version; one that cannot (a rename, a refactor, note wording) adds a row under
the same version and says why.
"""

import ast
import hashlib
import re
from pathlib import Path

READING_RULES_VERSION = 1

REPO_ROOT = Path(__file__).resolve().parents[2]
ROOT_MODULES = (
    "domains/fundamentals/facts.py",
    "domains/analysis/math_engine.py",
)
# Imported by the rules but never change a value: the note plumbing and the warning class.
NOT_RULES = {
    "domains/analysis/coded.py": "run notes as codes and words; no value is computed there",
    "shared_kernel/data_warnings.py": "the warning class only",
    "domains/analysis/reading_rules.py": "the version itself, checked against its log",
}
_PACKAGES = ("domains", "shared_kernel")
LOG_PATH = Path(__file__).with_name("reading_rules.md")

_ROW = re.compile(r"^\|\s*`([0-9a-f]{12})`\s*\|\s*(\d+)\s*\|")
_SKIPPED_FIELDS = {"ctx", "type_comment", "kind"}  # no meaning for what the code does


def _strip_docstrings(tree: ast.AST) -> ast.AST:
    for node in ast.walk(tree):
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            body = node.body
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                node.body = body[1:] or [ast.Pass()]
    return tree


def _canonical(node) -> str:
    """The tree written out with node and field names, leaving out line numbers and empty fields,
    so the same code gives the same text on every Python version Warren supports."""
    if isinstance(node, ast.AST):
        parts = []
        for name in node._fields:
            if name in _SKIPPED_FIELDS:
                continue
            value = getattr(node, name, None)
            if value is None or value == []:
                continue
            parts.append(f"{name}={_canonical(value)}")
        return f"{type(node).__name__}({','.join(parts)})"
    if isinstance(node, list):
        return "[" + ",".join(_canonical(v) for v in node) + "]"
    return repr(node)


def module_fingerprint_text(source: str) -> str:
    """The text a module contributes to the fingerprint: its code without docstrings."""
    return _canonical(_strip_docstrings(ast.parse(source)))


def _imports(path: Path, root: Path) -> set[str]:
    """Warren modules a file imports at its top level (not inside functions), as repo paths."""
    found = set()
    for node in ast.parse(path.read_text(encoding="utf-8")).body:
        names: list[str] = []
        if isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names = [node.module] + [f"{node.module}.{a.name}" for a in node.names]
        elif isinstance(node, ast.Import):
            names = [a.name for a in node.names]
        for name in names:
            if name.split(".")[0] not in _PACKAGES:
                continue
            candidate = root / (name.replace(".", "/") + ".py")
            if candidate.exists():
                found.add(candidate.relative_to(root).as_posix())
    return found


def rules_modules(root: Path = REPO_ROOT) -> tuple[str, ...]:
    """ROOT_MODULES and every Warren module they import, directly or not, minus NOT_RULES;
    sorted. A new import joins the rules by itself."""
    seen: set[str] = set()
    todo = list(ROOT_MODULES)
    while todo:
        module = todo.pop()
        if module in seen:
            continue
        seen.add(module)
        todo.extend(_imports(root / module, root) - seen)
    return tuple(sorted(seen - NOT_RULES.keys()))


def rules_fingerprint(modules: tuple[str, ...] | None = None, root: Path = REPO_ROOT) -> str:
    """SHA-256 of the reading rules' code, module by module in sorted path order."""
    if modules is None:
        modules = rules_modules(root)
    digest = hashlib.sha256()
    for module in sorted(modules):
        text = module_fingerprint_text((root / module).read_text(encoding="utf-8"))
        digest.update(f"{module}\n{text}\n".encode())
    return digest.hexdigest()


def logged_versions(path: Path = LOG_PATH) -> list[tuple[str, int]]:
    """(first 12 characters of a fingerprint, its version) for each row of the log, in order."""
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        match = _ROW.match(line)
        if match:
            rows.append((match.group(1), int(match.group(2))))
    return rows


if __name__ == "__main__":
    print(f"reading rules v{READING_RULES_VERSION}, fingerprint {rules_fingerprint()[:12]}")
    print("modules: " + ", ".join(rules_modules()))
