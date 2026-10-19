"""Deterministic, realistic demo data: seasonality, weekly cycle, growth, returns, and one
injected revenue anomaly (a spike) so dashboards and anomaly detection have something to show.

    python -m app.sample_data --rows 5000 --out sample-sales.csv
"""

import argparse
import math
import random
from datetime import date, timedelta

import pandas as pd

PRODUCTS = {
    "Hardware": [("Widget Pro", 49.99, 22.0), ("Widget Mini", 19.99, 8.5), ("Hub X", 129.0, 70.0)],
    "Software": [("Analytics Seat", 39.0, 4.0), ("API Credits", 9.99, 1.2)],
    "Services": [("Onboarding", 450.0, 260.0), ("Support Plan", 99.0, 35.0)],
}
REGIONS = ["UK", "Germany", "France", "Netherlands", "Turkey", "USA"]
CHANNELS = ["Online", "Partner", "Direct"]


def generate(
    rows: int = 5000, start: date = date(2025, 1, 1), days: int = 365, seed: int = 7
) -> pd.DataFrame:
    rng = random.Random(seed)  # noqa: S311 - reproducible demo data, not security
    customers = [(f"C-{i:04d}", f"Customer {i:04d}") for i in range(1, max(20, rows // 12))]
    spike_day = start + timedelta(days=int(days * 0.7))
    weights = []
    for d in range(days):
        day = start + timedelta(days=d)
        season = 1 + 0.25 * math.sin(2 * math.pi * (d / 365) - math.pi / 2) * -1
        weekly = 0.6 if day.weekday() >= 5 else 1.0
        growth = 1 + 0.5 * d / days
        weights.append(season * weekly * growth)
    day_choices = rng.choices(range(days), weights=weights, k=rows)

    records = []
    for n, d in enumerate(sorted(day_choices)):
        day = start + timedelta(days=d)
        category = rng.choices(list(PRODUCTS), weights=[5, 3, 1])[0]
        product, price, cost = rng.choice(PRODUCTS[category])
        quantity = rng.choices([1, 2, 3, 5, 10], weights=[50, 25, 12, 8, 5])[0]
        if category == "Services":
            quantity = 1  # nobody buys ten onboarding packages
        if day == spike_day:
            quantity *= 25  # the anomaly: a bulk-order day, far outside normal variation
        discount = rng.choice([0, 0, 0, 0.05, 0.1, 0.15])
        status = rng.choices(["completed", "returned", "cancelled"], weights=[92, 5, 3])[0]
        customer_id, customer_name = rng.choice(customers)
        revenue = round(quantity * price * (1 - discount), 2)
        records.append(
            {
                "order_id": f"SO-{100000 + n}",
                "order_date": day.isoformat(),
                "customer_id": customer_id,
                "customer_name": customer_name,
                "product": product,
                "category": category,
                "region": rng.choices(REGIONS, weights=[30, 20, 15, 10, 10, 15])[0],
                "channel": rng.choices(CHANNELS, weights=[60, 25, 15])[0],
                "status": status,
                "quantity": quantity,
                "unit_price": price,
                "discount": discount,
                "revenue": revenue,
                "cost": round(quantity * cost, 2),
            }
        )
    return pd.DataFrame.from_records(records)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rows", type=int, default=5000)
    parser.add_argument("--out", default="sample-sales.csv")
    parser.add_argument("--xlsx", action="store_true", help="write Excel instead of CSV")
    args = parser.parse_args()
    df = generate(args.rows)
    if args.xlsx:
        df.to_excel(args.out, index=False)
    else:
        df.to_csv(args.out, index=False)
    print(f"Wrote {len(df)} rows to {args.out}")


if __name__ == "__main__":
    main()
