"""Scanner for Python projects — reads ``requirements.txt`` / ``pyproject.toml`` / ``setup.cfg``."""

from __future__ import annotations

import configparser
import re
from pathlib import Path

try:
    import tomllib  # Python ≥3.11
except ImportError:
    try:
        import tomli as tomllib  # pip install tomli
    except ImportError:
        tomllib = None  # type: ignore[assignment]

from scanners.base import BaseScanner, Dependency, DependencyFile


class PythonScanner(BaseScanner):
    """Discover and parse Python dependency manifests."""

    MANIFESTS = ("requirements.txt", "pyproject.toml", "setup.cfg", "setup.py")

    def discover(self, project_path: str | Path) -> list[DependencyFile]:
        root = Path(project_path).resolve()
        dep_files: list[DependencyFile] = []

        for name in self.MANIFESTS:
            path = root / name
            if path.exists():
                fmt = name.replace(".", "_")
                dep_files.append(DependencyFile(path=str(path), format=fmt))

        # Also check requirements/ directory
        req_dir = root / "requirements"
        if req_dir.is_dir():
            for f in sorted(req_dir.glob("*.txt")):
                dep_files.append(
                    DependencyFile(path=str(f), format="requirements_txt")
                )

        return dep_files

    def parse(self, dep_file: DependencyFile) -> list[Dependency]:
        fmt = dep_file.format
        parser = {
            "requirements_txt": self._parse_requirements_txt,
            "requirements.txt": self._parse_requirements_txt,
            "pyproject_toml": self._parse_pyproject_toml,
            "setup_cfg": self._parse_setup_cfg,
            "setup.py": self._parse_setup_py,
        }.get(fmt)

        if parser is None:
            return []

        deps = parser(Path(dep_file.path))
        dep_file.dependencies = deps
        return deps

    # ── format-specific parsers ────────────────────────────────

    RE_REQ = re.compile(r"^([a-zA-Z0-9_.-]+)\s*([><=!~]+)\s*([a-zA-Z0-9.*_-]+)")

    def _parse_requirements_txt(self, path: Path) -> list[Dependency]:
        deps: list[Dependency] = []
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith(("#", "-", "//")):
                    continue
                m = self.RE_REQ.match(line)
                if m:
                    deps.append(
                        Dependency(
                            name=m.group(1),
                            current_version=m.group(3),
                            source_file=str(path),
                        )
                    )
                else:
                    # bare name with no version pin
                    name = line.split("#")[0].strip()
                    if name and not name.startswith("-"):
                        deps.append(
                            Dependency(
                                name=name,
                                current_version="",
                                source_file=str(path),
                            )
                        )
        except FileNotFoundError:
            pass
        return deps

    def _parse_pyproject_toml(self, path: Path) -> list[Dependency]:
        deps: list[Dependency] = []
        if tomllib is None:
            return deps
        try:
            data = tomllib.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return deps

        # PEP 621: [project] dependencies
        for dep_str in data.get("project", {}).get("dependencies", []):
            dep = self._parse_pep508(dep_str)
            if dep:
                deps.append(dep)

        # [project.optional-dependencies]
        for group in data.get("project", {}).get("optional-dependencies", {}).values():
            for dep_str in group:
                dep = self._parse_pep508(dep_str)
                if dep:
                    deps.append(dep)

        # Poetry: [tool.poetry.dependencies]
        poetry_deps = (
            data.get("tool", {}).get("poetry", {}).get("dependencies", {})
        )
        for name, spec in poetry_deps.items():
            if name.lower() == "python":
                continue
            if isinstance(spec, str):
                deps.append(Dependency(name=name, current_version=spec, source_file=str(path)))
            elif isinstance(spec, dict):
                deps.append(
                    Dependency(
                        name=name,
                        current_version=spec.get("version", ""),
                        source_file=str(path),
                    )
                )

        return deps

    def _parse_pep508(self, dep_str: str) -> Dependency | None:
        """Parse a PEP 508 dependency string like ``requests>=2.28.0``."""
        m = re.match(r"^([a-zA-Z0-9_.-]+)\s*([><=!~]+)\s*([a-zA-Z0-9.*_-]+)", dep_str)
        if m:
            return Dependency(
                name=m.group(1),
                current_version=m.group(3),
                source_file="",
            )
        # bare name
        name = dep_str.strip().split("[")[0].split(";")[0].strip()
        if name:
            return Dependency(name=name, current_version="", source_file="")
        return None

    def _parse_setup_cfg(self, path: Path) -> list[Dependency]:
        deps: list[Dependency] = []
        config = configparser.ConfigParser()
        try:
            config.read(str(path), encoding="utf-8")
        except Exception:
            return deps

        for key in ("install_requires", "tests_require"):
            raw = config.get("options", key, fallback="")
            if raw:
                for line in raw.strip().splitlines():
                    line = line.strip()
                    if line and not line.startswith("#"):
                        m = self.RE_REQ.match(line)
                        if m:
                            deps.append(Dependency(name=m.group(1), current_version=m.group(3), source_file=str(path)))
        return deps

    def _parse_setup_py(self, path: Path) -> list[Dependency]:
        """Minimal heuristic — extract ``install_requires=[...]`` via regex."""
        deps: list[Dependency] = []
        try:
            text = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return deps

        m = re.search(r"install_requires\s*=\s*\[([^\]]+)\]", text, re.DOTALL)
        if m:
            for line in m.group(1).splitlines():
                line = line.strip().strip("'\"")
                if line and not line.startswith("#"):
                    dep = self._parse_pep508(line)
                    if dep:
                        deps.append(dep)
        return deps
