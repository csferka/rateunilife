import os
import sqlite3
from contextlib import closing

import pymysql

TABLES_IN_ORDER = [
    "users",
    "posts",
    "comments",
    "votes",
    "tags",
    "reports",
    "post_tags",
]


def get_sqlite_rows(sqlite_path: str, table: str):
    with closing(sqlite3.connect(sqlite_path)) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(f"SELECT * FROM {table}")
        rows = cur.fetchall()
        return [dict(r) for r in rows]


def migrate_table(mysql_conn, rows, table):
    if not rows:
        return 0

    columns = list(rows[0].keys())
    placeholders = ", ".join(["%s"] * len(columns))
    col_list = ", ".join([f"`{c}`" for c in columns])
    sql = f"INSERT INTO `{table}` ({col_list}) VALUES ({placeholders})"

    with mysql_conn.cursor() as cur:
        for row in rows:
            values = [row[c] for c in columns]
            cur.execute(sql, values)
    return len(rows)


def main():
    sqlite_path = os.getenv("SQLITE_PATH", "app.db")
    mysql_host = os.getenv("MYSQL_HOST", "localhost")
    mysql_user = os.getenv("MYSQL_USER", "root")
    mysql_password = os.getenv("MYSQL_PASSWORD", "")
    mysql_db = os.getenv("MYSQL_DB", "rate_my_uni_life")
    mysql_port = int(os.getenv("MYSQL_PORT", "3306"))

    if not os.path.exists(sqlite_path):
        raise FileNotFoundError(f"SQLite DB not found: {sqlite_path}")

    mysql_conn = pymysql.connect(
        host=mysql_host,
        user=mysql_user,
        password=mysql_password,
        database=mysql_db,
        port=mysql_port,
        charset="utf8mb4",
        autocommit=False,
    )

    migrated_counts = {}

    try:
        with mysql_conn.cursor() as cur:
            cur.execute("SET FOREIGN_KEY_CHECKS = 0")
            for table in reversed(TABLES_IN_ORDER):
                cur.execute(f"TRUNCATE TABLE `{table}`")
            cur.execute("SET FOREIGN_KEY_CHECKS = 1")

        for table in TABLES_IN_ORDER:
            rows = get_sqlite_rows(sqlite_path, table)
            migrated_counts[table] = migrate_table(mysql_conn, rows, table)

        mysql_conn.commit()

        print("Migration completed successfully.")
        for table in TABLES_IN_ORDER:
            print(f"{table}: {migrated_counts.get(table, 0)} rows")

    except Exception:
        mysql_conn.rollback()
        raise
    finally:
        mysql_conn.close()


if __name__ == "__main__":
    main()
