import csv
import json
import os
import sys
import time
from pathlib import Path

os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")

import cv2
from paddleocr import PaddleOCR

from ezyocr.recognition.backends.paddle import lines_from_paddle
from ezyocr.recognition.extract import extract_waybill

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
OUTPUT_DIR = Path("output")
CUSTOMERS_FILE = Path("customers.txt")


def load_customers():
    if not CUSTOMERS_FILE.exists():
        return set()
    with open(CUSTOMERS_FILE, encoding="utf-8") as f:
        return {line.strip().upper() for line in f if line.strip()}


def process(ocr, path, customers):
    image = cv2.imread(str(path))
    result = list(ocr.predict(str(path)))[0]
    lines = lines_from_paddle(result.json["res"])
    result.save_to_img(str(OUTPUT_DIR))
    waybill = extract_waybill(lines, image, customers)
    return {
        "file": path.name,
        "carrier": waybill["carrier"],
        "tracking_number": waybill["tracking_number"],
        "tracking_source": waybill["tracking_source"],
        "master_tracking_number": waybill["master_tracking_number"],
        "customer_code": waybill["customer_code"],
        "customer_code_source": waybill["customer_code_source"],
        "customer_candidates": "|".join(waybill["customer_candidates"]),
    }


def list_images(args):
    paths = []
    for arg in args or ["images"]:
        p = Path(arg)
        if p.is_dir():
            paths.extend(sorted(f for f in p.iterdir() if f.suffix.lower() in IMAGE_EXTS))
        else:
            paths.append(p)
    return paths


def main():
    OUTPUT_DIR.mkdir(exist_ok=True)
    init_start = time.perf_counter()
    ocr = PaddleOCR(
        lang="ch",
        engine="onnxruntime",
        use_doc_orientation_classify=True,
        use_doc_unwarping=False,
        use_textline_orientation=False,
    )
    init_seconds = time.perf_counter() - init_start
    print(f"Model init: {init_seconds:.2f}s")
    customers = load_customers()
    print(f"Customers loaded: {len(customers)}")

    rows = []
    durations = []
    for path in list_images(sys.argv[1:]):
        start = time.perf_counter()
        row = process(ocr, path, customers)
        elapsed = time.perf_counter() - start
        durations.append(elapsed)
        row["elapsed_seconds"] = round(elapsed, 2)
        rows.append(row)
        print(f"[{elapsed:.2f}s] {json.dumps(row, ensure_ascii=False)}")

    if durations:
        total = sum(durations)
        print(
            f"Images: {len(durations)} | total: {total:.2f}s | avg: {total / len(durations):.2f}s"
            f" | min: {min(durations):.2f}s | max: {max(durations):.2f}s"
            f" | with init: {init_seconds + total:.2f}s"
        )

    with open(OUTPUT_DIR / "waybills.json", "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=2)
    with open(OUTPUT_DIR / "waybills.csv", "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()) if rows else [])
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    main()
