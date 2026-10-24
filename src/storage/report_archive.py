"""Archive generated reports in MinIO and index their metadata in OpenSearch.

Each report file is stored under a versioned object key:

    reports/<report_name>/v<NNNN>/<file_name>

A new version is written only when the file's SHA-256 differs from the latest
stored version, so re-running the archive is idempotent. The OpenSearch
document carries the object key, checksum, and the Postgres source
identifiers (database, tables, primary keys, date_key range) the report was
computed from, so a search hit leads back to both the bytes and the warehouse
rows behind them.

The object store and search index are injected. ``MinioStore`` and
``OpenSearchIndex`` wrap the real clients; tests use in-memory fakes.
"""
import argparse
import hashlib
import json
import mimetypes
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

INDEX_NAME = 'ecom-reports'
KEY_PREFIX = 'reports'
_VERSION_RE = re.compile(r'/v(\d{4})/')

# Every generated report is derived from the Postgres star schema. These are
# the tables and primary keys src/insights/kpis.py reads.
POSTGRES_SOURCE = {
    'engine': 'postgresql',
    'database': 'ecommerce',
    'tables': {
        'fact_sales': ['item_id'],
        'dim_product': ['product_id'],
        'dim_customer': ['customer_id'],
        'dim_date': ['date_key'],
    },
}


class ObjectStore(Protocol):
    def put(self, key: str, data: bytes, content_type: str, metadata: dict) -> None: ...
    def get(self, key: str) -> bytes: ...
    def list_keys(self, prefix: str) -> list[str]: ...


class SearchIndex(Protocol):
    def index(self, doc_id: str, doc: dict) -> None: ...
    def get(self, doc_id: str) -> dict | None: ...
    def search(self, term_filters: dict) -> list[dict]: ...


def postgres_source(kpis_path: Path | None) -> dict:
    """Return the Postgres source identifiers, with the date_key range from kpis.json."""
    source = json.loads(json.dumps(POSTGRES_SOURCE))
    if kpis_path and kpis_path.exists():
        kpis = json.loads(kpis_path.read_text())
        source['date_key_range'] = [kpis.get('period_start'), kpis.get('period_end')]
    return source


def report_name(path: Path) -> str:
    return re.sub(r'[^a-z0-9_-]+', '-', path.name.lower()).strip('-')


def _latest(store: ObjectStore, name: str) -> tuple[int, str | None]:
    """Return (latest version number, its key) for a report, or (0, None)."""
    best, best_key = 0, None
    for key in store.list_keys(f'{KEY_PREFIX}/{name}/'):
        match = _VERSION_RE.search(key)
        if match and int(match.group(1)) > best:
            best, best_key = int(match.group(1)), key
    return best, best_key


def archive_report(path: Path, store: ObjectStore, index: SearchIndex,
                   source: dict, now: datetime | None = None) -> dict:
    """Store one report file and index its metadata. Returns the index document."""
    data = path.read_bytes()
    sha256 = hashlib.sha256(data).hexdigest()
    name = report_name(path)
    version, latest_key = _latest(store, name)
    if latest_key:
        existing = index.get(latest_key)
        if existing and existing['sha256'] == sha256:
            return existing

    version += 1
    key = f'{KEY_PREFIX}/{name}/v{version:04d}/{path.name}'
    content_type = mimetypes.guess_type(path.name)[0] or 'application/octet-stream'
    store.put(key, data, content_type, {
        'sha256': sha256,
        'report-name': name,
        'source-database': source['database'],
        'source-tables': ','.join(source['tables']),
    })
    doc = {
        'object_key': key,
        'report_name': name,
        'version': version,
        'file_name': path.name,
        'content_type': content_type,
        'size_bytes': len(data),
        'sha256': sha256,
        'archived_at': (now or datetime.now(timezone.utc)).isoformat(),
        'source': source,
    }
    index.index(key, doc)
    return doc


def fetch_report(object_key: str, store: ObjectStore, index: SearchIndex) -> bytes:
    """Read a report back and verify it against the indexed checksum."""
    doc = index.get(object_key)
    if doc is None:
        raise KeyError(f'{object_key} is not indexed')
    data = store.get(object_key)
    if hashlib.sha256(data).hexdigest() != doc['sha256']:
        raise ValueError(f'{object_key} does not match its indexed sha256')
    return data


def archive_directory(reports_dir: Path, store: ObjectStore, index: SearchIndex) -> list[dict]:
    source = postgres_source(reports_dir / 'kpis.json')
    return [archive_report(path, store, index, source)
            for path in sorted(reports_dir.iterdir()) if path.is_file()]


class MinioStore:
    def __init__(self, client, bucket: str):
        self.client, self.bucket = client, bucket
        if not client.bucket_exists(bucket):
            client.make_bucket(bucket)

    def put(self, key, data, content_type, metadata):
        import io
        self.client.put_object(self.bucket, key, io.BytesIO(data), len(data),
                               content_type=content_type, metadata=metadata)

    def get(self, key):
        response = self.client.get_object(self.bucket, key)
        try:
            return response.read()
        finally:
            response.close()
            response.release_conn()

    def list_keys(self, prefix):
        return [obj.object_name for obj in
                self.client.list_objects(self.bucket, prefix=prefix, recursive=True)]


class OpenSearchIndex:
    MAPPING = {'mappings': {'properties': {
        'object_key': {'type': 'keyword'}, 'report_name': {'type': 'keyword'},
        'version': {'type': 'integer'}, 'file_name': {'type': 'keyword'},
        'content_type': {'type': 'keyword'}, 'size_bytes': {'type': 'long'},
        'sha256': {'type': 'keyword'}, 'archived_at': {'type': 'date'},
        'source': {'type': 'object'},
    }}}

    def __init__(self, client, name: str = INDEX_NAME):
        self.client, self.name = client, name
        if not client.indices.exists(index=name):
            client.indices.create(index=name, body=self.MAPPING)

    def index(self, doc_id, doc):
        self.client.index(index=self.name, id=doc_id, body=doc, refresh=True)

    def get(self, doc_id):
        if not self.client.exists(index=self.name, id=doc_id):
            return None
        return self.client.get(index=self.name, id=doc_id)['_source']

    def search(self, term_filters):
        query = {'bool': {'filter': [{'term': {k: v}} for k, v in term_filters.items()]}}
        hits = self.client.search(index=self.name, body={'query': query, 'size': 100})
        return [hit['_source'] for hit in hits['hits']['hits']]


def connect_from_env() -> tuple[MinioStore, OpenSearchIndex]:
    """Build real clients from MINIO_* and OPENSEARCH_URL environment variables."""
    from minio import Minio
    from opensearchpy import OpenSearch

    minio = Minio(os.getenv('MINIO_ENDPOINT', 'localhost:9000'),
                  access_key=os.environ['MINIO_ACCESS_KEY'],
                  secret_key=os.environ['MINIO_SECRET_KEY'],
                  secure=os.getenv('MINIO_SECURE', 'false') == 'true')
    search = OpenSearch(os.getenv('OPENSEARCH_URL', 'http://localhost:9200'))
    return (MinioStore(minio, os.getenv('MINIO_BUCKET', 'ecom-reports')),
            OpenSearchIndex(search))


def main() -> None:
    from src.config import PATHS

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--reports-dir', type=Path, default=Path(PATHS['reports']))
    args = parser.parse_args()
    store, index = connect_from_env()
    for doc in archive_directory(args.reports_dir, store, index):
        print(f"{doc['object_key']}  {doc['sha256'][:12]}")


if __name__ == '__main__':
    main()
