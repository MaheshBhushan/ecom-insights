"""Check the deployable workflow contracts and isolated Compose definition."""

import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_workflow_schedules_keys_retries_and_credentials():
    for audience, hour in (("sales", 8), ("marketing", 9)):
        workflow = json.loads((ROOT / "n8n" / f"{audience}-briefing.json").read_text())
        assert workflow["active"] is False
        assert workflow["settings"]["timezone"] == "Europe/Berlin"
        schedule, identity, request = workflow["nodes"]
        assert schedule["parameters"]["rule"]["interval"][0]["expression"] == f"0 {hour} * * 1-5"
        value = identity["parameters"]["assignments"]["assignments"][0]["value"]
        assert f"ecom-{audience}-" in value
        assert "Europe/Berlin" in value and "toISODate()" in value
        assert request["parameters"]["url"] == f"http://briefing-api:8000/deliveries/{audience}"
        assert request["parameters"]["method"] == "POST"
        assert request["retryOnFail"] and request["maxTries"] == 3
        assert request["waitBetweenTries"] == 5000
        assert request["onError"] == "stopWorkflow"
        assert request["parameters"]["options"]["timeout"] == 20000
        assert request["parameters"]["headerParameters"]["parameters"] == [
            {"name": "Idempotency-Key", "value": "={{ $json.delivery_key }}"}]
        assert request["credentials"]["httpHeaderAuth"]["id"] == "CONFIGURE_BRIEFING_API_HEADER_AUTH"
        for source, target in ((schedule, identity), (identity, request)):
            assert workflow["connections"][source["name"]]["main"][0][0]["node"] == target["name"]


def test_compose_configuration_is_local_and_persistent():
    # Supply a synthetic test token without reading any private .env file.
    result = subprocess.run([
        "docker", "compose", "--env-file", "/dev/null", "-f",
        "docker-compose.briefings.yml", "config", "--format", "json",
    ], cwd=ROOT, env={**os.environ, "BRIEFING_API_TOKEN": "offline-compose-test"},
        text=True, capture_output=True, timeout=10, check=True)
    config = json.loads(result.stdout)
    assert set(config["services"]) == {"briefing-api", "n8n"}
    api, n8n = config["services"]["briefing-api"], config["services"]["n8n"]
    assert api["ports"][0]["host_ip"] == n8n["ports"][0]["host_ip"] == "127.0.0.1"
    assert any(v["target"] == "/state" and v["type"] == "volume" for v in api["volumes"])
    assert any(v["target"] == "/app/reports" and v["read_only"] for v in api["volumes"])
    assert any(v["target"] == "/home/node/.n8n" for v in n8n["volumes"])
