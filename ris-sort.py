#!/usr/bin/env python3
"""Sort a RIS file by author (AU), date (DA/PY), and title (TI).

Usage:
    ris-sort.py file.ris      # sort specified file
    ris-sort.py               # sort the single .ris file in current directory
"""

import sys
import glob


def find_ris_file():
    files = glob.glob("*.ris")
    if len(files) == 1:
        return files[0]
    if len(files) == 0:
        print("Error: no RIS file found in current directory.", file=sys.stderr)
    else:
        names = ", ".join(files)
        print(f"Error: multiple RIS files found: {names}", file=sys.stderr)
    sys.exit(1)


def parse_ris(path):
    with open(path, encoding="utf-8") as f:
        lines = f.readlines()

    records = []
    current = []

    for line in lines:
        stripped = line.rstrip("\r\n")
        if not stripped.strip():
            continue  # skip blank lines between records
        current.append(stripped)
        if stripped[:2] == "ER":
            records.append(current)
            current = []

    if current:  # trailing incomplete record
        records.append(current)

    return records


def extract_field(record_lines, *tags):
    """Return value of the first matching tag, in tag-priority order."""
    found = {}
    for line in record_lines:
        if len(line) >= 6 and line[2:6] == "  - ":
            tag = line[:2]
            if tag in tags and tag not in found:
                found[tag] = line[6:].strip()
    for tag in tags:
        if tag in found:
            return found[tag]
    return ""


def sort_key(record_lines):
    au = extract_field(record_lines, "AU").lower()
    date = extract_field(record_lines, "DA", "PY").lower()
    ti = extract_field(record_lines, "TI").lower()
    return (au, date, ti)


def write_ris(records, path):
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        for i, record in enumerate(records):
            for line in record:
                f.write(line + "\n")
            if i < len(records) - 1:
                f.write("\n")


def main():
    if len(sys.argv) == 2:
        path = sys.argv[1]
    elif len(sys.argv) == 1:
        path = find_ris_file()
    else:
        print("Usage: ris-sort.py [file.ris]", file=sys.stderr)
        sys.exit(1)

    stem = path[:-4] if path.lower().endswith(".ris") else path
    out_path = stem + "-sorted.ris"

    records = parse_ris(path)
    records.sort(key=sort_key)
    write_ris(records, out_path)
    print(f"Sorted {len(records)} records → {out_path}")


if __name__ == "__main__":
    main()
