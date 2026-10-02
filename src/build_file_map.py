"""Build data/hf_file_map.json from OPM's own API (the authority on which version of each month is
CURRENT), then confirm every file in it actually exists in the HuggingFace mirror.

Why not list HuggingFace directly: its tree API caps at 1,000 entries per page and silently truncates
big folders, and it holds superseded versions too. The OPM API says which version is current; HF is
just where we read the bytes from.

Also records WHEN this ran and which month is newest (everything downstream reads these, nothing is typed in),
and saves OPM's release-notes page as plain text so the notebook can search it.

Writes data/hf_file_map.json    ({dataset: {YYYYMM: "dataset/dataset_YYYYMM_vN.parquet"}})
       data/file_versions.csv    (dataset, ym, version, publish_date, hf_status) -- the audit trail
       data/file_map_meta.json   (as_of date, latest published month per dataset)
       data/release_notes.txt    (OPM release-notes page, tags stripped, fetched as_of)
"""
import json, time, csv, re, html, datetime
from concurrent.futures import ThreadPoolExecutor
import requests

API = "https://data.opm.gov/api/v1/files"
HF = "https://huggingface.co/datasets/impactproject/opm-ehri-data/resolve/main"
DATASETS = ("accessions", "separations", "employment")


def head(path, tries=5):
    for i in range(tries):
        r = requests.head(f"{HF}/{path}", allow_redirects=True, timeout=60)
        if r.status_code in (200, 404):
            return r.status_code
        time.sleep(3 * (i + 1))      # 429 / 5xx: back off and retry
    return r.status_code


rows, fmap = [], {}
for d in DATASETS:
    recs = requests.get(f"{API}/{d}", params={"current": "true"}, timeout=60).json()
    fmap[d] = {}
    for r in recs:
        ym = r["year"] + r["month"]
        assert ym not in fmap[d], f"two 'current' files for {d} {ym}"
        fmap[d][ym] = f"{d}/{d}_{ym}_v{int(r['version'])}.parquet"
        rows.append([d, ym, int(r["version"]), r["publishDate"]])

with ThreadPoolExecutor(4) as ex:
    status = list(ex.map(lambda r: head(fmap[r[0]][r[1]]), rows))
bad = [(r[0], r[1]) for r, s in zip(rows, status) if s != 200]

json.dump({d: dict(sorted(v.items())) for d, v in fmap.items()}, open("data/hf_file_map.json", "w"), indent=1)
with open("data/file_versions.csv", "w", newline="") as f:
    w = csv.writer(f); w.writerow(["dataset", "ym", "version", "publish_date", "hf_http_status"])
    for r, s in zip(sorted(rows), [s for _, s in sorted(zip(rows, status))]):
        w.writerow(r + [s])
print({d: len(v) for d, v in fmap.items()}, "files; missing on HF:", bad or "none")

# ---- as-of date and newest published month ----
latest = {d: max(fmap[d]) for d in fmap}
meta = {"as_of": datetime.date.today().isoformat(), "latest_month_by_dataset": latest, "latest_month": min(latest.values())}
json.dump(meta, open("data/file_map_meta.json", "w"), indent=1)
print("as of", meta["as_of"], "| newest month in all three datasets:", meta["latest_month"], latest)

# ---- OPM release notes (a server-rendered page; no API) ----
page = requests.get("https://data.opm.gov/info-and-help/release-notes", timeout=60).text
page = re.sub(r"<script.*?</script>|<style.*?</style>", "", page, flags=re.S)
text = html.unescape(re.sub(r"<[^>]+>", "\n", page)); text = re.sub(r"\n\s*\n+", "\n", text)
open("data/release_notes.txt", "w").write(text)
print("saved release notes:", len(text), "characters")
