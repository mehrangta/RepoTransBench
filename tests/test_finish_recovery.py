import json
from pathlib import Path
import shutil
import sys
from types import SimpleNamespace

import pytest

from RepoTransAgent import run_enhanced
from RepoTransAgent.enhanced import client
from RepoTransAgent.enhanced.adapters import CppRunner
from RepoTransAgent.enhanced.finish_recovery import FinishRecovery, NOTE


def test_recovery_budget_and_clean_gate():
    recovery = FinishRecovery()
    assert not recovery.intercept(20, 20)
    result = SimpleNamespace(
        compilation=SimpleNamespace(success=True),
        total_tests=2,
        passed_tests=1,
        failed_tests=0,
        error_tests=0,
        skipped_tests=1,
    )
    recovery.observe(result)
    assert recovery.intercept(1, 20)
    assert "Recovery 1/2" in recovery.observation()
    result.passed_tests = 2
    result.skipped_tests = 0
    recovery.observe(result)
    assert not recovery.intercept(2, 20)
    result.total_tests = result.passed_tests = 0
    recovery.observe(result)
    assert recovery.intercept(3, 20)
    assert "Recovery 2/2" in recovery.observation()
    assert not recovery.intercept(4, 20)


def test_cpp_runner_reports_skipped_tests(tmp_path):
    adapter = SimpleNamespace(validation_runs=0, artifacts=tmp_path)
    output = (
        "[       OK ] Fixture.Pass (0 ms)\n"
        "[  SKIPPED ] Fixture.Skip (0 ms)\n"
        "[  SKIPPED ] 1 test, listed below:\n"
        "[  SKIPPED ] Fixture.Skip\n"
    )
    result = CppRunner(adapter).analyze_output(output, "", 0)
    assert (result.total_tests, result.passed_tests, result.skipped_tests) == (2, 1, 1)
    recovery = FinishRecovery()
    recovery.observe(result)
    assert recovery.intercept(2, 20)


def create(name, content):
    return f'Thought: implement\nAction: CreateFile(filepath="{name}"):\n```\n{content}\n```'


@pytest.mark.parametrize("pair", [("Python", "C++"), ("JavaScript", "Python")])
def test_enhanced_cli_uses_manifest_and_recovers_from_early_finish(tmp_path, monkeypatch, pair):
    source_language, target_language = pair
    project = "fixture"
    workspace = tmp_path / "workspace"
    source = workspace / "source_projects" / source_language / project
    target = workspace / "target_projects" / source_language / target_language / project
    source.mkdir(parents=True)
    target.mkdir(parents=True)
    if target_language == "C++":
        if not shutil.which("cmake") or not shutil.which("g++"):
            pytest.skip("CMake and a C++ compiler are required for this fixture")
        (source / "main.py").write_text("def twice(x):\n    return x * 2\n")
        manifest = dict(sources=["src/fixture.cpp"], headers=["include/fixture.h"], libraries=[])
        implementation = {
            "include/fixture.h": "int twice(int x);",
            "src/fixture.cpp": '#include "fixture.h"\nint twice(int x) { return x * 2; }',
        }
        tests = {
            "tests/test.cpp": (
                '#include <gtest/gtest.h>\n#include "fixture.h"\n'
                "TEST(Fixture, Original) { EXPECT_EQ(twice(3), 6); }"
            ),
            "public_tests/test.cpp": (
                '#include <gtest/gtest.h>\n#include "fixture.h"\n'
                "TEST(Fixture, Public) { EXPECT_EQ(twice(2), 4); }"
            ),
        }
        runner = (
            "set -e\ncmake -S . -B build\ncmake --build build -j1\n"
            "./build/test_runner\n./build/public_test_runner\n"
        )
    else:
        (source / "main.js").write_text("export function twice(x) { return x * 2; }\n")
        manifest = dict(modules=["pkg/twice.py"])
        implementation = {"pkg/twice.py": "def twice(x):\n    return x * 2\n"}
        tests = {
            name: "from pkg.twice import twice\n\ndef test_twice():\n    assert twice(3) == 6\n"
            for name in ("tests/test_twice.py", "public_tests/test_twice.py")
        }
        runner = f"set -e\n{sys.executable} -m pytest -q tests\n{sys.executable} -m pytest -q public_tests\n"

    for name, content in tests.items():
        (target / name).parent.mkdir()
        (target / name).write_text(content)
    (target / "run_tests.sh").write_text(runner)
    (target / "project_structure.txt").write_text("\n".join(implementation))
    row = dict(
        project_name=project,
        source_language=source_language,
        target_language=target_language,
        run_tests_script="run_tests.sh",
        project_structure="project_structure.txt",
        target_public_tests=[name for name in tests if name.startswith("public_tests/")],
        target_original_tests=[name for name in tests if name.startswith("tests/")],
    )
    (workspace / "target_projects" / "projects_summary.jsonl").write_text(json.dumps(row) + "\n")
    responses = [
        'Thought: stop early\nAction: Finished(status="failed")',
        create("translation_manifest.json", json.dumps(manifest)),
        *(create(name, content) for name, content in implementation.items()),
        'Thought: all tests pass\nAction: Finished(status="success")',
    ]
    requests = []

    def post(url, *, json, **kwargs):
        assert url == "https://example.invalid/v1/chat/completions"
        requests.append(json["messages"][0]["content"][0]["text"])
        return SimpleNamespace(
            raise_for_status=lambda: None,
            json=lambda: {"choices": [{"message": {"content": responses[len(requests) - 1]}}]},
        )

    artifacts = tmp_path / "artifacts"
    for name in ("PYTHONPATH", "PYTEST_ADDOPTS"):
        monkeypatch.setenv(name, "")
    monkeypatch.setenv("REPOTRANS_WORKSPACE", str(workspace))
    monkeypatch.setenv("REPOTRANS_API_KEY", "offline")
    monkeypatch.setenv("REPOTRANS_BASE_URL", "https://example.invalid/v1")
    monkeypatch.setattr(client.requests, "post", post)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_enhanced",
            "--project_name",
            project,
            "--source_language",
            source_language,
            "--target_language",
            target_language,
            "--model_name",
            "offline/model",
            "--artifacts-dir",
            str(artifacts),
        ],
    )

    assert run_enhanced.main() == 0
    assert len(requests) == len(responses)
    assert all(prompt.count(NOTE) == 1 for prompt in requests)
    assert "STRUCTURED SOURCE CONTRACT" in requests[0]

    first = json.loads((artifacts / "upgrade_finishes" / "turn-01.json").read_text())
    final = json.loads(
        (artifacts / "upgrade_finishes" / f"turn-{len(responses):02d}.json").read_text()
    )
    assert first["intercepted"]
    assert not final["intercepted"]
    assert final["gate"]["clean"]
    assert final["gate"]["total"] == 2
    assert final["recoveries_before"] == 1

    candidate = workspace / "translated_projects" / "offline_model" / Path(*pair) / project
    assert json.loads((candidate / "translation_manifest.json").read_text()) == manifest
    assert (
        candidate / ("CMakeLists.txt" if target_language == "C++" else "pkg/__init__.py")
    ).is_file()
    assert all((candidate / name).read_text() == content for name, content in tests.items())
