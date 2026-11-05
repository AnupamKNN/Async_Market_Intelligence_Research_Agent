# Async Market Intelligence & Research Agent

An asynchronous AI-powered market intelligence and research platform combining retail analytics, sentiment modeling, economic indicators, and external news research to generate evidence-backed insights.

## Project Objectives

- Analyze retail transactions and online shopper session data.
- Train and evaluate classical ML and deep learning sentiment models.
- Integrate external economic indicators and news intelligence.
- Orchestrate specialized AI agents using LangGraph.
- Expose analytical and research capabilities through MCP servers.
- Generate structured research reports with citations and source provenance.
- Deliver real-time research progress through a React dashboard.

## Planned Technology Stack

| Component | Technologies |
|---|---|
| Backend | Python 3.13, FastAPI |
| Dependency Management | uv |
| Frontend | React.js, Bootstrap, Plotly |
| Agent Orchestration | LangChain, LangGraph |
| MCP | FastMCP |
| Database | PostgreSQL, asyncpg |
| Caching and Job Queue | Redis, Redis Streams |
| Machine Learning | Scikit-learn, PyTorch |
| LLM Integration | Portkey, Groq, Ollama |
| Evaluation and Monitoring | LangSmith, Logfire, DeepEval, RAGAS |

## Project Structure

```text
src/market_intelligence/  # Python application
frontend/                 # React dashboard
tests/                    # Automated tests
data/                     # Local datasets
artifacts/                # Model artifacts
infrastructure/           # Infrastructure configuration
docs/                     # Architecture and technical documentation
```

## Development Setup

### Prerequisites

- Python 3.13
- uv
- Node.js (for the React frontend, introduced in a later phase)
- PostgreSQL and Redis (introduced in later phases)

### Backend Setup

Clone the repository:

```bash
git clone https://github.com/AnupamKNN/Async_Market_Intelligence_Research_Agent.git

cd Async_Market_Intelligence_Research_Agent
```

Create and synchronize the Python environment:

```bash
uv sync
```

Verify Python:

```bash
uv run python --version
```

## Development Roadmap

The project will be developed in five phases:

1. Data and MCP Foundation
2. Redis Semantic Cache and Portkey Integration
3. LangGraph Multi-Agent Orchestration
4. Security and Evaluation
5. FastAPI Backend and React Dashboard

## Data and Model Artifacts

Datasets, trained model binaries, credentials, and environment-specific files are excluded from Git and managed separately.

## Project Status

**Initial development – Project structure established.**
