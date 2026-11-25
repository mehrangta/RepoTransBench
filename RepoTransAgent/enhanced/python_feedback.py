"""Parse actual quiet/multi-invocation pytest output from supplied runners."""

import re
from RepoTransAgent.test_analyzer import CompilationResult, ModuleResult, AnalysisResult


def adapt(original):
    def analyze(self, stdout, stderr, return_code):
        result = original(self, stdout, stderr, return_code)
        output = stdout + "\n" + stderr
        collection = bool(
            re.search(r"ImportError|ModuleNotFoundError|SyntaxError|ERROR collecting", output)
        )
        if collection:
            lines = output.splitlines()
            relevant = [
                s
                for s in lines
                if re.search(r"ImportError|ModuleNotFoundError|SyntaxError|ERROR collecting", s)
            ]
            result.compilation = CompilationResult(
                False, max(1, len(relevant)), 0, "\n".join(relevant)[:500]
            )
        if result.total_tests:
            return result
        counts = dict(passed=0, failed=0, error=0, skipped=0)
        # pytest emits one terminal session-summary line per invocation.
        for line in output.splitlines():
            if " in " not in line:
                continue
            for number, status in re.findall(
                r"\b(\d+)\s+(passed|failed|errors?|skipped|xfailed|xpassed)\b", line
            ):
                key = {"errors": "error", "xfailed": "skipped", "xpassed": "skipped"}.get(
                    status, status
                )
                counts[key] += int(number)
        total = sum(counts.values())
        if not total:
            return result
        module = ModuleResult(
            "supplied_runner",
            total,
            counts["passed"],
            counts["failed"],
            counts["error"],
            counts["skipped"],
        )
        return AnalysisResult(
            compilation=result.compilation,
            total_tests=total,
            passed_tests=counts["passed"],
            failed_tests=counts["failed"],
            error_tests=counts["error"],
            skipped_tests=counts["skipped"],
            modules={"supplied_runner": module},
            individual_tests=[],
        )

    return analyze
