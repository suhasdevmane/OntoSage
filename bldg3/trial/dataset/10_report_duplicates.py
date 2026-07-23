import os
import csv
from collections import Counter, defaultdict


def main():
    base_dir = os.path.dirname(__file__)
    sensor_file = os.environ.get("SENSOR_UUIDS_FILE", os.path.join(base_dir, "sensor_uuids.txt"))

    names = []
    uuids = []
    rows = []
    with open(sensor_file, newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        for row in reader:
            if not row or len(row) < 2:
                continue
            name, uid = row[0].strip(), row[1].strip()
            if not name or not uid:
                continue
            rows.append((name, uid))
            names.append(name)
            uuids.append(uid)

    name_counts = Counter(names)
    uuid_counts = Counter(uuids)

    dup_names = [n for n, c in name_counts.items() if c > 1]
    dup_uuids = [u for u, c in uuid_counts.items() if c > 1]

    print(f"Total rows: {len(rows)} | unique names: {len(name_counts)} | unique uuids: {len(uuid_counts)}")
    if dup_names:
        print(f"Duplicate names ({len(dup_names)}):")
        for n in dup_names:
            print(" -", n)
    else:
        print("No duplicate device names found.")

    if dup_uuids:
        print(f"Duplicate UUIDs ({len(dup_uuids)}):")
        for u in dup_uuids:
            print(" -", u)
    else:
        print("No duplicate UUIDs found.")


if __name__ == "__main__":
    main()
