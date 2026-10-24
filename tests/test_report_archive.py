"""Round-trip the generated report fixtures through fake MinIO and OpenSearch."""

import hashlib
import shutil
from pathlib import Path

import pytest

from src.storage.report_archive import (archive_directory, archive_report, fetch_report,
                                        postgres_source)

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ['kpis.json', 'executive_briefing.json', 'executive_briefing.md',
            'cohort_retention.png', 'ecom_insights_analysis.xlsx']


class FakeStore:
    def __init__(self):
        self.objects = {}

    def put(self, key, data, content_type, metadata):
        self.objects[key] = (data, content_type, metadata)

    def get(self, key):
        return self.objects[key][0]

    def list_keys(self, prefix):
        return [key for key in self.objects if key.startswith(prefix)]


class FakeIndex:
    def __init__(self):
        self.docs = {}

    def index(self, doc_id, doc):
        self.docs[doc_id] = doc

    def get(self, doc_id):
        return self.docs.get(doc_id)

    def search(self, term_filters):
        return [doc for doc in self.docs.values()
                if all(doc.get(k) == v for k, v in term_filters.items())]


@pytest.fixture
def reports(tmp_path):
    for name in FIXTURES:
        shutil.copy(ROOT / 'reports' / name, tmp_path / name)
    return tmp_path


def test_round_trip_preserves_bytes_and_postgres_source(reports):
    store, index = FakeStore(), FakeIndex()
    docs = archive_directory(reports, store, index)

    assert len(docs) == len(FIXTURES)
    for doc in docs:
        assert doc['object_key'] == f"reports/{doc['report_name']}/v0001/{doc['file_name']}"
        original = (reports / doc['file_name']).read_bytes()
        assert fetch_report(doc['object_key'], store, index) == original
        assert doc['sha256'] == hashlib.sha256(original).hexdigest()
        assert doc['source']['tables']['fact_sales'] == ['item_id']
        assert doc['source']['date_key_range'] == ['2025-06-30', '2026-06-30']
        assert store.objects[doc['object_key']][2]['source-database'] == 'ecommerce'

    [hit] = index.search({'report_name': 'kpis-json'})
    assert hit['content_type'] == 'application/json'


def test_unchanged_report_is_not_versioned_again_and_changed_one_is(reports):
    store, index = FakeStore(), FakeIndex()
    source = postgres_source(reports / 'kpis.json')
    path = reports / 'executive_briefing.md'

    first = archive_report(path, store, index, source)
    assert archive_report(path, store, index, source) == first
    assert len(store.objects) == 1

    path.write_text(path.read_text() + '\nRevised.\n')
    second = archive_report(path, store, index, source)
    assert second['version'] == 2
    assert second['object_key'].endswith('/v0002/executive_briefing.md')
    assert fetch_report(first['object_key'], store, index) != path.read_bytes()
    assert fetch_report(second['object_key'], store, index) == path.read_bytes()


def test_fetch_rejects_tampered_or_unindexed_objects(reports):
    store, index = FakeStore(), FakeIndex()
    doc = archive_report(reports / 'kpis.json', store, index, postgres_source(None))
    data, content_type, metadata = store.objects[doc['object_key']]
    store.objects[doc['object_key']] = (data + b' ', content_type, metadata)

    with pytest.raises(ValueError):
        fetch_report(doc['object_key'], store, index)
    with pytest.raises(KeyError):
        fetch_report('reports/missing/v0001/missing.json', store, index)
