from pathlib import Path


def create_project_structure() -> None:
    """Create the project directory structure and Python packages."""

    # The project root is the directory containing this script.
    project_root = Path(__file__).resolve().parent

    # Prevent accidentally creating the structure in the wrong directory.
    if not (project_root / "pyproject.toml").exists():
        raise FileNotFoundError(
            "pyproject.toml not found. Place this script in the project root and run it again."
        )

    # Directories that should be importable Python packages.
    python_packages = [
        "src/market_intelligence",
        "src/market_intelligence/api",
        "src/market_intelligence/api/v1",
        "src/market_intelligence/api/v1/endpoints",
        "src/market_intelligence/core",
        "src/market_intelligence/db",
        "src/market_intelligence/db/models",
        "src/market_intelligence/db/repositories",
        "src/market_intelligence/schemas",
        "src/market_intelligence/services",
        "src/market_intelligence/analytics",
        "src/market_intelligence/sentiment",
        "src/market_intelligence/sentiment/training",
        "src/market_intelligence/sentiment/inference",
        "src/market_intelligence/mcp",
        "src/market_intelligence/mcp/internal_analytics",
        "src/market_intelligence/mcp/external_research",
        "src/market_intelligence/orchestration",
        "src/market_intelligence/orchestration/nodes",
        "src/market_intelligence/workers",
        "src/market_intelligence/cache",
        "src/market_intelligence/observability",
    ]

    # Supporting directories that do not need __init__.py.
    supporting_directories = [
        "src/market_intelligence/sentiment/datasets",
        "frontend",
        "tests/unit",
        "tests/integration",
        "tests/e2e",
        "docs/architecture",
        "docs/technical_design",
        "infrastructure/docker",
        "infrastructure/postgres",
        "infrastructure/redis",
        "data/raw",
        "data/interim",
        "data/processed",
        "data/external",
        "artifacts/sentiment",
    ]

    created_directories = 0
    created_package_files = 0
    created_placeholders = 0

    print(f"\nProject root: {project_root}\n")
    print("Creating project structure...\n")

    # Create Python package directories and their __init__.py files.
    for relative_path in python_packages:
        directory = project_root / relative_path
        directory.mkdir(parents=True, exist_ok=True)
        init_file = directory / "__init__.py"

        if not init_file.exists():
            init_file.touch()
            created_package_files += 1
            print(f"[PACKAGE] {relative_path}")

        created_directories += 1

    # Create supporting directories.
    for relative_path in supporting_directories:
        directory = project_root / relative_path
        directory.mkdir(parents=True, exist_ok=True)

        # Git does not track empty directories.
        # .gitkeep allows these directories to remain in the repository.
        gitkeep_file = directory / ".gitkeep"

        if not gitkeep_file.exists():
            gitkeep_file.touch()
            created_placeholders += 1
            print(f"[DIRECTORY] {relative_path}")

        created_directories += 1

    print("\n" + "=" * 55)
    print("PROJECT STRUCTURE CREATED SUCCESSFULLY")
    print("=" * 55)
    print(f"Directories processed : {created_directories}")
    print(f"Python package files  : {created_package_files}")
    print(f"Git placeholders     : {created_placeholders}")
    print(f"Project root         : {project_root}")
    print("=" * 55)


if __name__ == "__main__":
    create_project_structure()
