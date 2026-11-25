"""Python target adapter for the measured file-manifest policy."""

from pathlib import Path
import json
import re

FILENAME = "translation_manifest.json"
FORBIDDEN = {
    "test",
    "tests",
    "public_tests",
    "build",
    ".git",
    ".baseline-evaluation",
    "__pycache__",
}


def validate(raw, root, protected):
    if (
        not isinstance(raw, dict)
        or not isinstance(raw.get("modules"), list)
        or not 1 <= len(raw["modules"]) <= 32
    ):
        raise ValueError("Provide 1 to 32 implementation filenames in modules")
    modules = []
    root = Path(root).resolve()
    for name in raw["modules"]:
        if (
            not isinstance(name, str)
            or not re.fullmatch(r"[A-Za-z0-9_./\-]+\.py", name)
            or Path(name).is_absolute()
        ):
            raise ValueError("Expected a relative Python implementation path")
        rel = (root / name).resolve().relative_to(root).as_posix()
        if rel in protected or set(Path(rel).parts) & FORBIDDEN:
            raise ValueError("Protected or test path: " + rel)
        modules.append(rel)
    if len(set(modules)) != len(modules):
        raise ValueError("Duplicate module path")
    return dict(modules=sorted(modules))


def sync(plan, root):
    """Create declared files and package markers; never replace existing bodies."""
    root = Path(root).resolve()
    created = []
    for name in plan["modules"]:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_text("")
            created.append(name)
        for parent in path.parents:
            if parent == root:
                break
            marker = parent / "__init__.py"
            if not marker.exists():
                marker.write_text("")
                created.append(marker.relative_to(root).as_posix())
    return created


def note(plan):
    if plan is None:
        return (
            'DETERMINISTIC MODULE MANIFEST. First use CreateFile(filepath="'
            + FILENAME
            + '") with fenced JSON. '
            'Schema: {"modules":["src/package/__init__.py","src/package/helpers.py"]}. '
            "Choose the exact paths required by the documented structure and public interfaces. "
            "The controller creates missing empty files and package __init__.py markers. "
            "Implement every real body. Update this JSON when adding files. "
            "Feedback uses bash run_tests.sh, the supplied runner. Planning consumes the same 20-request budget."
        )
    return (
        "MODULE MANIFEST ACTIVE. Implement every planned module. Empty files are placeholders, not implementations. "
        "Keep imports consistent. Update " + FILENAME + " to add or rename modules. "
        "Use bash run_tests.sh. Plan: " + json.dumps(plan)
    )
