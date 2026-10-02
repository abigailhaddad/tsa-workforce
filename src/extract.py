"""Pull TSA (HSBC) accessions, separations, and employment from the impactproject/opm-ehri-data
HuggingFace dataset, 2018-01 onward, into data/.

Each OPM monthly "dynamics" file is incremental: mostly actions whose effective month equals the file
month, plus a tail of late-reported earlier actions. So the event-month series is built by summing
`count` across ALL files grouped by `personnel_action_effective_date_yyyymm`. We keep `file_ym` (the
month of the file a row came from) so the notebook can measure how late rows arrive.
Employment files are point-in-time snapshots: one snapshot per file, never summed across files.
"""
import time
import tsa

MIN = "201801"


def run_retry(con, sql, tries=10):
    for i in range(tries):
        try:
            return con.execute(sql)
        except Exception as e:                       # HF 429s / transient 5xx
            if i == tries - 1:
                raise
            print("  retry:", str(e)[:80], flush=True); time.sleep(20 * (i + 1))


def run():
    con = tsa.con()
    D = tsa.DATA
    FILE = r"regexp_extract(filename, '_(\d{6})_v', 1)"

    us = tsa.url_list(tsa.urls("accessions", MIN))
    print(f"accessions: {len(tsa.urls('accessions', MIN))} files", flush=True)
    run_retry(con, f"""COPY (
      SELECT personnel_action_effective_date_yyyymm AS event_ym, {FILE} AS file_ym,
             accession_category, appointment_type, pay_plan_code, grade, supervisory_status,
             occupational_series_code, length_of_service_years, work_schedule,
             duty_station_state_abbreviation AS duty_state, count::INT AS count
      FROM read_parquet({us}, union_by_name=true, filename=true)
      WHERE agency_subelement_code = '{tsa.TSA}') TO '{D/'acc_tsa.parquet'}' (FORMAT parquet)""")

    us = tsa.url_list(tsa.urls("separations", MIN))
    print(f"separations: {len(tsa.urls('separations', MIN))} files", flush=True)
    run_retry(con, f"""COPY (
      SELECT personnel_action_effective_date_yyyymm AS event_ym, {FILE} AS file_ym,
             separation_category, drp_indicator, appointment_type, pay_plan_code, grade, supervisory_status,
             occupational_series_code, length_of_service_years, work_schedule,
             duty_station_state_abbreviation AS duty_state, count::INT AS count
      FROM read_parquet({us}, union_by_name=true, filename=true)
      WHERE agency_subelement_code = '{tsa.TSA}') TO '{D/'sep_tsa.parquet'}' (FORMAT parquet)""")

    # Employment: one file per month, one snapshot per file. 100+ files x ~50 MB, but DuckDB only
    # fetches the columns named here.
    ems = tsa.urls("employment", MIN)
    print(f"employment: {len(ems)} files (one at a time to stay under the HF rate limit)", flush=True)
    con.execute("CREATE TABLE te(snapshot_ym VARCHAR, pay_plan_code VARCHAR, grade VARCHAR, occupational_series_code VARCHAR, "
                "length_of_service_years VARCHAR, work_schedule VARCHAR, appointment_type VARCHAR, supervisory_status VARCHAR, count BIGINT)")
    for u in ems:
        run_retry(con, f"""INSERT INTO te SELECT snapshot_yyyymm, pay_plan_code, grade, occupational_series_code,
              length_of_service_years, work_schedule, appointment_type, supervisory_status, SUM(count::INT)
              FROM read_parquet('{u}') WHERE agency_subelement_code='{tsa.TSA}' GROUP BY ALL""")
    con.execute(f"COPY te TO '{D/'emp_tsa.parquet'}' (FORMAT parquet)")

    for f in ("acc_tsa", "sep_tsa", "emp_tsa"):
        n, s = con.execute(f"SELECT COUNT(*), SUM(count) FROM '{D/(f+'.parquet')}'").fetchone()
        print(f"  {f}: {n:,} rows, count sum {s:,}")


if __name__ == "__main__":
    run()
