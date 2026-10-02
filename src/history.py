"""Long-run TSA context (2005-2017) and an agency-code stability audit.

Writes data/tsa_hires_history.csv      (new hires and separations per year, 2005-2017, from raw yearly files)
       data/agency_code_audit.csv      (every subelement whose name mentions transportation/security, in
                                        sampled months 2005-2026, with its code and headcount -- shows
                                        HSBC is the only TSA code and that it never changes)
       data/occ_series_names.csv       (series code -> name for the codes the notebook prints, from OPM's own files)
"""
import time
import pandas as pd
import tsa

con = tsa.con()


def read_retry(sql, tries=6):
    for i in range(tries):
        try:
            return con.execute(sql).df()
        except Exception as e:
            if i == tries - 1:
                raise
            print("  retry:", str(e)[:70], flush=True); time.sleep(8 * (i + 1))


rows = []
FRONT_SQL = tsa.FRONTLINE
for yr in range(2005, 2018):
    y = str(yr)
    for label, kind, extra in (("accessions", "accessions", f"AND {tsa.NEW_HIRE}"),
                               ("accessions_frontline", "accessions", f"AND {tsa.NEW_HIRE} AND {FRONT_SQL}"),
                               ("separations", "separations", ""),
                               ("separations_frontline", "separations", f"AND {FRONT_SQL}")):
        us = tsa.url_list(tsa.urls(kind, f"{y}01", f"{y}12"))
        d = read_retry(f"""
          SELECT '{y}' AS year, '{label}' AS kind, SUM(count::INT) AS n
          FROM read_parquet({us}, union_by_name=true)
          WHERE agency_subelement_code = '{tsa.TSA}' {extra}
            AND substr(personnel_action_effective_date_yyyymm,1,4) = '{y}'""")
        rows.append(d); print(y, label, int(d.n.iloc[0] or 0), flush=True)
pd.concat(rows).to_csv(tsa.DATA / "tsa_hires_history.csv", index=False)

# ---- code-stability audit: employment snapshots in June (or the nearest month) of sampled years ----
em = tsa.file_map()["employment"]
audit = []
for yr in (2005, 2008, 2010, 2012, 2014, 2016, 2018, 2020, 2022, 2024, 2025, 2026):
    ym = next((f"{yr}{m:02d}" for m in (6, 7, 5, 8, 4, 9, 3, 10, 12, 1) if f"{yr}{m:02d}" in em), None)
    if ym is None:
        print("no employment file near", yr); continue
    d = read_retry(f"""
      SELECT '{ym}' AS snapshot_ym, agency_subelement_code AS code, agency_subelement AS name,
             SUM(count::INT) AS headcount
      FROM read_parquet('{tsa.HF}/{em[ym]}')
      WHERE agency_subelement ILIKE '%TRANSPORTATION%' OR agency_subelement ILIKE '%SECURITY ADMIN%'
         OR agency_subelement ILIKE '%TSA%' OR agency_subelement_code = '{tsa.TSA}'
      GROUP BY ALL""")
    audit.append(d); print("audit", ym, len(d), "rows", flush=True)
pd.concat(audit).sort_values(["snapshot_ym", "code"]).to_csv(tsa.DATA / "agency_code_audit.csv", index=False)

# ---- occupational-series names, straight from OPM's files (latest employment snapshot) ----
d = read_retry(f"""
  SELECT DISTINCT occupational_series_code AS code, occupational_series AS name
  FROM read_parquet('{tsa.HF}/{em[tsa.LATEST_MONTH]}') WHERE agency_subelement_code = '{tsa.TSA}'
  ORDER BY 1""")
d.to_csv(tsa.DATA / "occ_series_names.csv", index=False)
print("saved history, audit, series names")
