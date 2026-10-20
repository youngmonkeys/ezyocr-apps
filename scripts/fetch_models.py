import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TARGET = ROOT / "src" / "ezyocr" / "resources" / "models"


def main():
    with tempfile.TemporaryDirectory(prefix="paddlex-") as cache_home:
        os.environ["PADDLE_PDX_CACHE_HOME"] = cache_home
        os.environ["PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK"] = "True"
        from paddleocr import PaddleOCR

        PaddleOCR(
            lang="ch",
            engine="onnxruntime",
            use_doc_orientation_classify=True,
            use_doc_unwarping=False,
            use_textline_orientation=False,
        )
        downloaded = Path(cache_home) / "official_models"
        models = sorted(p for p in downloaded.iterdir() if p.is_dir())
        if not models:
            sys.exit("No models were downloaded")

        TARGET.mkdir(parents=True, exist_ok=True)
        for old in (p for p in TARGET.iterdir() if p.is_dir()):
            shutil.rmtree(old)
        for model in models:
            shutil.copytree(model, TARGET / model.name)
            print(f"Bundled {model.name}")
    print(f"Models are in {TARGET}")


if __name__ == "__main__":
    main()
