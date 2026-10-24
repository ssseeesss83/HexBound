"""Read-only official monster header/form/explicit-variant identity audit."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend import compendium
from backend.monster_inventory import audit


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path)
    args=parser.parse_args(); report=audit(compendium.COLLECTIONS)
    if args.output:args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({key:report[key] for key in ('official_stat_headers','normalized_records','candidate_records')}))
    return int(bool(report['differences'] or report['unmapped_records'] or report['duplicate_mappings']))


if __name__=='__main__':raise SystemExit(main())
