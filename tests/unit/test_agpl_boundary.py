"""Enforce the AGPL boundary described in ADR-0013.

Slither and crytic-compile are AGPL-3.0. The commercial product runs Slither as
an unmodified, out-of-process executable and reads its JSON output. Nothing in
this repository may import, vendor or patch it, because doing so would make our
own source a derivative work of AGPL code.

These tests are the guard rail. A future contributor who adds
``import slither`` to make something easier should fail here rather than
discover the problem during a licence review.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

#: Directories that hold code we ship.
SOURCE_ROOTS = ("apps", "packages", "scripts")

#: Directories that are not ours to police (they are third-party or generated).
EXCLUDED_PARTS = frozenset(
    {
        ".venv",
        "node_modules",
        ".next",
        ".git",
        "__pycache__",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        "var",
        "dist",
        "build",
    }
)

#: AGPL-licensed packages that must never be imported by our own code.
FORBIDDEN_IMPORTS = ("slither", "crytic_compile", "crytic")

#: A Python import of a forbidden package, in any of the forms Python allows.
IMPORT_PATTERN = re.compile(
    r"^\s*(?:import\s+(?P<import>[A-Za-z_][\w.]*)|from\s+(?P<from>[A-Za-z_][\w.]*)\s+import)",
    re.MULTILINE,
)


def _python_sources() -> list[Path]:
    """Every Python file we ship."""
    files: list[Path] = []
    for root in SOURCE_ROOTS:
        base = REPO_ROOT / root
        if not base.is_dir():
            continue
        for path in base.rglob("*.py"):
            if EXCLUDED_PARTS & set(path.parts):
                continue
            files.append(path)
    return sorted(files)


def test_there_are_python_sources_to_check() -> None:
    """Guard against the scan silently finding nothing."""
    assert len(_python_sources()) > 50, "the source scan found suspiciously few files"


@pytest.mark.parametrize("path", _python_sources(), ids=lambda p: str(p.relative_to(REPO_ROOT)))
def test_no_forbidden_imports(path: Path) -> None:
    """No file we ship may import Slither or crytic-compile."""
    text = path.read_text(encoding="utf-8", errors="replace")
    for match in IMPORT_PATTERN.finditer(text):
        module = match.group("import") or match.group("from") or ""
        root = module.split(".")[0]
        assert root not in FORBIDDEN_IMPORTS, (
            f"{path.relative_to(REPO_ROOT)} imports {module!r}. Slither and "
            "crytic-compile are AGPL-3.0 and must be run as an external "
            "executable, never imported. See ADR-0013."
        )


def test_no_vendored_agpl_source() -> None:
    """No AGPL source may be vendored into the repository."""
    forbidden_names = {"slither", "crytic_compile", "crytic"}
    for root in SOURCE_ROOTS:
        base = REPO_ROOT / root
        if not base.is_dir():
            continue
        for path in base.rglob("*"):
            if not path.is_dir():
                continue
            if EXCLUDED_PARTS & set(path.parts):
                continue
            assert path.name.lower() not in forbidden_names, (
                f"{path.relative_to(REPO_ROOT)} looks like vendored AGPL source. "
                "See ADR-0013."
            )


#: A string literal, in any of the forms Python allows.
STRING_LITERAL_PATTERN = re.compile(
    r"\"\"\".*?\"\"\"" r"|\'\'\'.*?\'\'\'" r"|\"[^\"\\\n]*\"" r"|\'[^\'\\\n]*\'",
    re.DOTALL,
)

#: A comment, in either the hash or the triple-quoted form.
COMMENT_PATTERN = re.compile(r"#[^\n]*|\"\"\".*?\"\"\"", re.DOTALL)

#: A dynamic import, which would evade the import pattern above.
DYNAMIC_IMPORT_PATTERN = re.compile(
    r"import_module\(\s*[\"\'](?P<module>[\w.]+)[\"\']"
    r"|__import__\(\s*[\"\'](?P<direct>[\w.]+)[\"\']"
)


def _code_only(text: str) -> str:
    """Return the text with its string literals and comments removed.

    A mention of Slither inside a string -- a database constraint value, an
    environment variable name, a command line -- is data, not an import of
    AGPL code. Only a mention in *code* matters for this check.
    """
    without_strings = STRING_LITERAL_PATTERN.sub(" ", text)
    return COMMENT_PATTERN.sub(" ", without_strings)


def test_slither_is_never_imported_dynamically() -> None:
    """A dynamic import must not become a way around the import check."""
    offenders: list[str] = []
    for path in _python_sources():
        text = path.read_text(encoding="utf-8", errors="replace")
        for match in DYNAMIC_IMPORT_PATTERN.finditer(text):
            module = match.group("module") or match.group("direct") or ""
            if module.split(".")[0] in FORBIDDEN_IMPORTS:
                offenders.append(f"{path.relative_to(REPO_ROOT)} ({module})")
    assert not offenders, (
        "these files import a forbidden module dynamically: "
        + ", ".join(offenders)
        + ". See ADR-0013."
    )


def test_slither_is_invoked_only_as_a_subprocess() -> None:
    """If we use Slither in code, we do it by running the executable.

    A mention in *code* rather than in a string is what matters here: a
    database constraint that stores the word "slither" as a finding source
    is data, not an invocation.
    """
    offenders: list[str] = []
    for path in _python_sources():
        text = path.read_text(encoding="utf-8", errors="replace")
        if "slither" not in _code_only(text).lower():
            continue
        if "subprocess" not in text and "AGPL" not in text and "ADR-0013" not in text:
            offenders.append(str(path.relative_to(REPO_ROOT)))
    assert not offenders, (
        "these files use Slither in code without using subprocess: "
        + ", ".join(offenders)
        + ". Slither must be invoked as an external executable."
    )
