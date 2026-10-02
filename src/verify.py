"""Independent second check of the extract, against the ORIGINAL source.

For a sample of files (fixed edge cases + random picks) it:
  1. downloads the file straight from OPM's API (the source of record) and from the HuggingFace mirror;
  2. compares them as an ORDER-INDEPENDENT multiset of rows over the columns the analysis uses (plus agency and count).
     (Comparing all ~64 columns of 2-million-row headcount files took ~3 minutes each and added nothing: the extract is
     built from the columns below. Some mirrored files list
     the same rows in a different order, so a positional or byte comparison is meaningless.) Two flavours:
       exact       -- cell-for-cell identical
       normalized  -- identical once "null-like" cells are unified: whitespace is stripped, then a NULL, an
                      empty string, and the literal text 'NA' all count as the same. We count how many cells
                      that touches in TSA rows;
  3. recounts TSA (HSBC) rows from OPM's file with pyarrow/pandas -- a different reader from the
     DuckDB-over-HTTP path that built the extract -- and compares the *columns the analysis uses*, as a
     multiset of rows, to data/*_tsa.parquet. Employment is compared as group totals.
Writes data/proof_sample.csv -- one row per file, OPM's value next to ours. Exit 1 on any mismatch.
"""
import random, sys
import pandas as pd, pyarrow as pa, pyarrow.compute as pc, pyarrow.parquet as pq, requests
import tsa

CACHE = tsa.DATA / "raw_cache"; CACHE.mkdir(exist_ok=True)
API = "https://data.opm.gov/api/v1/files"
fm = tsa.file_map()
NULL_LIKE = ["", "NA"]          # normalized = whitespace stripped, then these count as NULL
SENT = "\x00NULL"

# Edge cases on purpose: first/last month of the series, the hiring-pause months, the late-landing
# Oct-2025 separations month, and June 2026 (which OPM re-published as a later version).
FIXED = [("employment", "201801"), ("employment", "202502"), ("employment", "202510"), ("employment", "202606"),
         ("employment", "202607"), ("accessions", "201801"), ("accessions", "202512"), ("accessions", "202606"),
         ("accessions", "202607"), ("separations", "201801"), ("separations", "202510"), ("separations", "202509"),
         ("separations", "202606"), ("separations", "202607")]
random.seed(20261001)
pool = [(k, ym) for k in fm for ym in fm[k] if ym >= "201801" and (k, ym) not in FIXED]
SAMPLE = FIXED + random.sample(pool, 12)

# columns the analysis reads, as named in OPM's files
USED = ["personnel_action_effective_date_yyyymm", "accession_category", "separation_category", "drp_indicator",
        "appointment_type", "pay_plan_code", "grade", "supervisory_status", "occupational_series_code", "length_of_service_years", "work_schedule"]


def get(url, dest):
    if not dest.exists():
        r = requests.get(url, timeout=600); r.raise_for_status(); dest.write_bytes(r.content)
    return dest


def fold_series(s, null_like=True):
    """One null convention for every comparison: strings, and (if null_like) whitespace stripped and '' / 'NA' /
    missing all mapped to one sentinel. Vectorized; a missing value can never turn into the text 'nan'."""
    s = s.astype("string")
    if null_like:
        s = s.str.strip()
        s = s.where(~s.isin(NULL_LIKE))
    return s.fillna(SENT).astype(object)


def fold(df, cols, null_like=True):
    df = df.copy()
    for c in cols:
        df[c] = fold_series(df[c], null_like)
    return df


def as_str(t, null_like):
    df = t.to_pandas()
    return fold(df, list(df.columns), null_like)


def multiset_equal(a, b):
    if len(a) != len(b) or sorted(a.columns) != sorted(b.columns):
        return False
    cols = sorted(a.columns)
    ha = pd.util.hash_pandas_object(a[cols], index=False).sort_values().to_numpy()
    hb = pd.util.hash_pandas_object(b[cols], index=False).sort_values().to_numpy()
    return bool((ha == hb).all())


