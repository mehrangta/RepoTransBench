# RepoTransBench: A Real-World Multilingual Benchmark for Repository-Level Code Translation

[![License](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.8+-green.svg)](https://python.org)
[![Paper](https://img.shields.io/badge/Paper-arXiv-red.svg)](https://arxiv.org/pdf/2412.17744)

## 📖 Overview

**RepoTransBench** is a comprehensive repository-level code translation benchmark featuring **1,897 real-world repository samples** across **13 language pairs** with automatically executable test suites. Unlike previous fine-grained benchmarks that focus on snippets, functions, or files, RepoTransBench addresses real-world demands where entire repositories need translation.

### Key Features

- 🌍 **Multilingual**: 13 translation pairs covering 7 programming languages (C, C++, C#, Java, JavaScript, Python, Rust, Matlab)
- 📊 **Large-scale**: 1,897 repository samples with comprehensive test coverage
- ⚡ **Execution-based**: Automatic test suites for functional correctness validation
- 🏗️ **Real-world**: Repository-level complexity with dependencies, configuration files, and resource management
- 🤖 **Automated**: Multi-agent framework for benchmark construction

### Supported Translation Pairs

| Source Language | Target Languages |
|----------------|------------------|
| C | Python, Rust |
| C++ | Python |
| C# | Java |
| Java | C#, Go, Python |
| JavaScript | Python |
| Matlab | Python |
| Python | C++, Go, Java, Rust |

## 🚀 Getting Started

### Prerequisites

- Python 3.8+
- Docker (for sandboxed execution)
- Git

### Installation

1. **Clone the repository**
   ```bash
   git clone https://github.com/DeepSoftwareAnalytics/RepoTransBench.git
   cd RepoTransBench
   ```

2. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

3. **Download the dataset**
   
   Download the benchmark data from our latest release:
   
   **[📥 Release: RepoTransBench Dataset v1.0](https://github.com/DeepSoftwareAnalytics/RepoTransBench/releases/tag/v1.0)**
   
   ```bash
   # Download and extract the dataset to /workspace directory
   mkdir -p /workspace
   cd /workspace
   wget https://github.com/DeepSoftwareAnalytics/RepoTransBench/releases/download/v1.0/repotransbench_dataset.tar.gz
   tar -xzf repotransbench_dataset.tar.gz
   ```

4. **Configure API access**
   ```bash
   # Add your API keys to the configuration file
   echo "api_key_1 your_openai_api_key_here" > RepoTransAgent/API_KEY.txt
   echo "api_key_2 your_anthropic_api_key_here" >> RepoTransAgent/API_KEY.txt
   ```

5. **Set up Docker environment (optional)**
   ```bash
   cd docker
   docker-compose up -d
   ```

## 📊 Benchmark Statistics

| Metric | Value |
|--------|-------|
| **Total Samples** | 1,897 |
| **Translation Pairs** | 13 |
| **Programming Languages** | 7 |
| **Average Tokens per Sample** | 23,966 |
| **Average Lines of Code** | 2,394 |
| **Average Functions** | 177 |
| **Average Classes** | 35 |
| **Average Import Statements** | 163 |
| **Line Coverage** | 81.89% |
| **Branch Coverage** | 72.61% |

## 🤖 RepoTransAgent

We introduce **RepoTransAgent**, a general agent framework for repository-level code translation based on the ReAct (Reasoning + Acting) paradigm.

### Bounded finish recovery in this fork

The enhanced agent uses a shared recovery rule for Python → C++ and JavaScript → Python. When the model calls `Finished`, the agent checks the latest supplied-runner result. If the build or tests have yet to show a clean pass, it can return up to two repair observations within the same 20-request limit. A clean pass requires a successful build and at least one test, with every test passing and zero failures, errors, or skips.

Both adapters build a source contract offline and refresh up to 4,000 characters of source chunks per request, reserving space for related definitions and calls. Python → C++ generates CMake from an implementation manifest and includes localized diagnostics and current code in its repair feedback. JavaScript → Python builds the package scaffold from a module manifest and parses quiet pytest summaries from the supplied runner.

| Direction | Baseline | Success rate, baseline → enhanced | Success gain | Compile rate, baseline → enhanced | Compile gain |
| --- | --- | ---: | ---: | ---: | ---: |
| Python → C++ | Raw RepoTransAgent | 5.13% → 23.72% | **+18.59 pp** | 15.38% → 42.31% | **+26.92 pp** |
| Python → C++ | Strongest prior adapter | 14.10% → 23.72% | **+9.62 pp** | 28.85% → 42.31% | **+13.46 pp** |
| JavaScript → Python | Raw RepoTransAgent | 34.08% → 50.28% | **+16.20 pp** | 72.63% → 96.65% | **+24.02 pp** |
| JavaScript → Python | Strongest prior adapter | 35.75% → 50.28% | **+14.53 pp** | 72.63% → 96.65% | **+24.02 pp** |

The raw RepoTransAgent rows show the gains for the full enhanced method. The strongest prior adapter rows show the gains associated with adding finish recovery. Gains are in percentage points (pp), calculated from the original counts. Compile rate measures native builds for C++ and syntax, imports, and test collection for Python.

These results compare 156 Python → C++ and 179 JavaScript → Python tasks with saved single-run controls on `cx/gpt-6-luna(low)`. The fresh eight-task confirmation for each direction tied on full success. The supplied tests were visible or executable during generation, and a separate evaluator scored the candidates afterward. Compared with the strongest prior adapters, reported token use rose by 71.2% for Python → C++ and 91.3% for JavaScript → Python. [Evaluation details and per-repository results](docs/finish-recovery.md)

#### Run the enhanced agent

Use Python 3.10+ and extract the benchmark dataset. Run from the repository root in an isolated benchmark environment with the target toolchain. Python → C++ needs CMake, a C++17 compiler, and GoogleTest. JavaScript → Python needs pytest, which the enhanced requirements install. [Benchmark dataset](https://github.com/DeepSoftwareAnalytics/RepoTransBench/releases/tag/v1.0)

```bash
python -m pip install -r requirements-enhanced.txt

# Point this at the dataset root. The default is /workspace.
export REPOTRANS_WORKSPACE=/workspace
# Set REPOTRANS_API_KEY in your environment before running.
export REPOTRANS_BASE_URL=https://api.openai.com/v1

python -m RepoTransAgent.run_enhanced \
    --project_name tartley_colorama \
    --source_language Python \
    --target_language 'C++' \
    --model_name gpt-4.1
```

For JavaScript → Python, use `--project_name aceakash_string-similarity --source_language JavaScript --target_language Python`. Set `REPOTRANS_BASE_URL` to your provider's OpenAI-compatible API base and choose a model exposed by that provider. The benchmark model requires access to the endpoint that serves it.

The agent writes candidate files to `$REPOTRANS_WORKSPACE/translated_projects/<model>/<source>/<target>/<project>` and replaces that directory on another run with the same settings. It writes conversation logs, manifest receipts, and finish decisions to a new directory under `logs/enhanced/`. Use `--artifacts-dir` to choose a new directory.

### Key Capabilities

- **ReadFile**: Examine code files, configurations, and documentation
- **CreateFile**: Generate translated files and configurations
- **ExecuteCommand**: Run builds, tests, and dependency installations
- **SearchContent**: Locate specific code patterns and dependencies
- **Finished**: Mark translation completion

### Quick Start with RepoTransAgent

1. **Single Project Translation**
   ```bash
   # Translate a single project
   python -m RepoTransAgent.run \
       --project_name "your_project_name" \
       --source_language "Python" \
       --target_language "Java" \
       --model_name "claude-sonnet-4-20250514" \
       --max_iterations 20
   ```

2. **Batch Translation**
   ```bash
   # Run batch translation on multiple projects
   python -m RepoTransAgent.run_batch
   ```

3. **Available Models**
   - `claude-sonnet-4-20250514` (default)
   - `gpt-4.1`
   - `gemini-2.5-flash-lite`
   - `deepseek-chat`
   - `qwen3-235b-a22b`

### Command Line Arguments

#### Single Translation (`RepoTransAgent.run`)
```bash
python -m RepoTransAgent.run \
    --project_name PROJECT_NAME \      # Required: Name of the project to translate
    --source_language SOURCE_LANG \    # Required: Source language (Python, Java, C++, etc.)
    --target_language TARGET_LANG \    # Required: Target language (Python, Java, C++, etc.)
    --model_name MODEL_NAME \          # Optional: LLM model (default: claude-sonnet-4-20250514)
    --max_iterations MAX_ITER          # Optional: Max iterations (default: 20)
```

#### Batch Translation (`RepoTransAgent.run_batch`)
```bash
python -m RepoTransAgent.run_batch
```
The batch script automatically:
- Reads from `/workspace/target_projects/projects_summary.jsonl`
- Processes multiple projects in parallel
- Supports resume functionality (skips completed projects)
- Saves detailed results and logs

## 📋 Usage Examples

### 1. Basic Translation

```python
# Direct command line execution
python -m RepoTransAgent.run \
    --project_name "example_project" \
    --source_language "Python" \
    --target_language "Java" \
    --model_name "claude-sonnet-4-20250514"
```

### 2. Evaluation on Benchmark

```bash
# The agent automatically evaluates against tests during translation
# Results are saved in logs/ directory with detailed analysis

# Example log structure:
# logs/claude-sonnet-4-20250514/project_name_Python_to_Java_20240130_143022/
# ├── system_prompt.txt          # System prompt used
# ├── turn_01.txt                # Each conversation turn
# ├── turn_02.txt
# ├── ...
# └── final_summary.txt          # Final results and test analysis
```

### 3. Batch Processing

```bash
# Run multiple projects in parallel (configurable in run_batch.py)
python -m RepoTransAgent.run_batch

# Configuration in run_batch.py:
# - max_per_pair: Projects per translation pair
# - num_processes: Parallel processes (default: 50)
# - max_iterations: Max iterations per project (default: 20)
```

## 📈 Evaluation Results

Our evaluation reveals that repository-level code translation remains challenging:

| Method | Success Rate | Compilation Rate |
|--------|-------------|------------------|
| Translation Only | 0.0% | 26.2% |
| Error Feedback | 12.4% | 30.5% |
| **RepoTransAgent** | **32.8%** | **54.8%** |

### Key Findings

1. **Directional Asymmetry**: Static-to-dynamic translation (45-63% success) significantly outperforms dynamic-to-static (< 10%)
2. **Model Specialization**: Different LLMs show advantages for specific translation pairs
3. **Complexity Impact**: Repository complexity inversely correlates with translation success

## 🔬 Research Applications

RepoTransBench enables research in:

- **Code Translation**: Develop and evaluate new translation methods
- **LLM Capabilities**: Assess model performance on complex, real-world tasks
- **Software Engineering**: Study repository-level code migration challenges
- **Multi-Agent Systems**: Design collaborative AI systems for complex tasks

## 📁 Project Structure

```
RepoTransBench/
├── RepoTransAgent/              # 🤖 Main agent framework
│   ├── actions.py              # Action definitions (CreateFile, ReadFile, etc.)
│   ├── generator.py            # LLM API client and response handling
│   ├── run.py                  # Single project translation script
│   ├── run_enhanced.py         # Benchmarked adapters with bounded finish recovery
│   ├── enhanced/              # Source retrieval, manifests, and recovery logic
│   ├── run_batch.py            # Batch processing script
│   ├── test_analyzer.py        # Multi-language test result analysis
│   ├── API_KEY.txt             # API keys configuration
│   └── prompts/
│       └── system_prompt.py    # System prompt generation
├── multi_agent_based_benchmark_construction/  # 🏗️ Benchmark construction tools
│   ├── testcase_public_agent_batch/    # Public test generation
│   ├── testcase_target_agent_batch/    # Target test translation
│   ├── coverage_agent_batch/           # Coverage analysis
│   └── runnable_agent_batch/           # Environment setup
├── rule_based_filter_scripts/   # 📋 Repository filtering tools
├── download_repos_scripts/      # 📥 Data collection utilities
├── docker/                      # 🐳 Containerization setup
│   ├── Dockerfile
│   └── docker-compose.yml
└── assets/                      # 📊 Paper figures and resources
```

## 📊 Expected Directory Structure (After Dataset Download)

After downloading the dataset, your `/workspace` directory should look like:

```
/workspace/
├── source_projects/             # Original source code repositories
│   ├── Python/
│   ├── Java/
│   ├── C++/
│   └── ...
├── target_projects/             # Target translation projects with tests
│   ├── projects_summary.jsonl  # Project metadata
│   ├── Python/
│   │   ├── Java/
│   │   │   ├── project1/
│   │   │   │   ├── run_tests.sh
│   │   │   │   ├── public_tests/
│   │   │   │   └── original_tests/
│   │   │   └── project2/
│   │   └── C++/
│   └── Java/
│       └── Python/
└── translated_projects/         # Generated translations (created during execution)
    └── claude-sonnet-4-20250514/
        ├── Python/
        │   └── Java/
        └── Java/
            └── Python/
```

## 🏆 Leaderboard

We welcome submissions to our leaderboard! Submit your results via GitHub Issues.

| Rank | Method | Model | Success Rate | Paper/Code |
|------|--------|--------|-------------|------------|
| 1 | RepoTransAgent | Claude-4 | 32.8% | [This work] |
| 2 | RepoTransAgent | GPT-4.1 | 32.8% | [This work] |
| 3 | RepoTransAgent | DeepSeek | 22.5% | [This work] |

## 📄 Citation

If you use RepoTransBench in your research, please cite our paper:

```bibtex
@article{repotransbench2024,
  title={RepoTransBench: A Real-World Multilingual Benchmark for Repository-Level Code Translation},
  author={Wang, Yanli and Wang, Yanlin and Wang, Suiquan and Guo, Daya and Chen, Jiachi and Grundy, John and Liu, Xilin and Ma, Yuchi and Mao, Mingzhi and Zhang, Hongyu and Zheng, Zibin},
  journal={arXiv preprint arXiv:2024.xxxxx},
  year={2024}
}
```

## 🤝 Contributing

We welcome contributions! Please see our [Contributing Guidelines](CONTRIBUTING.md) for details.

### Ways to Contribute

- 🐛 Report bugs and issues
- 💡 Suggest new features or translation pairs
- 📝 Improve documentation
- 🧪 Add new evaluation methods
- 🔄 Submit translation results

## 📜 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 🙏 Acknowledgments

- Thanks to all contributors who helped build this benchmark
- Special thanks to the open-source community for providing repositories
- Supported by Sun Yat-sen University, Monash University, Huawei Cloud, and Chongqing University

## 📞 Contact

For questions or collaboration opportunities:

- **Primary Contact**: Yanlin Wang (wangylin36@mail.sysu.edu.cn)
- **Issues**: Please use [GitHub Issues](https://github.com/DeepSoftwareAnalytics/RepoTransBench/issues)
- **Discussions**: Join our [GitHub Discussions](https://github.com/DeepSoftwareAnalytics/RepoTransBench/discussions)

---

⭐ **Star this repository if you find it useful!** ⭐
