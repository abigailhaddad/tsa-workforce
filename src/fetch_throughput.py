"""Fetch TSA's published national daily checkpoint passenger counts (https://www.tsa.gov/travel/passenger-volumes, one page
per year, 2019 on) into data/tsa_daily_passengers.csv, with checks that the series is complete.

These are passengers screened, NOT wait times: TSA records wait times at every checkpoint every hour but does not publish them.
The counts cover every checkpoint TSA oversees, including airports where private contractors do the screening, so they are a
workload measure for the whole system, not only for TSA's own employees.

Writes data/tsa_daily_passengers.csv (date, passengers) and data/throughput_meta.json (fetch date, first/last day).
"""
import datetime, io, json
import pandas as pd
import requests
import tsa

URL = "https://www.tsa.gov/travel/passenger-volumes"
FIRST_YEAR = 2019
HEADERS = {"User-Agent": "Mozilla/5.0 (research; github.com/abigailhaddad/tsa-workforce)"}

frames = []
for year in range(FIRST_YEAR, datetime.date.today().year + 1):
    url = URL if year == datetime.date.today().year else f"{URL}/{year}"
    html = requests.get(url, headers=HEADERS, timeout=60).text
    t = pd.read_html(io.StringIO(html))[0]
    t.columns = ["date", "passengers"]
    t["date"] = pd.to_datetime(t["date"], format="%m/%d/%Y")
    assert (t.date.dt.year == year).all(), f"{url} has dates outside {year}"
    frames.append(t)
    print(year, len(t), "days", t.date.min().date(), "to", t.date.max().date())

d = pd.concat(frames).sort_values("date").reset_index(drop=True)
d["passengers"] = pd.to_numeric(d["passengers"], errors="raise").astype("int64")

# ---- completeness checks: no duplicate days, no gaps, nothing implausible ----
assert d.date.is_unique, "duplicate dates"
full = pd.date_range(d.date.min(), d.date.max(), freq="D")
missing = full.difference(d.date)
assert len(missing) == 0, f"missing days: {list(missing.date)[:10]}"
assert (d.passengers > 0).all(), "non-positive count"
print(f"{len(d):,} consecutive days, {d.date.min().date()} to {d.date.max().date()}; "
      f"min {d.passengers.min():,}, max {d.passengers.max():,}")

d.to_csv(tsa.DATA / "tsa_daily_passengers.csv", index=False)
json.dump({"fetched": datetime.date.today().isoformat(), "first_day": str(d.date.min().date()), "last_day": str(d.date.max().date()),
           "source": URL}, open(tsa.DATA / "throughput_meta.json", "w"), indent=1)
