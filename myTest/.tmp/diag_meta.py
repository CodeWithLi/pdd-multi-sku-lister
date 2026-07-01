import json
import pymysql

conn = pymysql.connect(
    host="192.168.23.128",
    port=3306,
    user="root",
    password="xiaoli",
    database="pdd_agent_platform",
    charset="utf8mb4",
)
cur = conn.cursor()
cur.execute(
    "SELECT pipeline_id, status, meta FROM integrated_pipelines "
    "ORDER BY CHAR_LENGTH(meta) DESC LIMIT 1"
)
pid, status, meta_raw = cur.fetchone()
meta = json.loads(meta_raw) if isinstance(meta_raw, str) else meta_raw
print("pipeline:", pid, "status:", status)
print("meta top-level keys:", list(meta.keys()))
for k, v in meta.items():
    if isinstance(v, (dict, list)):
        s = json.dumps(v, ensure_ascii=False)
        print(f"  {k}: type={type(v).__name__} size={len(s)}B")
        if k == "batch_progress" and isinstance(v, dict):
            print(f"    batch_progress units: {len(v)}")
            sample_key = next(iter(v))
            print(f"    sample unit [{sample_key}]: {json.dumps(v[sample_key], ensure_ascii=False)[:400]}")
    else:
        print(f"  {k}: {repr(v)[:100]}")
conn.close()
