import re

import anyio
from fastapi.testclient import TestClient

from changeproof.app import app, create_app, provider_from_env
from changeproof.demo import analyze_demo_change
from changeproof.enterprise import analyze_enterprise_change
from changeproof.live import analyze_live_change

client = TestClient(app)


def _analysis_token(path: str = "/datahub") -> str:
    response = client.get(path)
    match = re.search(r'name="analysis_token" value="([^"]+)"', response.text)
    assert match is not None
    return match.group(1)


def test_healthz() -> None:
    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "changeproof"}


def test_architecture_documentation_is_source_grounded() -> None:
    response = client.get("/documentation/architecture")
    alias_response = client.get("/docs/architecture")

    assert response.status_code == 200
    assert alias_response.status_code == 200
    assert "Architecture | contextIsKey documentation" in response.text
    assert "Source verified" in response.text
    assert "DataHub MCP adapter" in response.text
    assert "Generated SQL is review material" in response.text


def test_dashboard_labels_demo_evidence() -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert "contextIsKey" in response.text
    assert "Bundled AsterVale Living DataHub metadata" in response.text
    assert 'href="/static/styles.css"' in response.text
    assert 'href="/static/minimal.css"' in response.text
    assert 'aria-label="Investigation stages"' in response.text


def test_triage_uses_the_minimal_context_first_workflow() -> None:
    response = client.get("/triage")

    assert response.status_code == 200
    assert "What needs investigation?" in response.text
    assert "Show the context used" in response.text
    assert "Context before action." in response.text
    assert "Architecture" in response.text


def test_analyze_renders_downstream_impact_and_safe_fix() -> None:
    response = client.post(
        "/analyze",
        data={"column": "artist_id", "old_type": "varchar", "new_type": "bigint"},
    )

    assert response.status_code == 200
    assert "artist_payouts" in response.text
    assert "parallel_typed_field" in response.text
    assert "Proposed safe rollout" in response.text


def test_analyze_returns_validation_message() -> None:
    response = client.post(
        "/analyze",
        data={"column": "unknown", "old_type": "varchar", "new_type": "bigint"},
    )

    assert response.status_code == 422
    assert "Unknown column" in response.text


def test_dashboard_displays_injected_live_evidence_label() -> None:
    def live_provider(**values: str):
        result = analyze_demo_change(**values)
        return result.__class__(
            request=result.request,
            evidence=result.evidence,
            impact=result.impact,
            plan=result.plan,
            evidence_source="Live DataHub MCP evidence",
        )

    live_client = TestClient(create_app(live_provider))
    response = live_client.get("/")
    post_response = live_client.post(
        "/analyze",
        data={"column": "artist_id", "old_type": "varchar", "new_type": "bigint"},
    )

    assert response.status_code == 200
    assert "Live DataHub MCP evidence" in response.text
    assert "Bundled SonicLedger demo metadata" not in response.text
    assert post_response.status_code == 200
    assert "Live DataHub MCP evidence" in post_response.text
    assert "artist_payouts" in post_response.text


def test_live_provider_failure_returns_503_without_demo_fallback() -> None:
    def unavailable_provider(**values: str):
        raise RuntimeError("DataHub MCP unavailable")

    response = TestClient(create_app(unavailable_provider)).get("/")

    assert response.status_code == 503
    assert "DataHub MCP unavailable" in response.text
    assert "Bundled SonicLedger demo metadata" not in response.text


def test_mcp_value_error_is_service_failure_not_input_error() -> None:
    def missing_tools_provider(**values: str):
        raise ValueError("Missing required DataHub MCP tools: get_lineage")

    failure_client = TestClient(create_app(missing_tools_provider))
    get_response = failure_client.get("/")
    post_response = failure_client.post(
        "/analyze",
        data={"column": "artist_id", "old_type": "varchar", "new_type": "bigint"},
    )

    assert get_response.status_code == 503
    assert post_response.status_code == 503
    assert "Missing required DataHub MCP tools" in post_response.text


def test_post_runs_sync_mcp_style_provider_outside_async_event_loop() -> None:
    async def async_probe() -> None:
        return None

    def mcp_style_provider(**values: str):
        anyio.run(async_probe)
        return analyze_demo_change(**values)

    response = TestClient(create_app(mcp_style_provider)).post(
        "/analyze",
        data={"column": "artist_id", "old_type": "varchar", "new_type": "bigint"},
    )

    assert response.status_code == 200
    assert "parallel_typed_field" in response.text


def test_provider_from_env_defaults_to_bundled(monkeypatch) -> None:
    monkeypatch.delenv("CHANGE_PROOF_EVIDENCE_MODE", raising=False)

    assert provider_from_env() is analyze_enterprise_change


def test_provider_from_env_selects_datahub(monkeypatch) -> None:
    monkeypatch.setenv("CHANGE_PROOF_EVIDENCE_MODE", "datahub")

    assert provider_from_env() is analyze_live_change


def test_provider_from_env_rejects_unknown_mode(monkeypatch) -> None:
    monkeypatch.setenv("CHANGE_PROOF_EVIDENCE_MODE", "mystery")

    try:
        provider_from_env()
    except RuntimeError as exc:
        assert "Unknown CHANGE_PROOF_EVIDENCE_MODE" in str(exc)
    else:
        raise AssertionError("Expected an unknown evidence mode to fail")


