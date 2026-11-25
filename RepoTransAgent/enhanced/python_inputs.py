"""Prepare the Python source chunks and persistent contract offline."""

from .python_inventory import inventory_sources
from .source_chunks import chunks_for


def source_files(base, excluded):
    excluded = set(excluded)
    skip = {
        "test",
        "tests",
        "public_tests",
        "docs",
        "examples",
        "example",
        "build",
        "dist",
        "__pycache__",
    }
    return [
        (p.relative_to(base).as_posix(), p.read_text(encoding="utf-8", errors="replace"))
        for p in sorted(base.rglob("*.py"))
        if p.relative_to(base).as_posix() not in excluded
        and not any(x in skip or x.startswith(".") for x in p.relative_to(base).parts[:-1])
        and p.name not in {"setup.py", "conftest.py", "tests.py", "extra_tests.py"}
        and not p.name.startswith("test_")
    ]


def legacy_chunks(name, text):
    result, current, position = [], "", 1
    for number, line in enumerate(text.splitlines(keepends=True), 1):
        if current and len(current) + len(line) > 1600:
            result.append(
                dict(
                    id=f"{name}:{position}-{number-1}",
                    path=name,
                    symbol="unparsed block",
                    start=position,
                    end=number - 1,
                    text=current,
                )
            )
            current, position = "", number
        current += line
    if current:
        result.append(
            dict(
                id=f"{name}:{position}-{number}",
                path=name,
                symbol="unparsed block",
                start=position,
                end=number,
                text=current,
            )
        )
    return result


def contract_text(project, sources):
    inventory = inventory_sources(sources, group_target=3500)
    lines = [
        f"PROJECT: {project}",
        "TARGET: C++17",
        "This source-derived contract contains no target reference implementation.",
        "",
        "MODULES:",
    ]
    for module in inventory["modules"]:
        lines.append(f'- {module["path"]} ({module["characters"]} chars)')
        lines.extend("  import: " + item["statement"] for item in module["imports"])
    lines += ["", "CLASSES:"]
    lines.extend(
        f'- {item["path"]}:{item["line"]} {item["name"]} bases={", ".join(item["bases"]) or "none"}'
        for item in inventory["classes"]
    )
    lines += ["", "SOURCE UNITS (each requires a consistent declaration and definition):"]
    for unit in inventory["units"]:
        fields = ", ".join(f'{f["name"]}={f["value"]}' for f in unit["fields"]) or "none"
        calls = ", ".join(unit["calls"]) or "none"
        lines.append(
            f'- id={unit["id"]} owner={unit["owner"] or "module"} signature={unit["signature"]} returns={unit["returns"] or "unspecified"}'
        )
        lines.append(
            f'  decorators={", ".join(unit["decorators"]) or "none"}; fields={fields}; calls={calls}'
        )
    lines += [
        "",
        "OWNERSHIP RULES:",
        "- Preserve public names, defaults, fields, and callable behavior.",
        "- Keep declarations and definitions consistent across generated C++ files.",
        "- Define helpers required by the source, even when they are not top-level Python units.",
        "- Run the supplied build and tests before reporting success.",
    ]
    return ("\n".join(lines) + "\n")[:30000]


def make_inputs(project, root, excluded):
    sources = source_files(root, excluded)
    chunks = []
    parse_issues = []
    for name, text in sources:
        try:
            chunks.extend(chunks_for(name, text))
        except (SyntaxError, ValueError) as error:
            parse_issues.append(dict(path=name, reason=str(error)))
            chunks.extend(legacy_chunks(name, text))
    return dict(
        source_files=[name for name, _ in sources],
        source_chars=sum(len(text) for _, text in sources),
        chunks=chunks,
        parse_issues=parse_issues,
        contract=contract_text(project, sources),
    )
