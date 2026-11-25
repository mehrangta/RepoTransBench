"""Source chunking and dependency-aware retrieval for both adapters."""

import ast
from collections import Counter
import math
import re

CHUNK_BUDGET = 4000


def chunks_for(name, text):
    """Keep complete small functions/methods; split long blocks by lines."""
    lines = text.splitlines(keepends=True)
    tree = ast.parse(text)
    spans = []
    cursor = 1
    for node in tree.body:
        start = min([node.lineno] + [d.lineno for d in getattr(node, "decorator_list", [])])
        if cursor < start:
            spans.append((cursor, start - 1, "module context"))
        if isinstance(node, ast.ClassDef):
            previous = start
            for child in node.body:
                child_start = min(
                    [child.lineno] + [d.lineno for d in getattr(child, "decorator_list", [])]
                )
                if previous < child_start:
                    spans.append((previous, child_start - 1, node.name))
                spans.append(
                    (
                        child_start,
                        child.end_lineno,
                        node.name + "." + getattr(child, "name", "attributes"),
                    )
                )
                previous = child.end_lineno + 1
            if previous <= node.end_lineno:
                spans.append((previous, node.end_lineno, node.name))
        else:
            spans.append((start, node.end_lineno, getattr(node, "name", "module context")))
        cursor = node.end_lineno + 1
    if cursor <= len(lines):
        spans.append((cursor, len(lines), "module context"))
    result = []
    for start, end, symbol in spans:
        # Limit individual chunks so one long function cannot occupy the budget.
        position = start
        while position <= end:
            stop = position
            size = 0
            while stop <= end and (size + len(lines[stop - 1]) <= 1600 or stop == position):
                size += len(lines[stop - 1])
                stop += 1
            content = "".join(lines[position - 1 : stop - 1])
            result.append(
                dict(
                    id=f"{name}:{position}-{stop-1}",
                    path=name,
                    symbol=symbol,
                    start=position,
                    end=stop - 1,
                    text=content,
                )
            )
            position = stop
    return result


def words(text):
    # Also split snake_case identifiers; stable local retrieval, no embedding API.
    raw = re.findall(r"[A-Za-z][A-Za-z_0-9]+", text.lower())
    stop = {"const", "std", "string", "include", "test", "public", "class", "return", "void", "int"}
    return Counter(
        w for token in raw for w in [token, *token.split("_")] if len(w) > 2 and w not in stop
    )


def identifiers(text):
    return {
        w
        for w in re.findall(r"[A-Za-z_][A-Za-z_0-9]*", text)
        if len(w) > 2
        and w not in {"the", "and", "for", "with", "return", "void", "int", "class", "public"}
    }


def chunk_entities(chunk):
    if "definitions" in chunk and "calls" in chunk:
        return set(chunk["definitions"]), set(chunk["calls"])
    text = chunk["text"]
    definitions = set(re.findall(r"\b(?:def|class)\s+([A-Za-z_]\w*)", text))
    definitions.update(re.findall(r"(?m)^\s*([A-Za-z_]\w*)\s*=\s*", text))
    calls = set(re.findall(r"\b([A-Za-z_]\w*)\s*\(", text))
    symbol = chunk.get("symbol", "")
    if symbol:
        definitions.add(symbol.split(".")[-1])
    return definitions, calls


def lexical_score(chunk, query_words, document_frequency, total):
    terms = words(chunk["text"] + " " + chunk.get("symbol", ""))
    return sum(
        min(n, 3) * math.log(1 + total / (1 + document_frequency[w])) * min(terms[w], 3)
        for w, n in query_words.items()
        if terms[w]
    ) / math.sqrt(1 + len(chunk["text"]) / 800)


