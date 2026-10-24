"""
Chunked raw-CSV import for the PostgreSQL warehouse staging tables.

Each raw source in data/raw/ is read in fixed-size batches with pandas. Every
batch is validated against an explicit column schema (type coercion, required
fields, ranges, allowed values, duplicate keys across batches). Rows that fail
are written to a quarantine CSV with the reason, and only valid rows are
appended to the staging table (see sql/staging.postgres.sql).

profile_batch_sizes() runs the import once per batch size and records the
runtime of each stage (read, validate, load) plus the peak Python heap
allocation measured with tracemalloc, so the cost of large imports can be
compared across batch sizes.

    python -m src.load.chunked_import --batch-sizes 100 500 2000
"""
import argparse
import json
import os
import time
import tracemalloc
from dataclasses import dataclass, field

import pandas as pd
from sqlalchemy import create_engine, text

from src.config import PATHS


@dataclass(frozen=True)
class Column:
    name: str
    kind: str  # 'str', 'int', 'float', 'date'
    required: bool = True
    min_value: float = None
    max_value: float = None
    allowed: tuple = None


SCHEMAS = {
    'customers': (
        [Column('customer_id', 'str'), Column('first_name', 'str'), Column('last_name', 'str'),
         Column('email', 'str'), Column('registration_date', 'date'),
         Column('country', 'str', required=False)],
        'customer_id',
    ),
    'products': (
        [Column('product_id', 'str'), Column('product_name', 'str'),
         Column('description', 'str', required=False), Column('category', 'str', required=False),
         Column('price', 'float', min_value=0), Column('cost', 'float', required=False, min_value=0),
         Column('brand', 'str', required=False)],
        'product_id',
    ),
    'orders': (
        [Column('order_id', 'str'), Column('customer_id', 'str'), Column('order_date', 'date'),
         Column('order_status', 'str',
                allowed=('Pending', 'Processing', 'Shipped', 'Completed', 'Delivered', 'Cancelled', 'Returned')),
         Column('order_total', 'float', required=False, min_value=0),
         Column('shipping_cost', 'float', required=False, min_value=0),
         Column('tax', 'float', required=False, min_value=0),
         Column('payment_method', 'str', required=False),
         Column('shipping_method', 'str', required=False)],
        'order_id',
    ),
    'order_items': (
        [Column('item_id', 'str'), Column('order_id', 'str'), Column('product_id', 'str'),
         Column('quantity', 'int', min_value=1), Column('price', 'float', min_value=0),
         Column('discount_rate', 'float', required=False, min_value=0, max_value=1)],
        'item_id',
    ),
}

# Parents first so the staging tables can be checked for orphans after load.
IMPORT_ORDER = ['customers', 'products', 'orders', 'order_items']


class SchemaError(Exception):
    """Raised when a source file's header does not match its schema."""


@dataclass
class ImportStats:
    source: str
    batches: int = 0
    rows_read: int = 0
    rows_loaded: int = 0
    rows_quarantined: int = 0
    reasons: dict = field(default_factory=dict)
    seconds: dict = field(default_factory=lambda: {'read': 0.0, 'validate': 0.0, 'load': 0.0})


def validate_chunk(chunk, source, seen_keys):
    """Split a raw batch into (typed valid rows, quarantined rows with a reason column).

    seen_keys carries primary keys from earlier batches so duplicates spanning
    batch boundaries are caught; it is updated with the keys of valid rows.
    """
    columns, key = SCHEMAS[source]
    missing = [c.name for c in columns if c.name not in chunk.columns]
    if missing:
        raise SchemaError(f"{source}: missing column(s) {missing}")

    typed = pd.DataFrame(index=chunk.index)
    reasons = pd.Series('', index=chunk.index, dtype=object)

    def flag(mask, message):
        mask = mask & (reasons == '')
        reasons[mask] = message

    for col in columns:
        raw = chunk[col.name]
        blank = raw.isna() | (raw.astype(str).str.strip() == '')
        if col.kind == 'str':
            value = raw.where(~blank).astype(object)
            value = value.where(blank, value.astype(str).str.strip())
            bad = pd.Series(False, index=chunk.index)
        elif col.kind == 'date':
            value = pd.to_datetime(raw.where(~blank), format='%Y-%m-%d', errors='coerce').dt.date
            bad = ~blank & value.isna()
        else:
            value = pd.to_numeric(raw.where(~blank), errors='coerce')
            bad = ~blank & value.isna()
            if col.kind == 'int':
                bad |= value.notna() & (value % 1 != 0)
        if col.required:
            flag(blank, f'{col.name}: missing')
        flag(bad, f'{col.name}: not a valid {col.kind}')
        if col.min_value is not None:
            flag(value.notna() & (value < col.min_value), f'{col.name}: below {col.min_value}')
        if col.max_value is not None:
            flag(value.notna() & (value > col.max_value), f'{col.name}: above {col.max_value}')
        if col.allowed is not None:
            flag(value.notna() & ~value.isin(col.allowed), f'{col.name}: not an allowed value')
        typed[col.name] = value

    flag(typed[key].duplicated(keep='first') | typed[key].isin(seen_keys), f'{key}: duplicate key')

    ok = reasons == ''
    valid = typed[ok].copy()
    for col in columns:
        if col.kind == 'int':
            valid[col.name] = valid[col.name].astype('Int64')
    seen_keys.update(valid[key])
    quarantined = chunk[~ok].copy()
    quarantined['quarantine_reason'] = reasons[~ok]
    return valid, quarantined