def test_dashboard_shows_writeback_drafts_and_the_approval_gate() -> None:
    response = client.get("/datahub")

    assert response.status_code == 200
    assert "Draft changes for DataHub" in response.text
    assert "Nothing is written without approval" in response.text
    assert 'action="/writeback/apply"' in response.text
    assert 'name="approve"' in response.text


def test_writeback_requires_selecting_a_proposal() -> None:
    response = client.post(
        "/writeback/apply",
        data={"analysis_token": _analysis_token()},
    )

    assert response.status_code == 422
    assert "Select at least one proposal" in response.text


def test_writeback_refuses_when_no_datahub_is_reachable(monkeypatch) -> None:
    # Pin to the discard port so the suite never talks to a real DataHub, even
    # when one is running locally from `make live-demo`.
    monkeypatch.setenv("DATAHUB_GMS_URL", "http://127.0.0.1:9")

    response = client.post(
        "/writeback/apply",
        data={
            "column": "artist_id",
            "old_type": "varchar",
            "new_type": "bigint",
            "approve": "incident-source",
            "analysis_token": _analysis_token(),
        },
    )

    assert response.status_code == 503
    assert "nothing was written" in response.text


def test_writeback_ignores_forged_change_values(monkeypatch) -> None:
    monkeypatch.setenv("CHANGE_PROOF_WRITEBACK_MODE", "simulated")
    response = client.post(
        "/writeback/apply",
        data={
            "column": "unknown",
            "old_type": "attacker_type",
            "new_type": "attacker_type_2",
            "approve": "docs-source",
            "analysis_token": _analysis_token(),
        },
    )

    assert response.status_code == 200
    assert "AsterVale Living" in response.text
    assert "attacker_type" not in response.text


def test_writeback_rejects_missing_or_tampered_analysis_token(monkeypatch) -> None:
    monkeypatch.setenv("CHANGE_PROOF_WRITEBACK_MODE", "simulated")

    missing = client.post(
        "/writeback/apply", data={"approve": "incident-source"}
    )
    tampered = client.post(
        "/writeback/apply",
        data={"approve": "incident-source", "analysis_token": "tampered"},
    )

    assert missing.status_code == 403
    assert tampered.status_code == 403


def test_static_assets_must_revalidate() -> None:
    # Without this, browsers heuristically cache the stylesheet and can show a
    # stale theme for a long time after a deploy.
    response = client.get("/static/styles.css")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-cache"
    assert response.headers.get("etag")


def test_html_responses_are_not_marked_no_cache() -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert "cache-control" not in response.headers


def test_simulated_mode_labels_the_flow_and_completes_it(monkeypatch) -> None:
    monkeypatch.setenv("CHANGE_PROOF_WRITEBACK_MODE", "simulated")

    page = client.get("/datahub")
    assert "SIMULATED" in page.text
    assert "No DataHub is connected" in page.text

    response = client.post(
        "/writeback/apply",
        data={
            "column": "artist_id",
            "old_type": "varchar",
            "new_type": "bigint",
            "approve": "incident-source",
            "analysis_token": _analysis_token(),
        },
    )

    assert response.status_code == 200
    assert "recorded in the demo catalog, not sent to DataHub" in response.text
    assert "written to DataHub" not in response.text


def test_simulated_mode_never_claims_a_datahub_write(monkeypatch) -> None:
    monkeypatch.setenv("CHANGE_PROOF_WRITEBACK_MODE", "simulated")

    response = client.post(
        "/writeback/apply",
        data={
            "column": "artist_id",
            "old_type": "varchar",
            "new_type": "bigint",
            "approve": "docs-source",
            "analysis_token": _analysis_token(),
        },
    )

    assert "SIMULATED" in response.text
    assert "not sent to DataHub" in response.text


def test_every_catalog_scenario_renders_without_error() -> None:
    from changeproof.demo import CATALOG

    for name, entry in CATALOG.items():
        response = client.post(
            "/analyze",
            data={
                "column": name,
                "old_type": entry.old_type,
                "new_type": entry.new_type,
            },
        )
        assert response.status_code == 200, f"{name} failed to render"


def test_zero_downstream_scenario_renders_the_empty_state() -> None:
    # This previously raised UndefinedError on impacted_assets[-1].
    response = client.post(
        "/analyze",
        data={"column": "listener_email", "old_type": "varchar", "new_type": "text"},
    )

    assert response.status_code == 200
    assert "No downstream consumers" in response.text
    assert "not proof" in response.text


def test_dashboard_offers_the_other_catalog_columns() -> None:
    response = client.get("/")

    assert response.status_code == 200
    for name in ("track_id", "payout_amount", "stream_ts", "listener_email"):
        assert name in response.text


def test_source_card_reflects_the_analyzed_column_not_a_hardcoded_one() -> None:
    # stg_streams/artist_id used to be baked into the template, so every
    # scenario claimed the wrong source table and owner.
    response = client.post(
        "/analyze",
        data={"column": "listener_email", "old_type": "varchar", "new_type": "text"},
    )

    assert response.status_code == 200
    assert '<span class="source-pill">stg_listeners.listener_email</span>' in response.text
    assert "growth@sonicledger.demo" in response.text
    assert '<span class="source-pill">stg_streams.artist_id</span>' not in response.text


def test_payout_scenario_shows_its_own_source_table() -> None:
    response = client.post(
        "/analyze",
        data={
            "column": "payout_amount",
            "old_type": "decimal(10,2)",
            "new_type": "decimal(18,4)",
        },
    )

    assert response.status_code == 200
    assert "fct_royalties.payout_amount" in response.text
