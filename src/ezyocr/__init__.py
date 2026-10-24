import tomllib
from importlib import metadata
from pathlib import Path


def _read_version():
    pyproject = Path(__file__).resolve().parents[2] / "pyproject.toml"
    if pyproject.is_file():
        with pyproject.open("rb") as f:
            project = tomllib.load(f).get("project", {})
        if project.get("name") == "ezyocr" and project.get("version"):
            return project["version"]
    try:
        return metadata.version("ezyocr")
    except metadata.PackageNotFoundError:
        return "0.0.0"


__version__ = _read_version()