def import_source(path, source, engine, batch_size, quarantine_path):
    """Stream one CSV into staging_<source> in batches. Returns ImportStats."""
    stats = ImportStats(source)
    seen = set()
    table = f'staging_{source}'
    if os.path.exists(quarantine_path):
        os.remove(quarantine_path)
    reader = pd.read_csv(path, dtype=str, keep_default_na=False, chunksize=batch_size)
    while True:
        start = time.perf_counter()
        try:
            chunk = next(reader)
        except StopIteration:
            stats.seconds['read'] += time.perf_counter() - start
            break
        stats.seconds['read'] += time.perf_counter() - start

        start = time.perf_counter()
        valid, quarantined = validate_chunk(chunk, source, seen)
        stats.seconds['validate'] += time.perf_counter() - start

        start = time.perf_counter()
        with engine.begin() as conn:
            valid.to_sql(table, conn, if_exists='append', index=False, method='multi')
        if len(quarantined):
            quarantined.to_csv(quarantine_path, mode='a', index=False,
                               header=not os.path.exists(quarantine_path))
        stats.seconds['load'] += time.perf_counter() - start

        stats.batches += 1
        stats.rows_read += len(chunk)
        stats.rows_loaded += len(valid)
        stats.rows_quarantined += len(quarantined)
        for reason, n in quarantined['quarantine_reason'].value_counts().items():
            stats.reasons[reason] = stats.reasons.get(reason, 0) + int(n)
    return stats


def run_import(engine, raw_dir, quarantine_dir, batch_size):
    """Truncate the staging tables and import every source. Returns {source: ImportStats}."""
    os.makedirs(quarantine_dir, exist_ok=True)
    with engine.begin() as conn:
        for source in reversed(IMPORT_ORDER):
            conn.execute(text(f'DELETE FROM staging_{source}'))
    return {
        source: import_source(os.path.join(raw_dir, f'{source}.csv'), source, engine, batch_size,
                              os.path.join(quarantine_dir, f'{source}_quarantine.csv'))
        for source in IMPORT_ORDER
    }


def profile_batch_sizes(engine, raw_dir, quarantine_dir, batch_sizes):
    """Run the full import once per batch size and report stage runtimes and peak memory."""
    results = []
    for batch_size in batch_sizes:
        tracemalloc.start()
        start = time.perf_counter()
        stats = run_import(engine, raw_dir, quarantine_dir, batch_size)
        total = time.perf_counter() - start
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        stages = {stage: round(sum(s.seconds[stage] for s in stats.values()), 4)
                  for stage in ('read', 'validate', 'load')}
        results.append({
            'batch_size': batch_size,
            'total_seconds': round(total, 4),
            'stage_seconds': stages,
            'peak_memory_mib': round(peak / 2**20, 3),
            'sources': {name: {'batches': s.batches, 'rows_read': s.rows_read,
                               'rows_loaded': s.rows_loaded, 'rows_quarantined': s.rows_quarantined,
                               'reasons': s.reasons}
                        for name, s in stats.items()},
        })
    return results


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--batch-sizes', type=int, nargs='+', default=[100, 500, 2000])
    parser.add_argument('--raw-dir', default=PATHS['raw_data'])
    parser.add_argument('--quarantine-dir', default=os.path.join('data', 'quarantine'))
    parser.add_argument('--database-url', default=os.environ.get('DATABASE_URL'),
                        help='defaults to $DATABASE_URL; the staging DDL must already be applied')
    parser.add_argument('--output', default=os.path.join('reports', 'import_profile.json'))
    args = parser.parse_args(argv)
    if not args.database_url:
        parser.error('set --database-url or DATABASE_URL')
    engine = create_engine(args.database_url)
    results = profile_batch_sizes(engine, args.raw_dir, args.quarantine_dir, args.batch_sizes)
    with open(args.output, 'w') as fh:
        json.dump(results, fh, indent=2)
    for r in results:
        print(f"batch={r['batch_size']:>6} total={r['total_seconds']:.3f}s "
              f"stages={r['stage_seconds']} peak={r['peak_memory_mib']}MiB")


if __name__ == '__main__':
    main()
