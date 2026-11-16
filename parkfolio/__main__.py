from __future__ import annotations

import argparse
import json

from .batch import Batch
from .service import Parkfolio


def main() -> None:
    parser = argparse.ArgumentParser(description="Parkfolio offline data warehouse")
    parser.add_argument("--db", default="parkfolio.sqlite3")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("overview")
    for name in ("report", "quality", "preview"):
        sub.add_parser(name).add_argument("month")
    publish = sub.add_parser("publish")
    publish.add_argument("name")
    publish.add_argument("month")
    publish.add_argument("fingerprint")
    load = sub.add_parser("load")
    load.add_argument("batch_id")
    load.add_argument("file")
    load.add_argument("--stop-after", type=int)
    sub.add_parser("retry").add_argument("event_id", type=int)
    args = parser.parse_args()
    service = Parkfolio(args.db)
    if args.command == "overview":
        result = service.overview()
    elif args.command == "report":
        result = service.mart.period(args.month)
    elif args.command == "quality":
        result = service.quality.period(args.month)
    elif args.command == "preview":
        result = service.releases.preview(args.month)
    elif args.command == "publish":
        result = service.releases.publish(args.name, args.month, args.fingerprint)
    elif args.command == "load":
        result = Batch(service).from_file(args.batch_id, args.file, stop_after=args.stop_after)
    else:
        result = service.events.retry(args.event_id)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
