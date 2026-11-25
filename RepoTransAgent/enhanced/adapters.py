"""Prepare and apply the two measured source and target adapters."""

import hashlib
import json
from pathlib import Path
import re

from RepoTransAgent.actions import CreateFile
from RepoTransAgent.prompts import system_prompt
from RepoTransAgent.test_analyzer import CppTestAnalyzer, PythonTestAnalyzer
from RepoTransAgent.workspace import workspace_root

from . import cpp_manifest, python_manifest
from .python_feedback import adapt
from .repair_packet import repair_packet
from .source_chunks import CHUNK_BUDGET, entity_use_chunks

CONTRACT = "\n\n## STRUCTURED SOURCE CONTRACT (precomputed offline)\n"
PUBLIC_HEADER = "\n\n## 📋 PUBLIC TESTS (Visible Reference Tests)"
MANIFEST = "translation_manifest.json"


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def digest(value):
    return hashlib.sha256(value).hexdigest()


def message_text(message):
    content = message.get("content", "")
    if isinstance(content, str):
        return content
    return "\n".join(part.get("text", "") for part in content)


class Adapter:
    generated_file = None

    def __init__(self, args, row):
        self.project = args.project_name
        self.languages = (args.source_language, args.target_language)
        self.artifacts = args.artifacts_dir
        workspace = workspace_root()
        source = workspace / "source_projects" / args.source_language / self.project
        reference = workspace / "target_projects" / Path(*self.languages) / self.project
        self.runner_script = (reference / "run_tests.sh").read_text(encoding="utf-8")
        self.root = (
            workspace
            / "translated_projects"
            / args.model_name.replace("/", "_")
            / Path(*self.languages)
            / self.project
        )
        self.expected = {
            path.relative_to(reference).as_posix(): digest(path.read_bytes())
            for path in reference.rglob("*")
            if path.is_file()
        }
        self.violations = []
        self.plan = None
        self.revisions = 0
        excluded = row.get("source_original_tests", []) + row.get("source_public_tests", [])
        self.inputs = self.prepare_inputs(source, excluded)

    def build_prompt(self):
        project_args = (*self.languages, self.project)
        self.public_query = (
            system_prompt.get_public_tests_content(*project_args)
            + "\n"
            + system_prompt.get_project_structure(*project_args)
        )
        source = self.select_source(self.public_query, 0)
        prompt = system_prompt.get_react_translation_prompt(*project_args, source_context=source)
        prompt += CONTRACT + self.inputs["contract"] + self.contract_checklist
        header = (
            f"## 📄 SOURCE FILES (Reference - 5 sample files from {self.languages[0]} project)\n"
        )
        start = prompt.index(header) + len(header)
        stop = prompt.index(PUBLIC_HEADER, start)
        self.prefix, self.suffix = prompt[:start], prompt[stop:]
        return prompt

    def select_source(self, query, turn):
        selected, used = entity_use_chunks(self.inputs["chunks"], query, budget=CHUNK_BUDGET)
        body = "\n\n".join(
            f'SOURCE {chunk["id"]} ({chunk["symbol"]})\n{chunk["text"]}' for chunk, _ in selected
        )
        receipt = dict(
            call=turn,
            budget_chars=CHUNK_BUDGET,
            selected_source_chars=used,
            query_sha256=digest(query.encode()),
            rendered_source_sha256=digest(body.encode()),
            selected_chunks=[chunk["id"] for chunk, _ in selected],
            selected_reasons=[reason for _, reason in selected],
        )
        filename = f"call-{turn:02d}.json" if turn else "initial.json"
        save(self.artifacts / "context_selections" / filename, receipt)
        return body

    def request_prompt(self, messages, turn):
        query = (
            self.public_query + "\n" + "\n".join(message_text(message) for message in messages[1:])
        )
        prompt = self.prefix + self.select_source(query, turn) + self.suffix
        note, details = self.request_note()
        save(
            self.artifacts / "method_receipts" / f"call-{turn:02d}.json",
            dict(call=turn, note=note, plan=self.plan, **details),
        )
        start = prompt.rindex(CONTRACT)
        return prompt[:start] + self.note_start + note + self.note_end + prompt[start:]

    def before_prediction(self):
        if self.plan is not None:
            self.sync(self.plan)

    def intercept(self, action, turn):
        if not isinstance(action, CreateFile):
            return None
        name = self.action_name(action.filepath)
        if self.plan is None and turn <= 3 and name != MANIFEST:
            return f"Plan required first: CreateFile {MANIFEST} with the documented JSON schema."
        if (
            self.plan is not None
            and name == self.generated_file
            and self.generated_file is not None
        ):
            return f"Update {MANIFEST}; {self.generated_file} is generated from that manifest."
        if name != MANIFEST:
            return None
        try:
            plan = self.parse_manifest(action.content)
            created = self.sync(plan)
            (self.root / MANIFEST).write_text(action.content, encoding="utf-8")
        except (ValueError, TypeError, KeyError, OSError) as error:
            return f"Invalid manifest: {error}"
        self.plan = plan
        self.revisions += 1
        save(
            self.artifacts / "plans" / f"revision-{self.revisions:02d}.json",
            dict(turn=turn, plan=plan, created=created),
        )
        return self.manifest_accepted

    def action_name(self, filepath):
        return filepath

    def record_action(self, action, turn, observation, done, intercepted):
        for name, expected in self.expected.items():
            path = self.root / name
            if path.is_symlink() or not path.is_file() or digest(path.read_bytes()) != expected:
                self.violations.append(dict(turn=turn, path=name))
        save(
            self.artifacts / "method_actions" / f"turn-{turn:02d}.json",
            dict(
                turn=turn,
                kind=type(action).__name__,
                observation=observation,
                done=done,
                intercepted=intercepted,
                plan=self.plan,
                protected_violations=self.violations,
            ),
        )


