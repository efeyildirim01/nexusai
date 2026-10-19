"""Deterministic report narrative, used when no language model is configured (and as the
fact sheet the model is given when one is)."""

from typing import Any


def _money(value: float) -> str:
    return f"{value:,.0f}"


def _change(pct: float | None) -> str:
    if pct is None:
        return "with no comparable previous period"
    direction = "up" if pct >= 0 else "down"
    return f"{direction} {abs(pct):.1f}% on the previous period"


def facts(overview: dict[str, Any]) -> dict[str, Any]:
    """The subset of the dashboard the narrative is allowed to talk about."""
    return {
        "period": overview["period"],
        "kpis": overview["kpis"],
        "change_vs_previous_period_pct": overview["deltas_pct"],
        "top_categories": overview["by_category"][:3],
        "top_regions": overview["by_region"][:3],
        "top_products": overview["top_products"][:3],
        "customer_mix": overview["customer_mix"],
        "anomalies": overview["anomalies"],
    }


def template(overview: dict[str, Any]) -> dict[str, Any]:
    k = overview["kpis"]
    d = overview["deltas_pct"]
    period = overview["period"]
    if not k["lines"]:
        return {
            "headline": "No sales data in this period yet.",
            "summary": "Upload a CSV or Excel file of sales to see a summary here.",
            "anomaly_explanations": [],
        }
    sentences = [
        f"Revenue was {_money(k['revenue'])} from {k['orders']:,} orders, {_change(d['revenue'])}.",
        f"The average order was worth {k['average_order_value']:,.2f}"
        + (
            f" and gross margin was {k['gross_margin_pct']:.1f}%." if k["gross_margin_pct"] else "."
        ),
    ]
    if overview["by_category"]:
        top = overview["by_category"][0]
        share = top["revenue"] / k["revenue"] * 100 if k["revenue"] else 0
        sentences.append(f"{top['key']} was the largest category at {share:.0f}% of revenue.")
    if k["return_rate_pct"]:
        sentences.append(f"Returns took {k['return_rate_pct']:.1f}% of gross sales.")
    mix = overview["customer_mix"]
    if mix["new"] or mix["returning"]:
        sentences.append(
            f"{mix['new']:,} customers bought for the first time and "
            f"{mix['returning']:,} came back."
        )
    explanations = [
        f"{a['period']}: revenue of {_money(a['revenue'])} against an expected "
        f"{_money(a['expected'])} ({a['direction']}). Check for bulk orders, promotions, "
        "outages or data-entry errors on that date."
        for a in overview["anomalies"]
    ]
    return {
        "headline": f"Revenue {_money(k['revenue'])} for {period['date_from']} to "
        f"{period['date_to']}, {_change(d['revenue'])}.",
        "summary": " ".join(sentences),
        "anomaly_explanations": explanations,
    }
