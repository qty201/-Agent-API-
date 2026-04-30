"""Tests for dependency scanners — Node.js and Python."""

import json
from pathlib import Path
import tempfile

import pytest
from scanners.node_scanner import NodeScanner
from scanners.python_scanner import PythonScanner


# ── helpers ────────────────────────────────────────────────────

@pytest.fixture
def node_project(tmp_path: Path) -> Path:
    """Create a sample Node.js project."""
    pkg = {
        "name": "test-project",
        "dependencies": {
            "react": "^18.2.0",
            "express": "^4.18.0",
        },
        "devDependencies": {
            "typescript": "^5.0.0",
        },
    }
    pkg_path = tmp_path / "package.json"
    pkg_path.write_text(json.dumps(pkg))
    return tmp_path


@pytest.fixture
def python_project(tmp_path: Path) -> Path:
    """Create a sample Python project with multiple manifest formats."""
    # requirements.txt
    (tmp_path / "requirements.txt").write_text(
        "requests>=2.28.0\nflask==2.3.0\nclick>=8.0\n"
    )
    return tmp_path


# ── Node.js scanner tests ──────────────────────────────────────

def test_node_scanner_discover(node_project: Path):
    scanner = NodeScanner()
    files = scanner.discover(node_project)
    assert len(files) >= 1
    assert any(f.format == "package_json" for f in files)


def test_node_scanner_parse(node_project: Path):
    scanner = NodeScanner()
    files = scanner.discover(node_project)
    for f in files:
        deps = scanner.parse(f)
        assert len(deps) >= 3  # react + express + typescript
        dep_names = {d.name for d in deps}
        assert "react" in dep_names
        assert "express" in dep_names
        assert "typescript" in dep_names


def test_node_scanner_clean_version():
    assert NodeScanner._clean_version("^18.2.0") == "18.2.0"
    assert NodeScanner._clean_version("~1.0.0") == "1.0.0"
    assert NodeScanner._clean_version(">=2.0.0") == "2.0.0"


def test_node_scanner_dev_deps(node_project: Path):
    scanner = NodeScanner()
    files = scanner.discover(node_project)
    for f in files:
        deps = scanner.parse(f)
        ts_dep = next(d for d in deps if d.name == "typescript")
        assert ts_dep.is_dev is True
        react_dep = next(d for d in deps if d.name == "react")
        assert react_dep.is_dev is False


# ── Python scanner tests ─────────────────────────────────────

def test_python_scanner_discover(python_project: Path):
    scanner = PythonScanner()
    files = scanner.discover(python_project)
    assert len(files) >= 1
    assert any(f.format == "requirements_txt" for f in files)


def test_python_scanner_parse_requirements(python_project: Path):
    scanner = PythonScanner()
    files = scanner.discover(python_project)
    for f in files:
        deps = scanner.parse(f)
        assert len(deps) >= 3
        dep_names = {d.name for d in deps}
        assert "requests" in dep_names
        assert "flask" in dep_names
        assert "click" in dep_names


def test_python_scanner_pyproject_toml(tmp_path: Path):
    toml_content = """
[project]
name = "test-pkg"
dependencies = [
    "httpx>=0.24.0",
    "pydantic>=2.0.0",
]
"""
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(toml_content)

    scanner = PythonScanner()
    files = scanner.discover(tmp_path)
    assert len(files) >= 1

    for f in files:
        if f.format == "pyproject_toml":
            deps = scanner.parse(f)
            dep_names = {d.name for d in deps}
            assert "httpx" in dep_names
            assert "pydantic" in dep_names


def test_node_scanner_monorepo_workspace(tmp_path: Path):
    """Test monorepo workspace discovery."""
    # Root package.json with workspaces
    pkg = {
        "name": "monorepo",
        "dependencies": {"lodash": "^4.0.0"},
        "workspaces": ["packages/*"],
    }
    (tmp_path / "package.json").write_text(json.dumps(pkg))

    # Workspace package
    pkg_dir = tmp_path / "packages" / "app"
    pkg_dir.mkdir(parents=True)
    pkg2 = {"name": "app", "dependencies": {"react": "^18.0.0"}}
    (pkg_dir / "package.json").write_text(json.dumps(pkg2))

    scanner = NodeScanner()
    files = scanner.discover(tmp_path)
    assert len(files) == 2  # root + workspace

    all_deps = []
    for f in files:
        all_deps.extend(scanner.parse(f))
    dep_names = {d.name for d in all_deps}
    assert "lodash" in dep_names
    assert "react" in dep_names
