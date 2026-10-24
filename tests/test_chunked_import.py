"""Chunked raw import: schema validation, quarantine, and batch-size profiling."""

import shutil
import subprocess
from pathlib import Path

import pandas as pd
import pytest
from sqlalchemy import create_engine, text

from src.load import chunked_import as ci

ROOT = Path(__file__).resolve().parents[1]
DDL = (ROOT / "sql/staging.postgres.sql").read_text()


@pytest.fixture
def engine(tmp_path):
    eng = create_engine(f"sqlite:///{tmp_path / 'wh.db'}")
    with eng.begin() as conn:
        for stmt in filter(str.strip, DDL.split(";")):
            conn.execute(text(stmt))
    return eng


@pytest.fixture
def raw_dir(tmp_path):
    raw = tmp_path / "raw"
    shutil.copytree(ROOT / "data/raw", raw)
    # Append malformed rows, one per failure mode, after the clean data.
    with open(raw / "order_items.csv", "a") as fh:
        fh.write("ITEM0000001,ORD000001,PROD00002,2,40,0.05\n"   # duplicate key from batch 1
                 "ITEMBAD0001,ORD000001,PROD00002,abc,40,0.05\n"  # non-numeric quantity
                 "ITEMBAD0002,ORD000001,PROD00002,0,40,0.05\n"    # quantity below 1
                 "ITEMBAD0003,ORD000001,PROD00002,1,40,1.5\n"     # discount above 1
                 "ITEMBAD0004,,PROD00002,1,40,0.1\n")             # missing FK
    with open(raw / "orders.csv", "a") as fh:
        fh.write("ORDBAD01,CUST00001,2025-13-45,Shipped,1,1,1,PayPal,Express\n"
                 "ORDBAD02,CUST00001,2025-07-01,Teleported,1,1,1,PayPal,Express\n")
    return raw


def test_malformed_rows_are_quarantined_and_never_loaded(engine, raw_dir, tmp_path):
    quarantine = tmp_path / "q"
    stats = ci.run_import(engine, str(raw_dir), str(quarantine), batch_size=250)
    items = stats["order_items"]
    assert items.rows_read == 2169 + 5
    assert items.rows_quarantined == 5 and items.rows_loaded == 2169
    assert items.batches == 9
    assert items.reasons == {
        "item_id: duplicate key": 1, "quantity: not a valid int": 1,
        "quantity: below 1": 1, "discount_rate: above 1": 1, "order_id: missing": 1,
    }
    assert stats["orders"].reasons == {"order_date: not a valid date": 1,
                                       "order_status: not an allowed value": 1}
    q = pd.read_csv(quarantine / "order_items_quarantine.csv", dtype=str)
    assert set(q["item_id"].fillna("")) == {"ITEM0000001", "ITEMBAD0001", "ITEMBAD0002",
                                             "ITEMBAD0003", "ITEMBAD0004"}
    with engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM staging_order_items")).scalar() == 2169
        assert conn.execute(text(
            "SELECT count(*) FROM staging_order_items WHERE item_id LIKE 'ITEMBAD%'")).scalar() == 0
        assert conn.execute(text("SELECT count(*) FROM staging_orders")).scalar() == 1089


def test_header_mismatch_raises():
    with pytest.raises(ci.SchemaError, match="missing column"):
        ci.validate_chunk(pd.DataFrame({"customer_id": ["C1"]}), "customers", set())


def test_profile_is_rerun_safe_and_identical_across_batch_sizes(engine, raw_dir, tmp_path):
    results = ci.profile_batch_sizes(engine, str(raw_dir), str(tmp_path / "q"), [50, 500, 5000])
    assert [r["batch_size"] for r in results] == [50, 500, 5000]
    assert [r["sources"]["order_items"]["batches"] for r in results] == [44, 5, 1]
    counts = [{k: (v["rows_loaded"], v["rows_quarantined"]) for k, v in r["sources"].items()}
              for r in results]
    assert counts[0] == counts[1] == counts[2]
    for r in results:
        assert r["peak_memory_mib"] > 0
        assert set(r["stage_seconds"]) == {"read", "validate", "load"}


@pytest.mark.skipif(shutil.which("docker") is None, reason="docker not available")
def test_validated_batches_satisfy_postgres_constraints(raw_dir):
    """COPY validated rows into a network-isolated PostgreSQL with the staging DDL."""
    script = ["BEGIN;", DDL]
    for source in ci.IMPORT_ORDER:
        seen, frames = set(), []
        for chunk in pd.read_csv(raw_dir / f"{source}.csv", dtype=str,
                                 keep_default_na=False, chunksize=300):
            frames.append(ci.validate_chunk(chunk, source, seen)[0])
        frame = pd.concat(frames)
        script += [f"COPY staging_{source} ({', '.join(frame.columns)}) FROM STDIN "
                   "WITH (FORMAT CSV, HEADER TRUE);", frame.to_csv(index=False).rstrip(), "\\."]
    script.append("SELECT (SELECT count(*) FROM staging_orders) || ',' || "
                  "(SELECT count(*) FROM staging_order_items);")
    run = subprocess.run([
        "docker", "run", "--rm", "-i", "--pull=never", "--network=none",
        "--user=postgres", "--tmpfs", "/tmp", "--entrypoint", "sh", "postgres:16-alpine", "-c",
        ("set -eu\n"
         "initdb -D /tmp/pgdata -A trust --no-locale >/dev/null\n"
         "pg_ctl -D /tmp/pgdata -o \"-c listen_addresses='' -c unix_socket_directories=/tmp\" "
         "-l /tmp/postgres.log start >/dev/null\n"
         "exec psql -h /tmp -U postgres -d postgres -qAt -v ON_ERROR_STOP=1"),
    ], input="\n".join(script) + "\n", text=True, capture_output=True, timeout=25, check=False)
    assert run.returncode == 0, run.stderr
    assert run.stdout.strip() == "1089,2169"
