"""Cross-check the national daily passenger counts against TSA's OTHER publication of the same thing: the weekly hourly
throughput files in TSA's FOIA reading room (one row per airport, checkpoint and hour).

For a fixed set of weeks it downloads the weekly PDF, sums every count in it, and compares that to the sum of the daily national
table for the same seven days. Needs the `pdftotext` command (poppler). The PDFs are not kept in the repo.

Writes data/throughput_crosscheck.csv (week, file_total, daily_table_total, file_over_table).
The files and the daily table are both TSA's, so a gap means they cover slightly different things, not that one is "right".
"""
import re, subprocess, tempfile
from pathlib import Path
import pandas as pd
import tsa

BASE = "https://www.tsa.gov/sites/default/files/foia-readingroom/"
WEEKS = [   # (file name, first day, last day): spans 2024-2026, a March week during the 2026 DHS funding lapse, and a summer week
    ("tsa-total-throughput-data-march-3-2024-to-march-9-2024.pdf", "2024-03-03", "2024-03-09"),
    ("tsa-total-throughput-data-march-2-2025-to-march-8-2025.pdf", "2025-03-02", "2025-03-08"),
    ("tsa-throughput-data-to-march-1-2026-to-march-7-2026.pdf", "2026-03-01", "2026-03-07"),
    ("tsa-throughput-data-to-july-12-2026-to-july-18-2026_0.pdf", "2026-07-12", "2026-07-18"),
]
COUNT = re.compile(r"\d{1,3}(?:,\d{3})+|\d+")

daily = pd.read_csv(tsa.DATA / "tsa_daily_passengers.csv", parse_dates=["date"]).set_index("date").passengers
rows = []
with tempfile.TemporaryDirectory() as tmp:
    for fn, a, b in WEEKS:
        pdf = Path(tmp) / fn; txt = Path(tmp) / (fn + ".txt")
        subprocess.run(["curl", "-sL", "-A", "Mozilla/5.0", "-o", str(pdf), BASE + fn], check=True)
        subprocess.run(["pdftotext", "-raw", str(pdf), str(txt)], check=True)      # raw mode: counts come out one per line
        lines = [l.strip() for l in txt.read_text().split("\n")]
        header = lines[1]                      # the report date; repeated at the top of every page, followed by the page number
        total, skip = 0, False
        for l in lines:
            if l == header:
                skip = True; continue
            if COUNT.fullmatch(l):
                if skip: skip = False; continue          # that integer is the page number
                total += int(l.replace(",", ""))
        table = int(daily.loc[a:b].sum())
        rows.append(dict(week=f"{a} to {b}", file_total=total, daily_table_total=table, file_over_table=total / table))
        print(rows[-1])
pd.DataFrame(rows).to_csv(tsa.DATA / "throughput_crosscheck.csv", index=False)
