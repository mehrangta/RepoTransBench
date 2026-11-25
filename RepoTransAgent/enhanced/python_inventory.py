"""Python inventory and complete-body scheduling, without importing source code."""

import ast
import copy
import hashlib


def inventory_sources(sources, group_target=3500):
    if group_target <= 0:
        raise ValueError("group_target must be positive")
    units, modules, classes, catalog = [], [], [], []
    names = set()
    for path, text in sources:
        if path in names:
            raise ValueError(f"duplicate source path: {path}")
        names.add(path)
        # A few upstream repositories contain a UTF-8 BOM.  It is encoding
        # metadata rather than Python syntax; strip it only for parsing so the
        # original text, character counts, and hashes remain unchanged.
        # Some older projects are Python 2 sources and cannot be parsed by the
        # Python 3 AST.  Keep those files in the module inventory and continue
        # with the files that can be structurally parsed.
        try:
            tree = ast.parse(text.lstrip("\ufeff"), filename=path)
        except SyntaxError as exc:
            modules.append(
                dict(
                    path=path,
                    sha256=hashlib.sha256(text.encode()).hexdigest(),
                    characters=len(text),
                    imports=[],
                    parse_error=f"{exc.msg} at line {exc.lineno}",
                )
            )
            catalog.append(f"MODULE {path}\n# AST unavailable: {exc.msg} at line {exc.lineno}")
            continue
        lines = text.splitlines(keepends=True)
        imports = []
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                imports.append(dict(line=node.lineno, statement=ast.unparse(node)))
        modules.append(
            dict(
                path=path,
                sha256=hashlib.sha256(text.encode()).hexdigest(),
                characters=len(text),
                imports=imports,
            )
        )

        def scope(nodes, owner=""):
            for node in nodes:
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    start = min([node.lineno] + [d.lineno for d in node.decorator_list])
                    symbol = f"{owner}.{node.name}" if owner else node.name
                    fields = []
                    for child in ast.walk(node):
                        targets = (
                            child.targets
                            if isinstance(child, ast.Assign)
                            else [child.target] if isinstance(child, ast.AnnAssign) else []
                        )
                        for target in targets:
                            if (
                                isinstance(target, ast.Attribute)
                                and isinstance(target.value, ast.Name)
                                and target.value.id in {"self", "cls"}
                            ):
                                fields.append(
                                    dict(
                                        name=target.attr,
                                        line=child.lineno,
                                        value=ast.unparse(child.value) if child.value else None,
                                    )
                                )
                    units.append(
                        dict(
                            id=f"{path}:{start}:{symbol}",
                            path=path,
                            symbol=symbol,
                            name=node.name,
                            owner=owner,
                            start=start,
                            end=node.end_lineno,
                            signature=f"{node.name}({ast.unparse(node.args)})",
                            returns=ast.unparse(node.returns) if node.returns else None,
                            decorators=[ast.unparse(d) for d in node.decorator_list],
                            fields=fields,
                            calls=sorted(
                                {
                                    ast.unparse(n.func)
                                    for n in ast.walk(node)
                                    if isinstance(n, ast.Call)
                                }
                            ),
                            text="".join(lines[start - 1 : node.end_lineno]),
                        )
                    )
                    # Nested functions remain inside the enclosing complete body.
                elif isinstance(node, ast.ClassDef):
                    name = f"{owner}.{node.name}" if owner else node.name
                    classes.append(
                        dict(
                            path=path,
                            name=name,
                            line=node.lineno,
                            bases=[ast.unparse(b) for b in node.bases],
                        )
                    )
                    scope(node.body, name)
                else:
                    # Definitions under module/class if/try/with retain their scope.
                    children = []
                    for _, value in ast.iter_fields(node):
                        if isinstance(value, list):
                            children.extend(n for n in value if isinstance(n, ast.stmt))
                            for handler in value:
                                if isinstance(handler, ast.ExceptHandler):
                                    children.extend(handler.body)
                    scope(children, owner)

        scope(tree.body)

        class Declarations(ast.NodeTransformer):
            def visit_FunctionDef(self, node):
                node.body = [ast.Pass()]
                return node

            visit_AsyncFunctionDef = visit_FunctionDef

        catalog.append(f"MODULE {path}\n" + ast.unparse(Declarations().visit(copy.deepcopy(tree))))
    groups, current, size = [], [], 0
    for unit in units:
        if current and size + len(unit["text"]) > group_target:
            groups.append(current)
            current, size = [], 0
        current.append(unit["id"])
        size += len(unit["text"])
    if current:
        groups.append(current)
    steps = [dict(id=f"body-{i+1:02d}", unit_ids=g) for i, g in enumerate(groups)]
    return dict(
        schema_version=1,
        modules=modules,
        classes=classes,
        units=units,
        body_steps=steps,
        catalog="\n\n".join(catalog),
        group_target_chars=group_target,
        dependency_note="Calls/imports are syntactic evidence; dynamic dispatch and dependencies are not resolved.",
    )
