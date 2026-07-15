"""Generate the Power BI pitch dataset (``sample_events.csv``) from the deterministic demo seed.

Run from the ``foundry`` directory:

    python powerbi/generate.py   # writes powerbi/sample_events.csv

The CSV is a stand-in for the Cosmos DB -> OneLake mirror a real deployment would feed Power BI.
"""

from __future__ import annotations

from pathlib import Path

from airacare_foundry.tools.demo_seed import generate_events, to_records
from airacare_foundry.tools.powerbi_export import export_records


def main() -> None:
    records = to_records(generate_events())
    out = Path(__file__).parent / "sample_events.csv"
    export_records(records, out)
    print(f"wrote {len(records)} rows -> {out}")


if __name__ == "__main__":
    main()
