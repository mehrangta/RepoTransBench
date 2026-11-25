# Bounded finish recovery evaluation

The run completed on November 24, 2026, with the model `cx/gpt-6-luna(low)` and a 20-request limit for each repository. The full comparisons cover the same valid repositories across all three conditions. The study excluded 15 dataset-invalid Python → C++ tasks and 10 dataset-invalid JavaScript → Python tasks.

| Direction | Method | Valid builds | Full success | Reported tokens |
| --- | --- | ---: | ---: | ---: |
| Python → C++ | Raw RepoTransAgent | 24/156 (15.38%) | 8/156 (5.13%) | 16,431,283 |
| Python → C++ | Saved strongest base | 45/156 (28.85%) | 22/156 (14.10%) | 15,037,102 |
| Python → C++ | Base + finish recovery | 66/156 (42.31%) | 37/156 (23.72%) | 25,745,886 |
| JavaScript → Python | Raw RepoTransAgent | 130/179 (72.63%) | 61/179 (34.08%) | 12,867,026 |
| JavaScript → Python | Saved strongest base | 130/179 (72.63%) | 64/179 (35.75%) | 10,228,600 |
| JavaScript → Python | Base + finish recovery | 173/179 (96.65%) | 90/179 (50.28%) | 19,571,291 |

Compared with the saved strongest bases, full success rose by 9.62 percentage points for Python → C++ and 14.53 points for JavaScript → Python. The paired comparisons showed 15 gains and zero regressions for Python → C++, and 33 gains and seven regressions for JavaScript → Python. Reported token use rose by 71.2% and 91.3%, respectively. The policy intercepted a finish on 85 Python → C++ tasks and 95 JavaScript → Python tasks. [Per-repository scores](finish-recovery-results.csv)

## What was measured

Python build validity covers syntax, imports, and test collection. C++ build validity covers compilation of the candidate and supplied test targets. Full success requires all expected tests to pass and the supplied files to remain intact. An independent evaluator ran after generation in a separate container without model credentials. The tests were visible or executable during generation. The build-only counts under an additional intact-files requirement were 45 → 65 for Python → C++ and 129 → 172 for JavaScript → Python.

The previous Python → C++ base combined source contracts, dependency-aware retrieval, CMake manifests, and localized repair packets. The previous JavaScript → Python base combined JavaScript contracts, dependency-aware retrieval, package manifests, and corrected runner feedback. The finish-recovery rule and stop conditions were identical across the two adapters.

## Fresh comparisons

| Direction | Sample | Fresh control builds / successes | Recovery builds / successes |
| --- | --- | ---: | ---: |
| Python → C++ | 12-task pilot | 7 / 4 | 8 / 4 |
| Python → C++ | 8-task confirmation | 1 / 0 | 1 / 0 |
| JavaScript → Python | 12-task pilot | 8 / 5 | 11 / 7 |
| JavaScript → Python | 8-task confirmation | 6 / 3 | 8 / 3 |

The full comparison uses historical single-run controls. Sampling and provider drift can contribute to its differences. The fresh confirmation tied on full success in both directions. The full result reused all 40 pilot and confirmation outputs for the selected method and added 295 generations. The per-pair and execution audits passed.

Six interrupted generations resumed at the same failed requests. Each used an additional transport window within the original logical request limit. Eight other in-flight results were collected after a coordinator interruption without new model calls. Some failed transport attempts had unreported usage, so the token totals describe reported usage.

The published CLI prepares inputs from the dataset and records GoogleTest's skipped-test summaries in its finish gate. The tables report the saved study scores. The packaged CLI was verified with offline fixtures.
