"""Shared constants and helpers for the TSA workforce analysis.

The notebook and the verification script both import from here so every number comes from one definition of "TSA", "frontline officer", and one set of windows.
"""
from pathlib import Path
import json
import duckdb

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
HF = "https://huggingface.co/datasets/impactproject/opm-ehri-data/resolve/main"

ACC = str(DATA / "acc_tsa.parquet")
SEP = str(DATA / "sep_tsa.parquet")
EMP = str(DATA / "emp_tsa.parquet")
PAX = str(DATA / "tsa_daily_passengers.csv")   # national daily checkpoint passengers (fetch_throughput.py)

TSA = "HSBC"        # agency_subelement_code for Transportation Security Administration
REPO_URL = "github.com/abigailhaddad/tsa-workforce"   # where this repo will live; printed on the charts
# Transportation Security Officers are pay plan SV, series 1802 (Compliance Inspection and Support).
ALL_1802 = "pay_plan_code = 'SV' AND occupational_series_code = '1802'"
# FRONTLINE = rank-and-file screening officers: series 1802 with supervisory_status 'ALL OTHER POSITIONS'. Lead officers
# (supervisory_status 'LEADER'; labelled 'TEAM LEADER' before 2021) and supervisors/managers are excluded: leads lead other
# officers, and no source says whether leads are covered by the standing policy. Document checkers are NOT separately identifiable -- they
# sit in the same series and the same SV pay bands as the other screeners (July 2026: band F holds most of them).
FRONTLINE = ALL_1802 + " AND supervisory_status = 'ALL OTHER POSITIONS'"
OFFICER = FRONTLINE            # name used throughout the notebook for "frontline screening officers"
NEW_HIRE = "accession_category LIKE 'NEW HIRE%'"


_meta = json.load(open(DATA / "file_map_meta.json"))   # written by build_file_map.py
LATEST_MONTH = _meta["latest_month"]    # newest month OPM has published in all three datasets
ASOF = _meta["as_of"]                   # the day the file list was built from OPM's API


def file_map():
    return json.load(open(DATA / "hf_file_map.json"))


def urls(kind, min_ym="200501", max_ym="999999"):
    m = file_map()[kind]
    return [f"{HF}/{m[ym]}" for ym in sorted(m) if min_ym <= ym <= max_ym]


def url_list(us):
    return "[" + ",".join(f"'{u}'" for u in us) + "]"


def con():
    c = duckdb.connect()
    c.execute("SET enable_progress_bar=false;")
    # Low thread count -> low HTTP concurrency. Parallel scans of many remote files trip HF's rate limiter.
    c.execute("SET threads=3;")
    return c


def dbl(col):
    return f"TRY_CAST({col} AS DOUBLE)"
