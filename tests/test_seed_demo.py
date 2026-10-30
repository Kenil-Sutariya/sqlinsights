from __future__ import annotations

from pathlib import Path

from scripts.seed_demo import generate


def test_generation_matches_committed_fixtures(tmp_path: Path) -> None:
    generated = tmp_path / "sample_data"
    generate(generated)
    committed = Path(__file__).resolve().parents[1] / "sample_data"
    for filename in ("customers.csv", "products.csv", "orders.csv"):
        assert (generated / filename).read_bytes() == (committed / filename).read_bytes()
