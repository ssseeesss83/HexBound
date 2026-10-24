"""Reproduce the official numeric comparison without modifying rules data."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend import compendium
from backend.class_growth import audit_growth


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, help='Optional full JSON evidence path')
    args = parser.parse_args()
    report = audit_growth(compendium.COLLECTIONS)
    if args.output:
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report['summary'], sort_keys=True))
    return int(bool(report['diffs'] or report['unreviewed_fields']))


if __name__ == '__main__':
    raise SystemExit(main())
