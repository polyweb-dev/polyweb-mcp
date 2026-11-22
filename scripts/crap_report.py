# /// script
# requires-python = ">=3.12"
# dependencies = ["edn-format>=0.7.5,<0.8"]
# ///
"""Print high CRAP scores and functions without a score from a Crapper snapshot."""

import argparse
from pathlib import Path

import edn_format


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "snapshot",
        nargs="?",
        type=Path,
        default=Path(__file__).resolve().parent.parent / ".metrics" / "crap.edn",
        help="Crapper EDN snapshot (default: repository .metrics/crap.edn)",
    )
    parser.add_argument(
        "--threshold", type=float, default=30, help="Show scores above this value (default: 30)"
    )
    args = parser.parse_args()
    try:
        data = edn_format.loads(args.snapshot.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        parser.error(f"Cannot read snapshot {args.snapshot}: {exc}")

    key = edn_format.Keyword
    entries = data[key("entries")]
    scored = [
        entry
        for entry in entries
        if entry[key("crap")] is not None and entry[key("crap")] > args.threshold
    ]
    missing = [entry for entry in entries if entry[key("crap")] is None]
    scored.sort(key=lambda entry: entry[key("crap")], reverse=True)
    missing.sort(key=lambda entry: (entry[key("namespace")], entry[key("name")]))

    print(f"{'CRAP':>8}  Function")
    for entry in [*scored, *missing]:
        score = entry[key("crap")]
        score_text = "nil" if score is None else f"{score:.4f}"
        print(f"{score_text:>8}  {entry[key('namespace')]}.{entry[key('name')]}")


if __name__ == "__main__":
    main()
