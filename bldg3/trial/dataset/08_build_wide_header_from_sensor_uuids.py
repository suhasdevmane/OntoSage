import os
import csv
from typing import List, Tuple


def read_sensor_uuids(file_path: str) -> List[Tuple[str, str]]:
    pairs: List[Tuple[str, str]] = []
    with open(file_path, newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        for row in reader:
            if not row or len(row) < 2:
                continue
            name, uid = row[0].strip(), row[1].strip()
            if name and uid:
                pairs.append((name, uid))
    return pairs


def build_header(pairs: List[Tuple[str, str]]) -> List[str]:
    # Wide header: datetime + each UUID as a column
    return ["datetime"] + [uid for _, uid in pairs]


def write_empty_csv(header: List[str], out_path: str) -> None:
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(header)


def main():
    base_dir = os.path.dirname(__file__)
    sensor_file = os.environ.get("SENSOR_UUIDS_FILE", os.path.join(base_dir, "sensor_uuids.txt"))
    out_csv = os.environ.get("OUT_CSV", os.path.join(base_dir, "synthetic_data_wide_header_only.csv"))

    pairs = read_sensor_uuids(sensor_file)
    if not pairs:
        raise SystemExit(f"No pairs found in {sensor_file}")

    header = build_header(pairs)
    write_empty_csv(header, out_csv)
    print(f"Wrote header with {len(header)} columns to {out_csv}")


if __name__ == "__main__":
    main()