class CppRunner(CppTestAnalyzer):
    def __init__(self, adapter):
        self.adapter = adapter

    def get_test_commands(self):
        return ["bash run_tests.sh"]

    def analyze_output(self, stdout, stderr, return_code):
        self.adapter.validation_output = (stdout + "\n" + stderr)[-20000:]
        self.adapter.validation_runs += 1
        save(
            self.adapter.artifacts / "validation" / f"run-{self.adapter.validation_runs:03d}.json",
            dict(return_code=return_code, output=self.adapter.validation_output),
        )
        result = super().analyze_output(stdout, stderr, return_code)
        skipped = sum(
            int(count)
            for count in re.findall(
                r"^\[\s*SKIPPED\s*\]\s+(\d+) tests?\b",
                stdout,
                re.MULTILINE,
            )
        )
        result.skipped_tests += skipped
        result.total_tests += skipped
        return result


class PythonRunner(PythonTestAnalyzer):
    analyze_output = adapt(PythonTestAnalyzer.analyze_output)

    def get_test_commands(self):
        return ["bash run_tests.sh"]


class PythonToCpp(Adapter):
    generated_file = "CMakeLists.txt"
    manifest_accepted = f"Accepted {MANIFEST}. Plan installed."
    note_start = "\n\n<REPOTRANS_STRUCTURE_POLICY>\n"
    note_end = "\n</REPOTRANS_STRUCTURE_POLICY>"
    contract_checklist = (
        "\n\nUse this contract as a persistent checklist. Preserve each listed public name,\n"
        "argument/default contract, class field, and cross-function dependency. Define\n"
        "every required translated symbol. Keep target interfaces consistent across files.\n"
        "After changes, run the supplied build/test command and use the earliest compiler\n"
        "or linker error to repair the owning declaration or definition.\n"
    )

    def __init__(self, args, row):
        super().__init__(args, row)
        self.validation_runs = 0
        self.validation_output = ""

    def prepare_inputs(self, source, excluded):
        from .python_inputs import make_inputs

        return make_inputs(self.project, source, excluded)

    def create_runner(self):
        return CppRunner(self)

    def action_name(self, filepath):
        return cpp_manifest.relative(self.root, filepath)

    def parse_manifest(self, content):
        if len(content) > 90000:
            raise ValueError("Plan exceeds size limit")
        return cpp_manifest.manifest_plan(json.loads(content), self.root, self.expected)

    def sync(self, plan):
        cmake = cpp_manifest.render_cmake(plan, self.runner_script)
        return cpp_manifest.sync(plan, self.root, cmake)

    def request_note(self):
        if self.plan is None:
            base = (
                f'DETERMINISTIC BUILD MANIFEST. First use the normal CreateFile action with filepath="{MANIFEST}" '
                'and a fenced JSON body. Schema: {"sources":["src/lib.cpp"],"headers":["include/lib.h"],"libraries":[]}. '
                "Choose exact paths required by the supplied structure/public interfaces. Header-only projects may use empty sources. "
                "The controller generates CMakeLists, creates missing empty files and keeps this manifest synchronized. "
                "Implement the real bodies. Change the JSON to add files; do not rewrite CMakeLists directly. "
                "Feedback uses bash run_tests.sh, the supplied runner. Planning consumes the same 20-request budget."
            )
        else:
            base = (
                "BUILD MANIFEST ACTIVE. Implement every planned file. Empty files are placeholders, not implementations. "
                f"Update {MANIFEST} to add/rename files; the controller owns CMakeLists. "
                f"Use bash run_tests.sh. Plan: {json.dumps(self.plan)}"
            )
        packet, locations = repair_packet(self.validation_output, self.root)
        return (base[:4000] + "\n" + packet)[:4000], dict(
            locations=locations,
            validation_run=self.validation_runs,
        )


class JavaScriptToPython(Adapter):
    manifest_accepted = f"Accepted {MANIFEST}. Module/package scaffold installed."
    note_start = "\n\n<REPOTRANS_TRANSFER_POLICY>\n"
    note_end = "\n</REPOTRANS_TRANSFER_POLICY>"
    contract_checklist = (
        "\n\nUse this contract as a persistent checklist. "
        "Preserve listed public names, argument/default contracts, class fields, exports and dependencies. "
        "Keep translated definitions and imports consistent across files. "
        "Run the supplied build/test command and repair the owning definition or import."
    )

    def prepare_inputs(self, source, excluded):
        from .js_inputs import make_inputs, sources

        return make_inputs(self.project, sources(source, excluded))

    def create_runner(self):
        return PythonRunner()

    def parse_manifest(self, content):
        return python_manifest.validate(json.loads(content), self.root, self.expected)

    def sync(self, plan):
        return python_manifest.sync(plan, self.root)

    def request_note(self):
        return python_manifest.note(self.plan)[:4000], {}
