"""Offline JavaScript syntax adapter; never executes repository code."""

from pathlib import Path
import re

from tree_sitter import Language, Parser
import tree_sitter_javascript

PARSER = Parser(Language(tree_sitter_javascript.language()))
SKIP = {
    "test",
    "tests",
    "public_tests",
    "docs",
    "examples",
    "example",
    "build",
    "dist",
    "node_modules",
    "coverage",
    "vendor",
}
FUNCTIONS = {
    "function_declaration",
    "function_expression",
    "generator_function_declaration",
    "generator_function",
    "arrow_function",
    "method_definition",
}


def sources(root, excluded=()):
    root = Path(root)
    excluded = set(excluded)
    out = []
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root)
        if (
            not path.is_file()
            or path.is_symlink()
            or path.suffix not in {".js", ".jsx", ".mjs", ".cjs"}
            or rel.as_posix() in excluded
            or any(p in SKIP or p.startswith(".") for p in rel.parts[:-1])
            or re.search(r"(?:^test[_.-]|[._-](?:test|spec)\.[^.]+$)", path.name)
        ):
            continue
        out.append((rel.as_posix(), path.read_text(errors="replace")))
    return out


def inspect(name, text):
    raw = text.encode()
    tree = PARSER.parse(raw)
    units = []
    imports = []
    exports = []
    classes = []
    issues = []

    def content(node):
        return raw[node.start_byte : node.end_byte].decode(errors="replace") if node else ""

    def walk(node, owner=""):
        if node.type == "ERROR" or node.is_missing:
            issues.append(dict(line=node.start_point.row + 1, kind=node.type))
        if node.type in {"import_statement"}:
            imports.append(content(node)[:500])
        if (
            node.type == "call_expression"
            and content(node.child_by_field_name("function")) == "require"
        ):
            imports.append(content(node)[:500])
        if node.type == "export_statement":
            exports.append(content(node).split("\n", 1)[0][:300])
        if node.type == "assignment_expression":
            left = content(node.child_by_field_name("left"))
            if left.startswith(("module.exports", "exports.")):
                exports.append(left)
        next_owner = owner
        if node.type in {"class_declaration", "class"}:
            label = content(node.child_by_field_name("name")) or "<anonymous class>"
            classes.append(dict(path=name, line=node.start_point.row + 1, name=label))
            next_owner = owner + "." + label if owner else label
        if node.type in FUNCTIONS:
            label = content(node.child_by_field_name("name"))
            parent = node.parent
            if (
                not label
                and parent
                and parent.type in {"variable_declarator", "pair", "assignment_expression"}
            ):
                label = content(
                    parent.child_by_field_name("name")
                    or parent.child_by_field_name("key")
                    or parent.child_by_field_name("left")
                )
            label = label or "<anonymous@" + str(node.start_point.row + 1) + ">"
            params = node.child_by_field_name("parameters") or node.child_by_field_name("parameter")
            body = node.child_by_field_name("body")
            calls = set()
            fields = set()

            def evidence(child):
                if child != node and child.type in FUNCTIONS:
                    return
                if child.type == "call_expression":
                    calls.add(content(child.child_by_field_name("function"))[:120])
                if child.type == "assignment_expression":
                    left = content(child.child_by_field_name("left"))
                    if left.startswith("this."):
                        fields.add(left)
                for descendant in child.named_children:
                    evidence(descendant)

            evidence(node)
            symbol = owner + "." + label if owner else label
            units.append(
                dict(
                    path=name,
                    symbol=symbol,
                    name=label,
                    owner=owner,
                    line=node.start_point.row + 1,
                    end_line=node.end_point.row + 1,
                    start_byte=node.start_byte,
                    end_byte=node.end_byte,
                    signature=label + content(params),
                    calls=sorted(calls),
                    fields=sorted(fields),
                    async_function=content(node).lstrip().startswith("async "),
                )
            )
            next_owner = symbol
        for child in node.named_children:
            walk(child, next_owner)

    walk(tree.root_node)
    chunks = []
    lines = text.splitlines(keepends=True)
    spans = []
    cursor = 1
    # Keep top-level declarations intact when small. Split large spans by lines.
    # Same-line statements are coalesced so no source line is duplicated.
    for node in tree.root_node.named_children:
        start = max(cursor, node.start_point.row + 1)
        end = node.end_point.row + 1
        if start > end:
            continue
        if cursor < start:
            spans.append((cursor, start - 1, "module context"))
        contained = [
            u
            for u in units
            if node.start_byte <= u["start_byte"] and u["end_byte"] <= node.end_byte
        ]
        label = contained[0]["symbol"] if contained else "module context"
        spans.append((start, end, label))
        cursor = end + 1
    if cursor <= len(lines):
        spans.append((cursor, len(lines), "module context"))
    for start, end, label in spans:
        position = start
        while position <= end:
            stop = position
            size = 0
            while stop <= end and (size + len(lines[stop - 1]) <= 1600 or stop == position):
                size += len(lines[stop - 1])
                stop += 1
            fragment = "".join(lines[position - 1 : stop - 1])
            definitions = [u["name"].split(".")[-1] for u in units if position <= u["line"] < stop]
            chunks.append(
                dict(
                    id=f"{name}:{position}-{stop-1}",
                    path=name,
                    start=position,
                    end=stop - 1,
                    symbol=label,
                    text=fragment,
                    definitions=definitions,
                    calls=sorted(set(re.findall(r"\b([A-Za-z_$][\w$]*)\s*\(", fragment))),
                )
            )
            position = stop
    return dict(
        path=name,
        characters=len(text),
        units=units,
        imports=sorted(set(imports)),
        exports=sorted(set(exports)),
        classes=classes,
        parse_issues=issues,
        chunks=chunks,
    )


def make_inputs(project, source_files):
    modules = [inspect(path, text) for path, text in source_files]
    lines = [
        f"PROJECT: {project}",
        "TARGET: Python",
        "Source-derived JavaScript contract. No target implementation or evaluation result is used.",
        "MODULES:",
    ]
    for m in modules:
        lines.append(f'- {m["path"]} ({m["characters"]} chars)')
        lines.extend("  import: " + x for x in m["imports"])
        lines.extend("  export: " + x for x in m["exports"])
    lines.append("CLASSES:")
    for m in modules:
        lines.extend(f'- {m["path"]}:{c["line"]} {c["name"]}' for c in m["classes"])
    lines.append("SOURCE UNITS:")
    for m in modules:
        for u in m["units"]:
            lines.append(
                f'- id={m["path"]}::{u["symbol"]} owner={u["owner"] or "module"} signature={u["signature"]}'
            )
            lines.append("  fields=" + ", ".join(u["fields"]) + "; calls=" + ", ".join(u["calls"]))
    lines += [
        "OWNERSHIP RULES:",
        "- Preserve public names, defaults, fields, exports and callable behavior.",
        "- Keep definitions and imports consistent across translated files.",
        "- Implement source helpers and preserve observable behavior.",
        "- Run the supplied test command before reporting success.",
    ]
    return dict(
        project=project,
        source_files=[n for n, _ in source_files],
        source_chars=sum(len(t) for _, t in source_files),
        chunks=[c for m in modules for c in m["chunks"]],
        modules=modules,
        contract=("\n".join(lines) + "\n")[:30000],
        parse_issues=[
            dict(path=m["path"], **issue) for m in modules for issue in m["parse_issues"]
        ],
    )
