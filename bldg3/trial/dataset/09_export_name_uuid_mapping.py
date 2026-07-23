import os
import csv
import json
from typing import Dict, List, Tuple


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


def main():
    base_dir = os.path.dirname(__file__)
    sensor_file = os.environ.get("SENSOR_UUIDS_FILE", os.path.join(base_dir, "sensor_uuids.txt"))
    out_dir = os.environ.get("OUT_DIR", base_dir)

    pairs = read_sensor_uuids(sensor_file)
    if not pairs:
        raise SystemExit(f"No name,uuid pairs found in {sensor_file}")

    name_to_uuid: Dict[str, str] = {name: uid for name, uid in pairs}
    uuid_to_name: Dict[str, str] = {uid: name for name, uid in pairs}

    os.makedirs(out_dir, exist_ok=True)
    name_to_uuid_path = os.path.join(out_dir, "name_to_uuid.json")
    uuid_to_name_path = os.path.join(out_dir, "uuid_to_name.json")

    with open(name_to_uuid_path, "w", encoding="utf-8") as f:
        json.dump(name_to_uuid, f, ensure_ascii=False, indent=2)
    with open(uuid_to_name_path, "w", encoding="utf-8") as f:
        json.dump(uuid_to_name, f, ensure_ascii=False, indent=2)

    print(f"Wrote {len(name_to_uuid)} mappings to:\n - {name_to_uuid_path}\n - {uuid_to_name_path}")


if __name__ == "__main__":
    main()
