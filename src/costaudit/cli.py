"""costaudit snowflake queries.csv --credit-price 3 [--metering metering.csv] > report.md
costaudit redshift queries.csv --cluster-usd-per-hour 2.17 > report.md
"""

from __future__ import annotations

import argparse
import sys

from costaudit.detectors import run_all
from costaudit.model import load_redshift, load_snowflake, load_snowflake_metering
from costaudit.report import render


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(prog="costaudit")
    sub = parser.add_subparsers(dest="engine", required=True)
    sf = sub.add_parser("snowflake", help="CSV from queries/snowflake_export.sql")
    sf.add_argument("queries")
    sf.add_argument("--credit-price", type=float, required=True, help="USD per credit")
    sf.add_argument("--metering", help="CSV from queries/snowflake_metering.sql")
    rs = sub.add_parser("redshift", help="CSV from queries/redshift_export.sql")
    rs.add_argument("queries")
    rs.add_argument("--cluster-usd-per-hour", type=float, required=True, help="node price x node count")
    for engine in (sf, rs):
        engine.add_argument("-o", "--out", help="write the report here instead of stdout")
    args = parser.parse_args(argv)

    if args.engine == "snowflake":
        queries = load_snowflake(args.queries, args.credit_price)
        metering = load_snowflake_metering(args.metering) if args.metering else None
        findings = run_all(queries, metering, args.credit_price)
        billed = sum(m.credits for m in metering) * args.credit_price if metering else None
    else:
        queries = load_redshift(args.queries, args.cluster_usd_per_hour)
        findings = run_all(queries)
        billed = None
    report = render(queries, findings, source=f"{args.engine} export `{args.queries}`", billed_usd=billed)
    if args.out:
        with open(args.out, "w") as f:
            f.write(report)
    else:
        sys.stdout.write(report)


if __name__ == "__main__":
    main()