def greedy_entity_use_chunks(chunks, query, budget=CHUNK_BUDGET):
    """RAMBO/SaraCoder-inspired symbol and dependency-aware bounded selection."""
    query_ids = identifiers(query)
    query_words = words(query)
    document_frequency = Counter(
        w for chunk in chunks for w in set(words(chunk["text"] + " " + chunk.get("symbol", "")))
    )
    entities = {id(chunk): chunk_entities(chunk) for chunk in chunks}
    ranked = []
    for chunk in chunks:
        definitions, calls = entities[id(chunk)]
        exact = len((definitions | calls) & query_ids)
        score = lexical_score(chunk, query_words, document_frequency, len(chunks))
        ranked.append((-(exact * 8 + score), chunk["path"], chunk["start"], chunk))
    ranked.sort()

    selected, selected_ids, used = [], set(), 0

    def add(chunk, reason):
        nonlocal used
        if id(chunk) in selected_ids or used + len(chunk["text"]) > budget:
            return False
        selected.append((chunk, reason))
        selected_ids.add(id(chunk))
        used += len(chunk["text"])
        return True

    # Keep imports and module-level setup when they fit.
    for _, _, _, chunk in ranked:
        if "module context" in chunk.get("symbol", "").lower() and len(chunk["text"]) < 900:
            add(chunk, "module/import context")

    # Seed with direct symbol and lexical matches.
    for _, _, _, chunk in ranked:
        definitions, calls = entities[id(chunk)]
        overlap = (definitions | calls) & query_ids
        add(chunk, "query symbol" if overlap else "lexical seed")
        if used >= budget:
            break

    # Add one-hop definitions and usages for the symbols already selected.
    closure = set(query_ids)
    for chunk, _ in selected:
        definitions, calls = entities[id(chunk)]
        closure.update(definitions)
        closure.update(calls)
    dependency_candidates = []
    for _, _, _, chunk in ranked:
        definitions, calls = entities[id(chunk)]
        overlap = len(definitions & closure) * 6 + len(calls & closure) * 2
        if overlap:
            dependency_candidates.append((-overlap, chunk["path"], chunk["start"], chunk))
    for _, _, _, chunk in sorted(dependency_candidates):
        add(chunk, "one-hop symbol dependency")
        if used >= budget:
            break
    return sorted(selected, key=lambda pair: (pair[0]["path"], pair[0]["start"])), used


DEPENDENCY_RESERVE = 1000


def entity_use_chunks(chunks, query, budget=CHUNK_BUDGET):
    """Reserve one quarter of the 4,000-char source field for one-hop context.

    Ranking, chunk boundaries, entity extraction and the total budget are the
    frozen combined method's. Only the order in which capacity is allocated
    changes. Unused seed capacity is also available to whole dependency chunks.
    """
    reserve = min(DEPENDENCY_RESERVE, budget // 4)
    seed_limit = budget - reserve
    query_ids, query_words = identifiers(query), words(query)
    frequency = Counter(
        w for chunk in chunks for w in set(words(chunk["text"] + " " + chunk.get("symbol", "")))
    )
    entities = {id(chunk): chunk_entities(chunk) for chunk in chunks}
    ranked = []
    for chunk in chunks:
        definitions, calls = entities[id(chunk)]
        exact = len((definitions | calls) & query_ids)
        score = lexical_score(chunk, query_words, frequency, len(chunks))
        ranked.append((-(exact * 8 + score), chunk["path"], chunk["start"], chunk))
    ranked.sort()
    selected, selected_ids, used = [], set(), 0

    def add(chunk, reason, limit):
        nonlocal used
        if id(chunk) in selected_ids or used + len(chunk["text"]) > limit:
            return False
        selected.append((chunk, reason))
        selected_ids.add(id(chunk))
        used += len(chunk["text"])
        return True

    for _, _, _, chunk in ranked:
        if "module context" in chunk.get("symbol", "").lower() and len(chunk["text"]) < 900:
            add(chunk, "module/import context", seed_limit)
    for _, _, _, chunk in ranked:
        definitions, calls = entities[id(chunk)]
        add(
            chunk,
            "query symbol" if (definitions | calls) & query_ids else "lexical seed",
            seed_limit,
        )

    # Freeze the one-hop frontier after seeding; do not expand it recursively.
    closure = set(query_ids)
    for chunk, _ in selected:
        definitions, calls = entities[id(chunk)]
        closure.update(definitions)
        closure.update(calls)
    dependencies = []
    for _, _, _, chunk in ranked:
        definitions, calls = entities[id(chunk)]
        overlap = len(definitions & closure) * 6 + len(calls & closure) * 2
        if overlap:
            dependencies.append((-overlap, chunk["path"], chunk["start"], chunk))
    added = 0
    for _, _, _, chunk in sorted(dependencies):
        added += add(chunk, "one-hop symbol dependency", budget)
    if not added:
        return greedy_entity_use_chunks(chunks, query, budget)
    # Return capacity unused by whole dependencies to ordinary ranked chunks.
    for _, _, _, chunk in ranked:
        add(chunk, "lexical backfill", budget)
    return sorted(selected, key=lambda pair: (pair[0]["path"], pair[0]["start"])), used
