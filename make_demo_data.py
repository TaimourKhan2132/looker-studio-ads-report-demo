"""Generate synthetic daily ad data for a FICTIONAL Dubai dental clinic.

Output: ads_daily.csv (one row per date x campaign) in this script's folder.
Everything here is invented. No real business, account or platform data is used.

The file holds 90 days of "history" ending yesterday, plus FUTURE_DAYS of
pre-generated rows after that. The Looker Studio report hides any row dated
today or later, so each morning one more day "arrives" and the demo looks live
without anyone re-running this script.

Usage:
    python make_demo_data.py                  # history ends yesterday, + 365 future days
    python make_demo_data.py --end 2026-10-11 # history ends on a fixed date
    python make_demo_data.py --future-days 0  # history only
"""

import argparse
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

SEED = 42
HISTORY_DAYS = 90
FUTURE_DAYS = 365
BUDGET_INCREASE_DAY = 45  # 0-based index, so the increase starts on day 46 of history

# Benchmarks behind these numbers (estimates, not measured UAE data):
#   Google Search, dental: published US averages are ~USD 5-19 per click
#     (~AED 18-70) at ~3.5-5.5% CTR; Dubai agency pages quote AED 8-15.
#     Non-brand "Services" sits at AED ~13, CTR ~5%. Brand terms are cheap
#     and high-intent (AED ~4, CTR ~28%) because almost nobody else bids.
#   Performance Max mixes Search with Display/YouTube inventory, so clicks
#     are cheaper (AED ~5) and CTR much lower (~1.5%).
#   Meta, UAE healthcare: CTR averages ~1.5%; link clicks AED ~2.5-5.
#     Video awareness ads get views, not clicks, hence CTR ~0.4%.
#
# budget     = average daily spend in AED before the mid-period increase
# uplift     = budget multiplier applied from BUDGET_INCREASE_DAY onwards
# cvr        = click -> lead rate
# lead_value = average AED value attributed to one lead
CAMPAIGNS = [
    # channel,      campaign,            budget, uplift, cpc,  ctr,   cvr,   lead_value
    ("Google Ads", "Search: Brand",          60, 1.00,  4.0, 0.280, 0.140, 650),
    ("Google Ads", "Search: Services",      420, 1.35, 13.0, 0.050, 0.110, 520),
    ("Google Ads", "Performance Max",       220, 1.00,  5.0, 0.015, 0.035, 380),
    ("Meta Ads",   "Lead Form: Offer",      260, 1.35,  3.2, 0.016, 0.060, 240),
    ("Meta Ads",   "Retargeting",            90, 1.00,  2.6, 0.022, 0.045, 420),
    # The deliberate underperformer: real spend, almost no leads.
    ("Meta Ads",   "Awareness Video",       150, 1.00,  4.5, 0.004, 0.006, 200),
]

# Monday=0 ... Sunday=6. The UAE weekend is Saturday and Sunday; Friday is a short day.
# Search demand for a clinic drops when people are off work; Meta usage rises.
DOW_SPEND = {
    "Google Ads": [1.05, 1.08, 1.06, 1.02, 0.92, 0.74, 0.70],
    "Meta Ads":   [0.95, 0.96, 0.97, 1.00, 1.04, 1.12, 1.10],
}
# Weekend clicks convert a little worse on both channels (clinic phones are quieter).
DOW_CVR = [1.03, 1.05, 1.04, 1.00, 0.95, 0.85, 0.82]


def build(start: date, n_days: int) -> pd.DataFrame:
    rng = np.random.default_rng(SEED)
    rows = []
    for i in range(n_days):
        d = start + timedelta(days=i)
        dow = d.weekday()
        # A shared daily shock so campaigns wobble together a little (market noise).
        market = rng.lognormal(0, 0.06)
        for channel, campaign, budget, uplift, cpc, ctr, cvr, lead_value in CAMPAIGNS:
            if i >= BUDGET_INCREASE_DAY:
                budget = budget * uplift
            spend = budget * DOW_SPEND[channel][dow] * market * rng.lognormal(0, 0.12)
            day_cpc = cpc * rng.lognormal(0, 0.10)
            clicks = max(int(round(spend / day_cpc)), 0)
            day_ctr = ctr * rng.lognormal(0, 0.12)
            impressions = int(round(clicks / day_ctr)) if clicks else int(rng.integers(200, 800))
            day_cvr = min(cvr * DOW_CVR[dow] * rng.lognormal(0, 0.15), 1.0)
            leads = int(rng.binomial(clicks, day_cvr))
            value = leads * lead_value * rng.lognormal(0, 0.25) if leads else 0.0
            rows.append({
                "date": d.isoformat(),
                "channel": channel,
                "campaign": campaign,
                "spend_aed": round(spend, 2),
                "impressions": impressions,
                "clicks": clicks,
                "leads": leads,
                "conversions_value_aed": round(value, 2),
            })
    return pd.DataFrame(rows)


