"""Offline smoke check for the built API image and the pinned n8n importer.

Build ecom-briefings:d8cb693 from Dockerfile.briefings before running this check.
"""

import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(args, expected, timeout):
    result = subprocess.run(args, cwd=ROOT, text=True, capture_output=True, timeout=timeout, check=False)
    if result.returncode or expected not in result.stdout:
        raise AssertionError(result.stdout[-2000:] + result.stderr[-2000:])
    print(expected, flush=True)


def main():
    start = time.monotonic()
    print("Checking API image with a read-only report mount and nonroot state writes", flush=True)
    run([
        "docker", "run", "--rm", "--network", "none",
        "--mount", f"type=bind,source={ROOT / 'reports'},target=/app/reports,readonly",
        "ecom-briefings:d8cb693", "python", "-c", """
import os
import httpx
from fastapi.testclient import TestClient
from src.delivery_api import create_app
assert os.getuid() == 10001
app = create_app(token='offline-container-test', destinations={'sales': 'http://receiver.invalid'},
                 transport=httpx.MockTransport(lambda request: httpx.Response(204)))
headers = {'Authorization': 'Bearer offline-container-test', 'Idempotency-Key': 'container-smoke'}
with TestClient(app) as client:
    assert client.get('/briefings/sales', headers=headers).status_code == 200
    response = client.post('/deliveries/sales', headers=headers)
    assert response.status_code == 200, response.text
    assert response.json()['status'] == 'delivered'
    assert client.post('/deliveries/sales', headers=headers).json()['attempts'] == 1
assert os.path.isfile('/state/deliveries.sqlite3')
print('API container smoke passed')
""",
    ], "API container smoke passed", 8)
    print("Importing both workflows into an isolated n8n database without network access", flush=True)
    run([
        "docker", "run", "--rm", "--network", "none",
        "--tmpfs", "/home/node/.n8n:uid=1000,gid=1000,mode=0700",
        "--mount", f"type=bind,source={ROOT / 'n8n'},target=/workflows,readonly",
        "-e", "N8N_DIAGNOSTICS_ENABLED=false",
        "docker.n8n.io/n8nio/n8n:2.42.4", "import:workflow", "--separate", "--input=/workflows",
    ], "Successfully imported 2 workflows.", 20)
    print(f"Container checks passed in {time.monotonic() - start:.1f}s", flush=True)


if __name__ == "__main__":
    main()
