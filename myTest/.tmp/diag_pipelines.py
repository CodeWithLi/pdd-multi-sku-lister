"""One-off diagnostic for integrated_pipelines sort memory issue."""
import pymysql

DB = dict(host="192.168.23.128", port=3306, user="root", password="xiaoli", database="pdd_agent_platform", charset="utf8mb4")

conn = pymysql.connect(**DB)
cur = conn.cursor()

print("=== integrated_pipelines 基本统计 ===")
cur.execute("SELECT COUNT(*) FROM integrated_pipelines")
print("总行数:", cur.fetchone()[0])

cur.execute("SELECT status, COUNT(*) cnt FROM integrated_pipelines GROUP BY status ORDER BY cnt DESC")
print("\n按 status 分布:")
for row in cur.fetchall():
    print(f"  {row[0]}: {row[1]}")

cur.execute(
    """
SELECT table_rows, data_length, index_length, avg_row_length,
       ROUND(data_length/1024/1024,2) data_mb,
       ROUND(index_length/1024/1024,2) index_mb
FROM information_schema.tables
WHERE table_schema=%s AND table_name='integrated_pipelines'
""",
    (DB["database"],),
)
r = cur.fetchone()
print(f"\n表统计(information_schema): rows~{r[0]}, data={r[4]}MB, index={r[5]}MB, avg_row={r[3]}B")

print("\n=== 行宽(JSON/meta) 统计 ===")
cur.execute(
    """
SELECT
  COUNT(*) total,
  ROUND(AVG(LENGTH(meta)),0) avg_meta,
  MAX(LENGTH(meta)) max_meta,
  ROUND(AVG(LENGTH(product_codes)),0) avg_pc,
  MAX(LENGTH(product_codes)) max_pc,
  ROUND(AVG(LENGTH(error)),0) avg_err,
  MAX(LENGTH(error)) max_err,
  ROUND(AVG(
    LENGTH(COALESCE(pipeline_id,'')) + LENGTH(COALESCE(account_id,'')) +
    LENGTH(COALESCE(status,'')) + LENGTH(COALESCE(current_step,'')) +
    LENGTH(COALESCE(product_codes,'')) + LENGTH(COALESCE(error,'')) +
    LENGTH(COALESCE(meta,'')) + LENGTH(COALESCE(pdd_product_ids,'')) +
    LENGTH(COALESCE(mapping_ids,''))
  ),0) avg_row_bytes,
  MAX(
    LENGTH(COALESCE(pipeline_id,'')) + LENGTH(COALESCE(account_id,'')) +
    LENGTH(COALESCE(status,'')) + LENGTH(COALESCE(current_step,'')) +
    LENGTH(COALESCE(product_codes,'')) + LENGTH(COALESCE(error,'')) +
    LENGTH(COALESCE(meta,'')) + LENGTH(COALESCE(pdd_product_ids,'')) +
    LENGTH(COALESCE(mapping_ids,''))
  ) max_row_bytes
FROM integrated_pipelines
"""
)
r = cur.fetchone()
labels = [
    "total",
    "avg_meta",
    "max_meta",
    "avg_pc",
    "max_pc",
    "avg_err",
    "max_err",
    "avg_row_bytes",
    "max_row_bytes",
]
for label, val in zip(labels, r):
    print(f"  {label}: {val}")

print("\n=== meta 最大的 5 条 ===")
cur.execute(
    """
SELECT pipeline_id, status, LENGTH(meta) meta_len, created_at
FROM integrated_pipelines ORDER BY LENGTH(meta) DESC LIMIT 5
"""
)
for row in cur.fetchall():
    print(f"  {row[0]} status={row[1]} meta={row[2]}B created={row[3]}")

print("\n=== 索引 ===")
cur.execute("SHOW INDEX FROM integrated_pipelines")
indexes: dict[str, list[str]] = {}
for row in cur.fetchall():
    indexes.setdefault(row[2], []).append(row[4])
for key, cols in indexes.items():
    print(f"  {key}: {cols}")

print("\n=== MySQL sort 相关变量 ===")
for var in [
    "sort_buffer_size",
    "max_sort_length",
    "read_rnd_buffer_size",
    "tmp_table_size",
    "max_heap_table_size",
]:
    cur.execute("SHOW VARIABLES LIKE %s", (var,))
    row = cur.fetchone()
    if row:
        val = int(row[1])
        if val >= 1024 * 1024:
            print(f"  {row[0]} = {val} ({val / 1024 / 1024:.2f} MB)")
        else:
            print(f"  {row[0]} = {val} ({val / 1024:.1f} KB)")

print("\n=== EXPLAIN 列表查询 ===")
cur.execute("EXPLAIN SELECT * FROM integrated_pipelines ORDER BY created_at DESC LIMIT 10")
cols = [d[0] for d in cur.description]
print(" ", cols)
for row in cur.fetchall():
    print(" ", row)

# rough sort memory estimate
cur.execute("SELECT COUNT(*) FROM integrated_pipelines")
n = cur.fetchone()[0]
cur.execute(
    """
SELECT AVG(
    LENGTH(COALESCE(pipeline_id,'')) + LENGTH(COALESCE(account_id,'')) +
    LENGTH(COALESCE(status,'')) + LENGTH(COALESCE(current_step,'')) +
    LENGTH(COALESCE(product_codes,'')) + LENGTH(COALESCE(error,'')) +
    LENGTH(COALESCE(meta,'')) + LENGTH(COALESCE(pdd_product_ids,'')) +
    LENGTH(COALESCE(mapping_ids,''))
) FROM integrated_pipelines
"""
)
avg_bytes = float(cur.fetchone()[0] or 0)
est_mb = n * avg_bytes / 1024 / 1024
print(f"\n=== 粗估全表排序内存 ===")
print(f"  {n} 行 × ~{avg_bytes:.0f} B/行 ≈ {est_mb:.1f} MB (仅数据，不含排序开销)")

conn.close()
