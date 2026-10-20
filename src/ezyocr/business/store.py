import hashlib
import json
import logging
import shutil
import time
from dataclasses import asdict, dataclass

from ezyocr.paths import business_scripts_dir

logger = logging.getLogger(__name__)

SCRIPT_FILE = "script.py"
META_FILE = "meta.json"


class DowngradeError(Exception):
    pass


@dataclass(frozen=True)
class InstalledScript:
    id: int
    title: str
    slug: str
    description: str
    updated_at: int
    sha256: str
    installed_at: int

    def to_dict(self):
        return asdict(self)


def sha256_of(content):
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


class BusinessScriptStore:
    def __init__(self, root=None):
        self._root = root or business_scripts_dir()

    def list(self):
        scripts = []
        for directory in sorted(self._root.iterdir()) if self._root.exists() else []:
            script = self._read_meta(directory)
            if script is not None:
                scripts.append(script)
        return sorted(scripts, key=lambda s: s.title.lower())

    def get(self, script_id):
        return self._read_meta(self._dir(script_id))

    def script_path(self, script_id):
        return self._dir(script_id) / SCRIPT_FILE

    def read_content(self, script_id):
        try:
            return self.script_path(script_id).read_text(encoding="utf-8")
        except OSError:
            return None

    def verify(self, script):
        content = self.read_content(script.id)
        return content is not None and sha256_of(content) == script.sha256

    def install(self, details, content):
        script_id = int(details["id"])
        updated_at = int(details.get("updatedAt") or 0)
        current = self.get(script_id)
        if current is not None and updated_at < current.updated_at:
            raise DowngradeError(script_id)
        script = InstalledScript(
            id=script_id,
            title=str(details.get("title") or ""),
            slug=str(details.get("slug") or ""),
            description=str(details.get("description") or ""),
            updated_at=updated_at,
            sha256=sha256_of(content),
            installed_at=int(time.time() * 1000),
        )
        target = self._dir(script_id)
        staging = self._root / f".{script_id}.tmp"
        shutil.rmtree(staging, ignore_errors=True)
        staging.mkdir(parents=True)
        (staging / SCRIPT_FILE).write_text(content, encoding="utf-8")
        (staging / META_FILE).write_text(json.dumps(script.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        shutil.rmtree(target, ignore_errors=True)
        staging.replace(target)
        logger.info("Installed business script %s (%s), sha256 %s", script.id, script.title, script.sha256)
        return script

    def remove(self, script_id):
        shutil.rmtree(self._dir(script_id), ignore_errors=True)

    def _dir(self, script_id):
        return self._root / str(int(script_id))

    def _read_meta(self, directory):
        try:
            data = json.loads((directory / META_FILE).read_text(encoding="utf-8"))
            return InstalledScript(**{k: data[k] for k in InstalledScript.__dataclass_fields__})
        except (OSError, ValueError, KeyError, TypeError):
            return None