def null_like_cells(t, mask=None):
    n = 0
    for c in t.column_names:
        col = t[c].cast(pa.string())
        hit = pc.or_(pc.is_null(col), pc.is_in(pc.utf8_trim_whitespace(col), value_set=pa.array(NULL_LIKE)))
        if mask is not None:
            hit = pc.and_(hit, mask)
        n += pc.sum(hit.cast(pa.int64())).as_py() or 0
    return n


def same_totals(x, y):
    """x and y are Series of counts indexed by the same keys; equal if every key matches exactly."""
    d = x.astype("int64").sub(y.astype("int64"), fill_value=0)
    return bool((d == 0).all())


ext = {"accessions": pd.read_parquet(tsa.ACC), "separations": pd.read_parquet(tsa.SEP)}
emp = pd.read_parquet(tsa.EMP)
out = []
for kind, ym in SAMPLE:
    path = fm[kind][ym]; ver = int(path.split("_v")[1].split(".")[0])
    opm_p = get(f"{API}/{kind}/{ym[:4]}/{ym[4:]}/{ver}/download", CACHE / f"opm_{kind}_{ym}_v{ver}.parquet")
    hf_p = get(f"{tsa.HF}/{path}", CACHE / f"hf_{kind}_{ym}_v{ver}.parquet")
    a, b = pq.read_table(opm_p), pq.read_table(hf_p)
    cmp_cols = [c for c in USED + ["snapshot_yyyymm", "agency_subelement_code", "count"] if c in a.column_names]
    exact = multiset_equal(as_str(a.select(cmp_cols), False), as_str(b.select(cmp_cols), False))
    norm = multiset_equal(as_str(a.select(cmp_cols), True), as_str(b.select(cmp_cols), True))
    is_tsa = pc.equal(a["agency_subelement_code"], tsa.TSA)
    nl_tsa = null_like_cells(a, is_tsa)

    # TSA rows from OPM's original vs our extract, on the columns the analysis uses
    ta = a.filter(is_tsa).to_pandas()
    ta["count"] = ta["count"].astype("int64")
    if kind == "employment":
        k_cols = ["snapshot_yyyymm", "pay_plan_code", "grade", "supervisory_status", "occupational_series_code",
                  "length_of_service_years", "work_schedule", "appointment_type"]
        ours = emp[emp.snapshot_ym == ym].rename(columns={"snapshot_ym": "snapshot_yyyymm"})
    else:
        ours = ext[kind][ext[kind].file_ym == ym].rename(columns={"event_ym": "personnel_action_effective_date_yyyymm"})
        k_cols = [c for c in USED if c in ta.columns and c in ours.columns]
    src = fold(ta[k_cols + ["count"]], k_cols).groupby(k_cols)["count"].sum()
    mine = fold(ours[k_cols + ["count"]], k_cols).groupby(k_cols)["count"].sum()
    same_cols = same_totals(src, mine)
    src_n, our_n = int(src.sum()), int(mine.sum())
    out.append(dict(dataset=kind, month=ym, version=ver, opm_api_url=f"{API}/{kind}/{ym[:4]}/{ym[4:]}/{ver}/download",
                    rows_in_file=a.num_rows, opm_equals_mirror_exact=exact, opm_equals_mirror_normalized=norm,
                    null_like_cells_in_tsa_rows=nl_tsa, tsa_count_opm=src_n, tsa_count_ours=our_n,
                    tsa_columns_used_identical=bool(same_cols), match=bool(same_cols and src_n == our_n)))
    r = out[-1]
    print(f"{kind:12s} {ym} v{ver}  TSA opm={src_n:>6,} ours={our_n:>6,} used-cols identical={r['tsa_columns_used_identical']}  "
          f"mirror==opm exact={exact} normalized={norm}", flush=True)

df = pd.DataFrame(out); df.to_csv(tsa.DATA / "proof_sample.csv", index=False)
bad = df[~(df.match & df.opm_equals_mirror_normalized)]
print(f"\n{len(df)} files; extract matches OPM's original (TSA rows, columns used): {int(df.match.sum())}; "
      f"mirror == OPM exactly: {int(df.opm_equals_mirror_exact.sum())}; mirror == OPM after null-like folding: "
      f"{int(df.opm_equals_mirror_normalized.sum())}; files with a problem: {len(bad)}")
sys.exit(1 if len(bad) else 0)
