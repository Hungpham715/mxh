"""Command-line entry point: python -m src.cli <command> [options]."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

from src.common import EVAL, OUTPUT, PROCESSED, RAW, ROOT, load_env, log, read_json, read_jsonl, scrub, setup_logging


def _yaml(path: str) -> dict:
    with open(ROOT / path if not Path(path).is_absolute() else path, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def cmd_fetch(a: argparse.Namespace) -> int:
    from src.data.acl_fetch import fetch_acl
    from src.data.arxiv_fetch import fetch_arxiv
    from src.data.openalex_enrich import enrich
    scope = _yaml(a.config)
    acl = fetch_acl(scope)
    arx = [] if a.skip_arxiv else fetch_arxiv(scope)
    enrich(scope, acl + arx)
    log.info("fetch complete: %d ACL + %d arXiv records", len(acl), len(arx))
    return 0


def cmd_prepare(a: argparse.Namespace) -> int:
    from src.data.export import export
    from src.data.normalize import Normalizer
    from src.data.topics import TopicClassifier
    scope = _yaml(a.scope)
    acl = read_jsonl(RAW / "acl_selected.jsonl")
    arx = read_jsonl(RAW / "arxiv_selected.jsonl") if (RAW / "arxiv_selected.jsonl").exists() else []
    oa = read_jsonl(RAW / "openalex_works.jsonl")
    norm = Normalizer(acl, arx, oa)
    ents = norm.run()
    clf = TopicClassifier.from_file(ROOT / a.config)
    sv = {"acl_anthology": "acl-org/acl-anthology master XML, accessed " + scope["snapshot_date"],
          "arxiv": "export.arxiv.org Atom API, accessed " + scope["snapshot_date"],
          "openalex": "api.openalex.org single-work DOI lookup, accessed " + scope["snapshot_date"],
          "scope_config": scope["scope_id"]}
    ic = {"acl_selected": len(acl), "arxiv_selected": len(arx), "openalex_lookups": len(oa),
          "openalex_matched": sum(1 for r in oa if r["openalex"])}
    export(ents, clf, ic, sv, dict(norm.stats), PROCESSED if not a.out else Path(a.out))
    return 0


def cmd_validate(a: argparse.Namespace) -> int:
    from src.data.contracts import ContractError, load_dataset
    try:
        rows = load_dataset(Path(a.data))
    except ContractError as exc:
        for e in exc.errors[:50]:
            print("ERROR", e)
        print(f"VALIDATION FAILED: {len(exc.errors)} error(s)")
        return 2
    for k, v in rows.items():
        print(f"{k:22s} {len(v):7d} rows OK")
    print("VALIDATION PASSED (schema, keys, foreign keys, spans, checksums)")
    return 0


def cmd_import(a: argparse.Namespace) -> int:
    from src.graph.load import run_import
    return run_import(Path(a.data), dry_run=a.dry_run, batch_size=a.batch_size)


def cmd_preflight(a: argparse.Namespace) -> int:
    from src.graph.load import preflight
    return preflight()


def cmd_idem(a: argparse.Namespace) -> int:
    from src.graph.checks import idempotency_check
    return idempotency_check(Path(a.data))


def cmd_queries(a: argparse.Namespace) -> int:
    from src.graph.checks import example_queries
    return example_queries()


def cmd_analyze(a: argparse.Namespace) -> int:
    from src.analysis.run import run_analysis
    return run_analysis(Path(a.data), Path(a.out), source=a.source)


def cmd_sample(a: argparse.Namespace) -> int:
    from src.evaluation.sample_edges import run_sample
    return run_sample(per_type=a.per_type, seed=a.seed, tag=a.tag)


def cmd_score(a: argparse.Namespace) -> int:
    from src.evaluation.score import run_score
    return run_score(Path(a.labels), tag=f"_{a.tag}" if a.tag else "")


def cmd_report(a: argparse.Namespace) -> int:
    from src.report.build import build_report
    return build_report(Path(a.out))


def main(argv: list[str] | None = None) -> int:
    load_env()
    setup_logging()
    p = argparse.ArgumentParser(prog="python -m src.cli", description="NLP/LLM collaboration graph pipeline")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("fetch", help="fetch ACL + arXiv metadata and OpenAlex enrichment (cached)")
    s.add_argument("--config", default="configs/scope.yaml")
    s.add_argument("--skip-arxiv", action="store_true")
    s.set_defaults(fn=cmd_fetch)
    s = sub.add_parser("prepare", help="normalise, label topics, export 8 JSONL + manifest")
    s.add_argument("--config", default="configs/topics.yaml")
    s.add_argument("--scope", default="configs/scope.yaml")
    s.add_argument("--out", default=None)
    s.set_defaults(fn=cmd_prepare)
    s = sub.add_parser("validate", help="validate data contract + checksums")
    s.add_argument("--data", default=str(PROCESSED))
    s.set_defaults(fn=cmd_validate)
    s = sub.add_parser("preflight", help="read-only Neo4j Aura connectivity + inventory check")
    s.set_defaults(fn=cmd_preflight)
    s = sub.add_parser("idempotency", help="re-import same snapshot and assert identical counts")
    s.add_argument("--data", default=str(PROCESSED))
    s.set_defaults(fn=cmd_idem)
    s = sub.add_parser("queries", help="run example Cypher queries on Neo4j and save results")
    s.set_defaults(fn=cmd_queries)
    s = sub.add_parser("import", help="import processed snapshot into Neo4j (idempotent MERGE)")
    s.add_argument("--data", default=str(PROCESSED))
    s.add_argument("--dry-run", action="store_true")
    s.add_argument("--batch-size", type=int, default=300)
    s.set_defaults(fn=cmd_import)
    s = sub.add_parser("analyze", help="author-only co-authorship network analysis")
    s.add_argument("--data", default=str(PROCESSED))
    s.add_argument("--out", default=str(OUTPUT / "analysis"))
    s.add_argument("--source", choices=["local", "neo4j"], default="local",
                   help="build the projection from the local derived edges (default) or from Neo4j")
    s.set_defaults(fn=cmd_analyze)
    s = sub.add_parser("sample", help="stratified edge sample for QA")
    s.add_argument("--per-type", type=int, default=20)
    s.add_argument("--seed", type=int, default=20261107)
    s.add_argument("--tag", default=None, help="suffix for a re-evaluation round, e.g. postfix")
    s.set_defaults(fn=cmd_sample)
    s = sub.add_parser("score", help="precision / Wilson CI from labels")
    s.add_argument("--labels", default=str(EVAL / "labels.csv"))
    s.add_argument("--tag", default=None)
    s.set_defaults(fn=cmd_score)
    s = sub.add_parser("report", help="build the Vietnamese PDF report")
    s.add_argument("--out", default=str(ROOT / "report" / "final.pdf"))
    s.set_defaults(fn=cmd_report)
    args = p.parse_args(argv)
    try:
        return int(args.fn(args) or 0)
    except KeyboardInterrupt:
        return 130
    except Exception as exc:  # report sanitized error, non-zero exit
        log.error("command %s failed: %s", args.cmd, scrub(f"{type(exc).__name__}: {exc}"))
        import traceback
        print(scrub(traceback.format_exc()), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
