"""Read-only official seven-pack / 66-component relation audit."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend import compendium
from backend.equipment_contents import audit


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    report=audit(compendium.COLLECTIONS)
    if args.output:args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report['summary'],sort_keys=True))
    return int(bool(report['diffs']) or not report['inventory_match'])


if __name__=='__main__':raise SystemExit(main())