def add_ratios(t: pd.DataFrame) -> pd.DataFrame:
    """Ratios as sum / sum, the same way the Looker Studio fields are defined."""
    t = t.copy()
    t["ctr_%"] = 100 * t["clicks"] / t["impressions"]
    t["cpc"] = t["spend_aed"] / t["clicks"]
    t["cost_per_lead"] = t["spend_aed"] / t["leads"]
    t["conv_rate_%"] = 100 * t["leads"] / t["clicks"]
    t["roas"] = t["conversions_value_aed"] / t["spend_aed"]
    return t


SUMS = ["spend_aed", "impressions", "clicks", "leads", "conversions_value_aed"]


def compare(df: pd.DataFrame, today: date) -> pd.DataFrame:
    """What the Page 1 scorecards show on `today`: last 30 days vs the 30 before.

    Like Looker Studio's "Last 30 days", the window ends yesterday.
    """
    def window(first: int, last: int) -> pd.Series:
        lo = (today - timedelta(days=first)).isoformat()
        hi = (today - timedelta(days=last)).isoformat()
        return df[(df["date"] >= lo) & (df["date"] <= hi)][SUMS].sum()

    periods = add_ratios(pd.concat({
        "previous 30 days": window(60, 31),
        "last 30 days": window(30, 1),
    }, axis=1).T)
    periods.loc["change %"] = 100 * (periods.loc["last 30 days"] / periods.loc["previous 30 days"] - 1)
    return periods


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--end", type=date.fromisoformat,
                        default=date.today() - timedelta(days=1),
                        help="last day of history (YYYY-MM-DD), default yesterday")
    parser.add_argument("--future-days", type=int, default=FUTURE_DAYS,
                        help=f"days to pre-generate after --end, default {FUTURE_DAYS}")
    args = parser.parse_args()

    start = args.end - timedelta(days=HISTORY_DAYS - 1)
    df = build(start, HISTORY_DAYS + args.future_days)
    out = Path(__file__).with_name("ads_daily.csv")
    df.to_csv(out, index=False)

    pd.set_option("display.width", 200)
    pd.set_option("display.float_format", lambda x: f"{x:,.2f}")

    end = args.end.isoformat()
    history = df[df["date"] <= end]
    print(f"Wrote {len(df)} rows to {out}")
    print(f"History: {start} to {end}  "
          f"(budget increase from {start + timedelta(days=BUDGET_INCREASE_DAY)})")
    print(f"Future:  {args.future_days} pre-generated days, up to {df['date'].max()}\n")

    print(f"TOTALS, {HISTORY_DAYS} days of history")
    print(add_ratios(history[SUMS].sum().to_frame().T).to_string(index=False), "\n")

    print(f"BY CAMPAIGN, {HISTORY_DAYS} days of history")
    print(add_ratios(history.groupby(["channel", "campaign"], sort=False)[SUMS].sum()).to_string(), "\n")

    today = args.end + timedelta(days=1)
    cols = ["spend_aed", "leads", "cost_per_lead", "roas"]
    print(f"SCORECARDS on {today}: last 30 days vs previous 30 days")
    print(compare(df, today)[cols].to_string(), "\n")

    # How the story drifts as the demo ages and the window moves on.
    print("SCORECARD CHANGE % on later dates")
    later = {(today + timedelta(days=n)).isoformat(): compare(df, today + timedelta(days=n)).loc["change %", cols]
             for n in (30, 60, 120, 240) if n < args.future_days}
    if later:
        print(pd.DataFrame(later).T.to_string())


if __name__ == "__main__":
    main()
