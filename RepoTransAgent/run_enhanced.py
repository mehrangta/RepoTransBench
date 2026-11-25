"""Run a benchmarked pair adapter with bounded finish recovery."""

import json
import os
from pathlib import Path
from tempfile import mkdtemp

from .enhanced.adapters import Adapter, JavaScriptToPython, PythonToCpp, digest, save
from .enhanced.client import Generator
from .enhanced.finish_recovery import END, NOTE, START, FinishRecovery
from .run import ReactTranslationAgent, logger, run_translation, translation_parser
from .workspace import workspace_root

ADAPTERS = {("Python", "C++"): PythonToCpp, ("JavaScript", "Python"): JavaScriptToPython}
MAX_REQUESTS = 20


class EnhancedGenerator(Generator):
    def __init__(self, agent):
        self.agent = agent
        super().__init__(agent.args, logger, agent.system_prompt)

    def get_response(self, repo_name, history_conversation=None):
        if history_conversation:
            raise ValueError("The enhanced agent uses its current conversation")
        turn = self.agent.current_iteration
        prompt = self.agent.adapter.request_prompt(self.messages, turn) + START + NOTE + END
        self.messages[0] = dict(role="system", content=[dict(type="text", text=prompt)])
        save(
            self.args.artifacts_dir / "upgrade_requests" / f"call-{turn:02d}.json",
            dict(
                call=turn,
                addition=NOTE,
                prompt_sha256=digest(prompt.encode()),
                gate=self.agent.recovery.state,
                recoveries=self.agent.recovery.used,
            ),
        )
        return super().get_response(repo_name)


class EnhancedAgent(ReactTranslationAgent):
    def __init__(self, args, adapter: Adapter):
        self.adapter = adapter
        self.recovery = FinishRecovery()
        self.validation_runs = 0
        super().__init__(args)

    def create_test_analyzer(self):
        analyzer = super().create_test_analyzer()
        analyzer.analyzer = self.adapter.create_runner()
        return analyzer

    def build_system_prompt(self):
        return self.adapter.build_prompt()

    def create_generator(self):
        return EnhancedGenerator(self)

    def predict(self, observation):
        self.adapter.before_prediction()
        return super().predict(observation)

    def execute_action(self, action):
        observation = self.adapter.intercept(action, self.current_iteration)
        intercepted = observation is not None
        if intercepted:
            done = False
        else:
            observation, done = super().execute_action(action)
        self.adapter.record_action(action, self.current_iteration, observation, done, intercepted)
        return observation, done

    def run_tests_and_analyze(self):
        observation, analysis = super().run_tests_and_analyze()
        self.recovery.observe(analysis)
        self.validation_runs += 1
        save(
            self.args.artifacts_dir / "upgrade_gates" / f"run-{self.validation_runs:03d}.json",
            dict(
                turn=self.current_iteration,
                observation=observation,
                state=self.recovery.state,
            ),
        )
        return observation, analysis

    def _execute_finished(self, action):
        turn = self.current_iteration
        intercepted = self.recovery.intercept(turn, self.max_iterations)
        save(
            self.args.artifacts_dir / "upgrade_finishes" / f"turn-{turn:02d}.json",
            dict(
                turn=turn,
                requested_status=action.status,
                gate=self.recovery.state,
                recoveries_before=self.recovery.used,
                intercepted=intercepted,
                maximum=self.max_iterations,
            ),
        )
        if intercepted:
            return self.recovery.observation(), False
        return super()._execute_finished(action)


def project_row(args, workspace):
    with (workspace / "target_projects" / "projects_summary.jsonl").open(
        encoding="utf-8"
    ) as summary:
        for line in summary:
            if not line.strip():
                continue
            row = json.loads(line)
            if (
                row.get("project_name"),
                row.get("source_language"),
                row.get("target_language"),
            ) == (
                args.project_name,
                args.source_language,
                args.target_language,
            ):
                return row
    raise ValueError("Project and language pair do not match a dataset entry")


def main():
    parser = translation_parser("RepoTransAgent with bounded finish recovery", default_model=None)
    parser.add_argument(
        "--artifacts-dir", type=Path, help="New directory for logs and recovery receipts"
    )
    args = parser.parse_args()
    pair = (args.source_language, args.target_language)
    if pair not in ADAPTERS:
        parser.error("choose Python to C++ or JavaScript to Python")
    model_dir = args.model_name.replace("/", "_") if args.model_name else ""
    if any(
        name in {"", ".", ".."} or Path(name).name != name
        for name in (model_dir, args.project_name)
    ):
        parser.error("provide a model name and a dataset project name")
    if not 1 <= args.max_iterations <= MAX_REQUESTS:
        parser.error(f"--max_iterations must be between 1 and {MAX_REQUESTS}")
    if not os.environ.get("REPOTRANS_API_KEY"):
        parser.error("set REPOTRANS_API_KEY for your model provider")
    workspace = workspace_root()
    try:
        row = project_row(args, workspace)
        if not (workspace / "source_projects" / args.source_language / args.project_name).is_dir():
            raise ValueError("Source project directory is missing from the benchmark workspace")
        if args.artifacts_dir is None:
            parent = Path("logs/enhanced")
            parent.mkdir(parents=True, exist_ok=True)
            args.artifacts_dir = Path(mkdtemp(prefix=f"{args.project_name}-", dir=parent)).resolve()
        else:
            args.artifacts_dir = args.artifacts_dir.resolve()
            args.artifacts_dir.mkdir(parents=True)
        adapter = ADAPTERS[pair](args, row)
    except (OSError, ValueError, ImportError) as error:
        parser.error(str(error))

    if args.target_language == "Python":
        python_path = os.environ.get("PYTHONPATH")
        os.environ["PYTHONPATH"] = str(adapter.root) + (
            os.pathsep + python_path if python_path else ""
        )
        pytest_options = os.environ.get("PYTEST_ADDOPTS", "")
        os.environ["PYTEST_ADDOPTS"] = f"{pytest_options} --import-mode=importlib".strip()
    logger.info("Enhanced run artifacts: %s", args.artifacts_dir)
    return run_translation(args, lambda arguments: EnhancedAgent(arguments, adapter))


if __name__ == "__main__":
    raise SystemExit(main())
