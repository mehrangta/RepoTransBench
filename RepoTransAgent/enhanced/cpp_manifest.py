"""Build manifest and CMake assembly for Python to C++."""

from pathlib import Path
import re

CPP = {".cpp", ".cc", ".cxx"}
HEADERS = {".h", ".hh", ".hpp", ".hxx"}
SKIP = {
    "tests",
    "test",
    "public_tests",
    "build",
    "build-public",
    "CMakeFiles",
    ".git",
    ".baseline-evaluation",
}


def relative(root, name):
    path = Path(name)
    try:
        return (root / path).resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return None


def mutable_path(root, name, protected, suffixes=None):
    if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9_./+\-]+", name):
        raise ValueError("Expected a simple project-relative path")
    rel = relative(root, name)
    if not rel or rel == "." or Path(name).is_absolute() or rel in protected:
        raise ValueError("Protected or external path: " + str(name))
    if set(Path(rel).parts) & SKIP:
        raise ValueError("Build/test directories cannot own generated files")
    if suffixes and Path(rel).suffix not in suffixes:
        raise ValueError("Unexpected file extension: " + rel)
    return rel


def manifest_plan(raw, root, protected):
    if (
        not isinstance(raw, dict)
        or not isinstance(raw.get("sources"), list)
        or not isinstance(raw.get("headers"), list)
    ):
        raise ValueError("Provide sources and headers arrays of relative filenames")
    sources = sorted({mutable_path(root, n, protected, CPP) for n in raw["sources"]})
    headers = sorted({mutable_path(root, n, protected, HEADERS) for n in raw["headers"]})
    if len(sources) > 32 or len(headers) > 32 or not sources + headers:
        raise ValueError("Manifest needs generated files, with at most 32 per kind")
    allowed = {"pthread", "z", "dl", "m", "curl", "ssl", "crypto", "sqlite3", "fmt", "uuid"}
    libraries = raw.get("libraries", [])
    if not isinstance(libraries, list) or not set(libraries) <= allowed:
        raise ValueError("Unsupported library; allowed: " + ",".join(sorted(allowed)))
    if "CMakeLists.txt" in protected:
        raise ValueError("The supplied CMakeLists is protected")
    return dict(sources=sources, headers=headers, libraries=sorted(set(libraries)))


def render_cmake(plan, runner):
    include_dirs = sorted({".", "include", "src", *(str(Path(p).parent) for p in plan["headers"])})
    lines = [
        "cmake_minimum_required(VERSION 3.16)",
        "project(translated_repo LANGUAGES CXX)",
        "set(CMAKE_CXX_STANDARD 17)",
        "set(CMAKE_CXX_STANDARD_REQUIRED ON)",
        "set(CMAKE_CXX_EXTENSIONS OFF)",
        "find_package(GTest REQUIRED)",
        "find_package(Threads REQUIRED)",
        "enable_testing()",
    ]
    if plan["sources"]:
        lines += [
            "add_library(translated STATIC "
            + " ".join('"' + p + '"' for p in plan["sources"])
            + ")"
        ]
        visibility = "PUBLIC"
    else:
        lines += ["add_library(translated INTERFACE)"]
        visibility = "INTERFACE"
    lines += [
        "target_include_directories(translated "
        + visibility
        + " "
        + " ".join('"${CMAKE_CURRENT_SOURCE_DIR}/' + p + '"' for p in include_dirs)
        + ")"
    ]
    if plan["libraries"]:
        lines += [
            "target_link_libraries(translated "
            + visibility
            + " "
            + " ".join(plan["libraries"])
            + ")"
        ]
    lines += [
        'file(GLOB_RECURSE ORIGINAL_TESTS CONFIGURE_DEPENDS "tests/*.cpp")',
        'file(GLOB_RECURSE PUBLIC_TESTS CONFIGURE_DEPENDS "public_tests/*.cpp")',
    ]
    commands = list(dict.fromkeys(re.findall(r"\./(?:[A-Za-z0-9_.-]+/)*([A-Za-z_]\w*)\b", runner)))
    commands = [c for c in commands if c != "run_tests"] or ["test_runner"]
    for command in commands:
        group = "${PUBLIC_TESTS}" if "public" in command else "${ORIGINAL_TESTS}"
        if len(commands) == 1:
            group = "${ORIGINAL_TESTS} ${PUBLIC_TESTS}"
        lines += [
            "add_executable(" + command + " " + group + ")",
            "target_link_libraries("
            + command
            + " PRIVATE translated GTest::gtest GTest::gtest_main Threads::Threads)",
            "add_test(NAME " + command + " COMMAND " + command + ")",
        ]
    return "\n".join(lines) + "\n"


def sync(plan, root, cmake):
    created = []
    for name in plan["sources"] + plan["headers"]:
        path = root / name
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.touch()
            created.append(name)
    (root / "CMakeLists.txt").write_text(cmake, encoding="utf-8")
    return created
