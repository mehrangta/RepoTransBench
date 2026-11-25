"""Bounded repair feedback from C++ validation and current files."""

from pathlib import Path
import re

SKIP = {
    "test",
    "tests",
    "public_tests",
    "build",
    "build-public",
    "CMakeFiles",
    ".git",
    ".baseline-evaluation",
    "__pycache__",
}


def packet_files(root):
    root = Path(root)
    files = {}
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root)
        if (
            not path.is_file()
            or path.is_symlink()
            or set(rel.parts) & (SKIP - {"test", "tests", "public_tests"})
            or path.stat().st_size > 200000
        ):
            continue
        try:
            files[rel.as_posix()] = path.read_text()
        except (UnicodeError, OSError):
            continue
    return files


def repair_packet(output, root, limit=3100, files=None):
    """First failure + exact file location + related current definitions."""
    root = Path(root).resolve()
    lines = output.splitlines()
    files = packet_files(root) if files is None else files
    hits = [
        i
        for i, s in enumerate(lines)
        if re.search(r"error|undefined|not found|fail|assert|exception|Expected:|Actual:", s, re.I)
    ]
    if not hits:
        return "", []
    keep = set()
    for i in hits[:3]:
        keep.update(range(max(0, i - 1), min(len(lines), i + 5)))
    diagnostic = "\n".join(lines[i] for i in sorted(keep))[:1300]
    locations = []
    snippets = []
    seen = set()
    for match in re.finditer(r"([\w./+\-]+):([0-9]+)(?::[0-9]+)?", diagnostic):
        name = match[1]
        line = int(match[2])
        path = Path(name)
        if not path.is_absolute():
            path = root / path
        try:
            rel = path.resolve().relative_to(root).as_posix()
        except ValueError:
            continue
        if rel in seen or rel not in files:
            continue
        seen.add(rel)
        body = files[rel].splitlines()
        start = max(0, line - 4)
        stop = min(len(body), line + 3)
        locations.append(dict(path=rel, start=start + 1, end=stop, reason="diagnostic location"))
        snippets.append(
            "FILE " + rel + "\n" + "\n".join(f"{i+1}: {body[i]}" for i in range(start, stop))
        )
        if len(locations) >= 2:
            break
    identifiers = {
        w
        for w in re.findall(r"[A-Za-z_]\w{2,}", diagnostic)
        if w
        not in {"error", "warning", "candidate", "note", "function", "include", "public", "tests"}
    }
    ranked = []
    for rel, content in sorted(files.items()):
        if rel in seen or set(Path(rel).parts) & SKIP:
            continue
        body = content.splitlines()
        scores = [len(set(re.findall(r"[A-Za-z_]\w{2,}", s)) & identifiers) for s in body]
        if scores and max(scores) >= 2:
            pos = max(range(len(scores)), key=scores.__getitem__)
            ranked.append((-scores[pos], rel, pos, body))
    for _, rel, pos, body in sorted(ranked)[:2]:
        start = max(0, pos - 2)
        stop = min(len(body), pos + 5)
        locations.append(
            dict(path=rel, start=start + 1, end=stop, reason="related identifier overlap")
        )
        snippets.append(
            "FILE " + rel + "\n" + "\n".join(f"{i+1}: {body[i]}" for i in range(start, stop))
        )
    return (
        "ACTUAL VALIDATION FAILURE\n"
        + diagnostic
        + "\nCURRENT CODE AT FAILURE / RELATED LOCATIONS\n"
        + "\n\n".join(snippets)
    )[:limit], locations
