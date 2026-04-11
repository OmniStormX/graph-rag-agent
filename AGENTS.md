# Repository Guidelines

## Project Structure & Module Organization
Core runtime sits in `graphrag_agent/`: `agents/` implements GraphRAG agents (multi-agent flows under `multi_agent/`), `graph/` and `integrations/build/` own graph ingestion, and `cache_manager/` wraps persistence. The FastAPI backend lives in `server/`; the Streamlit UI in `frontend/`. Tests and evaluation scripts reside in `test/`. Data inputs (`datasets/`, `documents/`) and generated artifacts (`cache/`, `files/`) stay separated—do not mix sources and outputs.

## Build, Test, and Development Commands
- `python -m venv .venv && source .venv/bin/activate` creates an isolated Python 3.10+ environment.
- `pip install -r requirements.txt` installs runtime and evaluation deps; install the OS packages noted in the file for DOC/PDF support.
- `uvicorn server.main:app --reload` starts the FastAPI service; it consumes `.env` variables for Neo4j and LLM access.
- `streamlit run frontend/app.py` launches the chat UI. Pair it with the build pipelines via `python -m graphrag_agent.integrations.build.main --help` when refreshing graph indexes.
- `python -m unittest discover test -v` runs the default regression suite prior to any PR.

## Coding Style & Naming Conventions
Adhere to PEP 8: 4-space indentation, `snake_case` modules and functions, `PascalCase` classes, and upper-snake constants. Public methods should carry type hints and concise docstrings. Keep prompt templates readable and avoid trailing-space churn. Format locally with `black` and `isort` (no repo config, but matching their defaults keeps diffs clean).

## Agent Workflow & Design Sources
When a task matches an installed Codex Skill, prefer following that skill's workflow instead of improvising a new one. For frontend, admin console, Streamlit UI, or other user-facing visual changes, treat `DESIGN.md` as the project-level design source of truth and keep new work visually aligned with it. If an existing page already has a stronger local pattern, preserve that pattern unless the task explicitly asks for a redesign.

Frontend design changes should preserve readability, responsive behavior, and implementation realism. Reuse the design tokens, typography rhythm, spacing logic, and interaction constraints defined in `DESIGN.md`; do not introduce ad hoc colors, random component styles, or a conflicting visual language. If a design rule in `DESIGN.md` is hard to implement because of framework or licensing constraints, keep the visual intent and document the fallback clearly in code comments or PR notes.

## Testing Guidelines
Tests rely on `unittest` scripts in `test/`. Name new cases `test_{feature}.py` and mirror the package layout so discovery works. Run the suite with `python -m unittest discover test -v`; exercise targeted flows via explicit modules (e.g., `python test/test_deep_agent.py`). Document any external prerequisites (Neo4j, API keys, cached embeddings) in your PR and offer fallbacks or skips when they are unavailable.

## Commit & Pull Request Guidelines
Follow the short, imperative commit style in history (`add multi-agent config`, `unify configs`). Scope each logical change to one commit and use optional prefixes (`agents:`) when clarifying impact. PRs should include: summary, linked issue/TODO, test results, and configuration changes. Attach screenshots for `frontend/` changes and describe migration steps for datasets, caches, or graph indexes.

## Configuration & Data Handling
Clone `.env.example` when adding settings; never commit secrets. Update both `.env.example` and `assets/start.md` when introducing new knobs or services. Keep raw corpora in `documents/` or `datasets/`; persist generated embeddings and caches in `cache/` or `files/` and avoid adding them to git. Note required ports or Docker services in `docker-compose.yaml` for reviewers.


1. 代码中添加适量注释，符合 Google 编程规范, 注释请使用中文。
2. 你是一位高级服务器架构师，请你给我行业内标准的建议与项目开发建议。
3. 涉及前端界面、管理后台、展示页、交互视觉调整时，优先遵循仓库根目录的 `DESIGN.md`，保证视觉风格、色彩、排版和交互节奏一致。
4. 如果任务明显匹配已安装的 Codex Skills，优先按对应 Skill 的标准流程执行，并在实现时避免绕开既有工作流。
