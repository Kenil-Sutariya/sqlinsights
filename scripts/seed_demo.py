from __future__ import annotations

import argparse
import csv
from pathlib import Path

CUSTOMERS = [
    ("C001", "Berlin", "Consumer"),
    ("C002", "Hamburg", "Small Business"),
    ("C003", "Munich", "Consumer"),
    ("C004", "Cologne", "Enterprise"),
    ("C005", "Frankfurt", "Small Business"),
    ("C006", "Leipzig", "Consumer"),
]

PRODUCTS = [
    ("P001", "Office", "Desk Lamp"),
    ("P002", "Office", "Notebook Set"),
    ("P003", "Electronics", "USB-C Hub"),
    ("P004", "Electronics", "Wireless Mouse"),
    ("P005", "Home", "Storage Basket"),
    ("P006", "Home", "Water Bottle"),
]

ORDERS = [
    ("O0001", "C001", "P003", "2026-08-28", 2, "39.90"),
    ("O0002", "C002", "P001", "2026-09-01", 3, "24.50"),
    ("O0003", "C003", "P004", "2026-09-03", 2, "21.00"),
    ("O0004", "C001", "P002", "2026-09-04", 5, "8.50"),
    ("O0005", "C004", "P003", "2026-09-06", 6, "39.90"),
    ("O0006", "C005", "P005", "2026-09-10", 4, "16.25"),
    ("O0007", "C006", "P006", "2026-09-12", 3, "14.00"),
    ("O0008", "C002", "P004", "2026-09-15", 7, "21.00"),
    ("O0009", "C003", "P001", "2026-09-18", 1, "24.50"),
    ("O0010", "C004", "P003", "2026-09-21", 2, "39.90"),
    ("O0011", "C005", "P002", "2026-09-24", 8, "8.50"),
    ("O0012", "C006", "P005", "2026-09-28", 2, "16.25"),
    ("O0013", "C001", "P006", "2026-10-02", 4, "14.00"),
    ("O0014", "C002", "P003", "2026-10-05", 1, "39.90"),
    ("O0015", "C003", "P004", "2026-10-08", 3, "21.00"),
    ("O0016", "C004", "P001", "2026-10-11", 5, "24.50"),
    ("O0017", "C005", "P005", "2026-10-14", 2, "16.25"),
    ("O0018", "C006", "P002", "2026-10-18", 6, "8.50"),
]


def write_csv(path: Path, headers: tuple[str, ...], rows: list[tuple[object, ...]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(headers)
        writer.writerows(rows)


def generate(output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    write_csv(output_dir / "customers.csv", ("customer_id", "city", "segment"), CUSTOMERS)
    write_csv(output_dir / "products.csv", ("product_id", "category", "product_name"), PRODUCTS)
    write_csv(
        output_dir / "orders.csv",
        ("order_id", "customer_id", "product_id", "order_date", "quantity", "unit_price"),
        ORDERS,
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate the deterministic synthetic retail CSVs."
    )
    parser.add_argument("--output-dir", type=Path, default=Path("sample_data"))
    args = parser.parse_args()
    generate(args.output_dir)


if __name__ == "__main__":
    main()
