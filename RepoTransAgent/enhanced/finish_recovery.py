"""The same stopping rule for both benchmark adapters."""

import json

START = "\n\n<SHARED_UPGRADE_POLICY>\n"
END = "\n</SHARED_UPGRADE_POLICY>"
NOTE = (
    "BOUNDED FINISH RECOVERY. If you call Finished while the latest supplied-runner validation "
    "has not shown a clean pass, the controller can return at most two recovery observations. "
    "Use the next normal request to inspect or fix the earliest failure. All requests remain within "
    "the original 20-request allowance. This does not certify correctness; normal independent scoring follows."
)


def validation_state(analysis):
    if analysis is None:
        return dict(available=False, clean=False)
    compiles = bool(analysis.compilation.success)
    total = analysis.total_tests
    passed = analysis.passed_tests
    failed = analysis.failed_tests
    errors = analysis.error_tests
    skipped = analysis.skipped_tests
    clean = compiles and total > 0 and passed == total and not (failed or errors or skipped)
    return dict(
        available=True,
        compiles=compiles,
        total=total,
        passed=passed,
        failed=failed,
        errors=errors,
        skipped=skipped,
        clean=clean,
    )


class FinishRecovery:
    limit = 2

    def __init__(self):
        self.state = validation_state(None)
        self.used = 0

    def observe(self, analysis):
        self.state = validation_state(analysis)

    def intercept(self, turn, maximum):
        return not self.state["clean"] and self.used < self.limit and turn < maximum

    def observation(self):
        self.used += 1
        return (
            "The latest supplied-runner validation has not shown a clean pass. "
            "Continue with one concrete source inspection or implementation repair for the earliest failure. "
            "Use the existing files, source and runner feedback. This uses the remaining normal request allowance. "
            f"Recovery {self.used}/{self.limit}; evidence: {json.dumps(self.state)}"
        )
