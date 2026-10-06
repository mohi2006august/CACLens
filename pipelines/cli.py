"""`caclens` command line: refresh data, run alerts, ask questions, run the Q&A eval."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence

from api.config import get_settings
from api.log import configure_logging


def _cmd_refresh(args: argparse.Namespace) -> int:
    from pipelines.refresh import DbtBuildFailed, refresh

    try:
        summary = refresh(demo=args.demo, scale=args.scale)
    except DbtBuildFailed as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(summary, indent=2, default=str))
    return 0


def _cmd_load(args: argparse.Namespace) -> int:
    from pipelines.demo import load_demo
    from pipelines.load import load_sources

    settings = get_settings()
    if args.demo:
        print(json.dumps(load_demo(settings.warehouse_path, scale=args.scale), indent=2))
    else:
        print(json.dumps(load_sources(settings.warehouse_path, args.source or None), indent=2))
    return 0


def _cmd_alerts(_args: argparse.Namespace) -> int:
    from pipelines.refresh import compute_alerts, publish

    settings = get_settings()
    print(f"{compute_alerts(settings)} alert episodes saved")
    print(f"published {publish(settings).name}")
    return 0


def _cmd_ask(args: argparse.Namespace) -> int:
    from api import qa

    answer = qa.ask(" ".join(args.question), fully_loaded=args.fully_loaded,
                    attribution_model=args.attribution)
    print(answer.answer)
    if args.verbose:
        print(json.dumps(answer.queries, indent=2, default=str))
    return 0


def _cmd_eval(args: argparse.Namespace) -> int:
    from api.qa.eval import main as eval_main

    return eval_main(planner=args.planner, limit=args.limit, verbose=args.verbose)


def _cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    uvicorn.run("api.main:app", host=args.host, port=args.port, reload=args.reload)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="caclens", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("refresh", help="load raw data, dbt build, alerts, publish snapshot")
    p.add_argument("--demo", action=argparse.BooleanOptionalAction, default=None,
                   help="use the synthetic dataset (default: CACLENS_DEMO)")
    p.add_argument("--scale", type=float, default=1.0, help="demo data volume multiplier")
    p.set_defaults(func=_cmd_refresh)

    p = sub.add_parser("load", help="load raw data only")
    p.add_argument("--demo", action="store_true", help="load the synthetic dataset")
    p.add_argument("--scale", type=float, default=1.0)
    p.add_argument("--source", action="append", help="limit to a source (repeatable)")
    p.set_defaults(func=_cmd_load)

    p = sub.add_parser("alerts", help="recompute CAC alerts and republish")
    p.set_defaults(func=_cmd_alerts)

    p = sub.add_parser("ask", help="ask a question in plain English")
    p.add_argument("question", nargs="+")
    p.add_argument("--fully-loaded", action="store_true")
    p.add_argument("--attribution", default="position_based")
    p.add_argument("-v", "--verbose", action="store_true", help="print the queries used")
    p.set_defaults(func=_cmd_ask)

    p = sub.add_parser("eval", help="run the Q&A eval (evals/qa_questions.yml)")
    p.add_argument("--planner", choices=["rules", "claude"], default="rules")
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("-v", "--verbose", action="store_true")
    p.set_defaults(func=_cmd_eval)

    p = sub.add_parser("serve", help="run the API")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--reload", action="store_true")
    p.set_defaults(func=_cmd_serve)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    configure_logging()
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
