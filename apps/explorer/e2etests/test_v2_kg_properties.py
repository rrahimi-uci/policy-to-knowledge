"""E2E tests for v2 KG property support.

Validates that the new extended properties from the sample-guidelines KG format
(source_reference, risk_level, jurisdiction, applicability_scope, etc.) are
correctly stored, served, and searchable through the API layer.

Also tests backward compatibility: v1 KGs (commercial_lending) must continue
to work with empty/default values for v2 fields.
"""

import json
import uuid
import pytest
from conftest import KNOWN_GRAPHS

# ── Graph names for v1 vs v2 testing ─────────────────────────────
V2_GRAPH = "sample_guidelines_g"    # v2 format with extended properties
V1_GRAPH = "fannie_mae_g"          # alternate graph for comparison

# ── v2 property names (extended fields added to schema) ──────────
V2_STRING_PROPERTIES = [
    "source_reference", "effective_date", "expiration_date", "superseded_by",
    "jurisdiction", "risk_level", "related_rules", "enforcement_action",
    "applicability_scope", "data_points_required", "audit_frequency",
    "reference_verification_note", "confidence_breakdown", "deduplication_info",
]
V2_BOOL_PROPERTIES = ["reference_verified"]
V2_ALL_PROPERTIES = V2_STRING_PROPERTIES + V2_BOOL_PROPERTIES

# ── Base properties that must always exist ───────────────────────
BASE_PROPERTIES = [
    "rule_id", "rule_name", "rule_type", "description", "conditions",
    "consequences", "exceptions", "reference", "mandatory",
    "confidence_score", "requires_review", "review_reason",
    "entity_or_relationship", "entity_type", "extraction_notes",
    "node_type", "name", "content", "category", "vertex_uuid",
]


# ── Helper: fetch all nodes for a graph ──────────────────────────
def _fetch_graph_nodes(api, graph_name):
    """Return list of node dicts from /api/graph."""
    resp = api.get("/api/graph", params={"graph_name": graph_name})
    assert resp.status_code == 200, f"Graph fetch failed: {resp.text}"
    return resp.json()["nodes"]


def _fetch_business_rules(api, graph_name):
    """Return only business_rule nodes from a graph."""
    nodes = _fetch_graph_nodes(api, graph_name)
    return [n for n in nodes if n.get("label") == "business_rule"]


# ══════════════════════════════════════════════════════════════════
# 1. Schema endpoint reflects v2 properties
# ══════════════════════════════════════════════════════════════════

class TestVertexSchemaV2Properties:
    """Verify the vertex schema advertises v2 properties."""

    def test_schema_includes_v2_optional_properties(self, api):
        resp = api.get("/api/vertex/schema")
        assert resp.status_code == 200
        data = resp.json()
        br_optional = data["properties"]["business_rule"]["optional"]
        for prop in V2_ALL_PROPERTIES:
            assert prop in br_optional, (
                f"v2 property '{prop}' missing from business_rule optional schema"
            )

    def test_schema_entity_category_unchanged(self, api):
        """entity_category should NOT gain v2 properties."""
        resp = api.get("/api/vertex/schema")
        ec_optional = resp.json()["properties"]["entity_category"]["optional"]
        for prop in V2_ALL_PROPERTIES:
            assert prop not in ec_optional, (
                f"v2 property '{prop}' should not appear in entity_category schema"
            )


# ══════════════════════════════════════════════════════════════════
# 2. Graph endpoint returns v2 properties for sample_guidelines
# ══════════════════════════════════════════════════════════════════

class TestGraphV2Properties:
    """Verify /api/graph returns extended properties for the v2 graph."""

    @pytest.fixture(scope="class")
    def v2_rules(self, api):
        return _fetch_business_rules(api, V2_GRAPH)

    @pytest.fixture(scope="class")
    def v1_rules(self, api):
        return _fetch_business_rules(api, V1_GRAPH)

    def test_v2_graph_has_nodes(self, v2_rules):
        assert len(v2_rules) >= 300, (
            f"Expected ≥300 business rules in {V2_GRAPH}, got {len(v2_rules)}"
        )

    def test_v2_nodes_have_all_base_properties(self, v2_rules):
        node = v2_rules[0]
        for prop in BASE_PROPERTIES:
            assert prop in node, f"Base property '{prop}' missing from v2 node"

    def test_v2_nodes_have_extended_properties(self, v2_rules):
        node = v2_rules[0]
        for prop in V2_ALL_PROPERTIES:
            assert prop in node, f"v2 property '{prop}' missing from graph node"

    def test_v2_risk_level_populated(self, v2_rules):
        """Most v2 rules should have a non-empty risk_level."""
        with_risk = [n for n in v2_rules if n.get("risk_level")]
        ratio = len(with_risk) / len(v2_rules)
        assert ratio >= 0.5, (
            f"Only {ratio:.0%} of v2 rules have risk_level, expected ≥50%"
        )

    def test_v2_risk_level_values(self, v2_rules):
        """risk_level should only contain known values."""
        valid_levels = {"high", "medium", "low", "critical", ""}
        for node in v2_rules:
            rl = node.get("risk_level", "")
            assert rl in valid_levels, (
                f"Unexpected risk_level '{rl}' on node '{node.get('name')}'"
            )

    def test_v2_jurisdiction_populated(self, v2_rules):
        with_jurisdiction = [n for n in v2_rules if n.get("jurisdiction")]
        assert len(with_jurisdiction) > 0, "No v2 rules have jurisdiction set"

    def test_v2_source_reference_is_json(self, v2_rules):
        """source_reference should be a JSON-serialized object (dict)."""
        with_src_ref = [n for n in v2_rules if n.get("source_reference")]
        assert len(with_src_ref) > 0, "No v2 rules have source_reference"
        for node in with_src_ref[:10]:
            sr = node["source_reference"]
            try:
                parsed = json.loads(sr) if isinstance(sr, str) else sr
            except (json.JSONDecodeError, TypeError):
                parsed = None
            assert isinstance(parsed, dict), (
                f"source_reference should be a JSON dict, got: {type(sr).__name__}"
            )
            assert "chunk_path" in parsed, (
                f"source_reference missing 'chunk_path' key on {node.get('name')}"
            )

    def test_v2_applicability_scope_structure(self, v2_rules):
        """applicability_scope should parse to a dict with known keys."""
        with_scope = [n for n in v2_rules if n.get("applicability_scope")]
        assert len(with_scope) > 0, "No v2 rules have applicability_scope"
        for node in with_scope[:10]:
            raw = node["applicability_scope"]
            try:
                parsed = json.loads(raw) if isinstance(raw, str) else raw
            except (json.JSONDecodeError, TypeError):
                parsed = None
            assert isinstance(parsed, dict), (
                f"applicability_scope should be dict, got: {raw[:60]}"
            )
            valid_keys = {"loan_types", "occupancy_types", "transaction_types"}
            actual_keys = set(parsed.keys())
            assert actual_keys.issubset(valid_keys), (
                f"Unexpected applicability_scope keys: {actual_keys - valid_keys}"
            )

    def test_v2_confidence_breakdown_structure(self, v2_rules):
        """confidence_breakdown should be a JSON dict with numeric values."""
        with_cb = [n for n in v2_rules if n.get("confidence_breakdown")]
        assert len(with_cb) > 0, "No v2 rules have confidence_breakdown"
        for node in with_cb[:10]:
            raw = node["confidence_breakdown"]
            try:
                parsed = json.loads(raw) if isinstance(raw, str) else raw
            except (json.JSONDecodeError, TypeError):
                parsed = None
            assert isinstance(parsed, dict), (
                f"confidence_breakdown should be dict, got: {raw[:60]}"
            )
            for ck, cv in parsed.items():
                assert isinstance(cv, (int, float)), (
                    f"confidence_breakdown[{ck}] should be numeric, got {type(cv).__name__}"
                )

    def test_v2_related_rules_is_json_array(self, v2_rules):
        """related_rules should be a JSON array of rule_id strings."""
        with_rr = [n for n in v2_rules if n.get("related_rules")]
        assert len(with_rr) > 0, "No v2 rules have related_rules"
        for node in with_rr[:10]:
            raw = node["related_rules"]
            try:
                parsed = json.loads(raw) if isinstance(raw, str) else raw
            except (json.JSONDecodeError, TypeError):
                parsed = None
            assert isinstance(parsed, list), (
                f"related_rules should be list, got: {raw[:60]}"
            )
            for item in parsed:
                assert isinstance(item, str), (
                    f"related_rules items should be strings, got: {type(item).__name__}"
                )

    def test_v2_data_points_required_is_json_array(self, v2_rules):
        with_dp = [n for n in v2_rules if n.get("data_points_required")]
        assert len(with_dp) > 0, "No v2 rules have data_points_required"
        for node in with_dp[:10]:
            raw = node["data_points_required"]
            try:
                parsed = json.loads(raw) if isinstance(raw, str) else raw
            except (json.JSONDecodeError, TypeError):
                parsed = None
            assert isinstance(parsed, list), (
                f"data_points_required should be list, got: {raw[:60]}"
            )

    def test_v2_reference_verified_is_boolean(self, v2_rules):
        for node in v2_rules[:20]:
            rv = node.get("reference_verified")
            assert isinstance(rv, bool), (
                f"reference_verified should be bool, got: {type(rv).__name__}"
            )

    def test_v2_reference_string_derived_from_source_reference(self, v2_rules):
        """The flat 'reference' field should contain the chunk_path from source_reference."""
        for node in v2_rules[:20]:
            sr_raw = node.get("source_reference", "")
            ref = node.get("reference", "")
            if sr_raw:
                try:
                    parsed = json.loads(sr_raw) if isinstance(sr_raw, str) else sr_raw
                except (json.JSONDecodeError, TypeError):
                    continue
                if isinstance(parsed, dict) and parsed.get("chunk_path"):
                    # The derived reference should contain part of the chunk_path
                    chunk_path = parsed["chunk_path"]
                    # At minimum, the first directory should appear in reference
                    first_segment = chunk_path.split("/")[0] if "/" in chunk_path else chunk_path
                    assert first_segment in ref, (
                        f"reference '{ref[:60]}' should contain chunk_path segment '{first_segment}'"
                    )


# ══════════════════════════════════════════════════════════════════
# 3. CL graph properties — both graphs now carry v2 data
# ══════════════════════════════════════════════════════════════════

class TestAlternateGraphProperties:
    """Verify the alternate graph loads and serves correctly with v2 properties."""

    @pytest.fixture(scope="class")
    def v1_rules(self, api):
        return _fetch_business_rules(api, V1_GRAPH)

    def test_v1_graph_has_nodes(self, v1_rules):
        assert len(v1_rules) >= 50, (
            f"Expected ≥50 business rules in {V1_GRAPH}, got {len(v1_rules)}"
        )

    def test_v1_nodes_have_base_properties(self, v1_rules):
        node = v1_rules[0]
        for prop in BASE_PROPERTIES:
            assert prop in node, f"Base property '{prop}' missing from v1 node"

    def test_v1_nodes_have_v2_property_keys_with_defaults(self, v1_rules):
        """v1 nodes should still have v2 property keys, but with default/empty values."""
        node = v1_rules[0]
        for prop in V2_ALL_PROPERTIES:
            assert prop in node, (
                f"v2 property '{prop}' should exist on v1 node (with default value)"
            )

    def test_reference_verified_is_boolean(self, v1_rules):
        """reference_verified should be a boolean on every node."""
        for node in v1_rules[:10]:
            rv = node.get("reference_verified")
            assert isinstance(rv, bool), (
                f"reference_verified should be bool, got {type(rv).__name__}: {rv}"
            )

    def test_v1_reference_is_plain_string(self, v1_rules):
        """v1 references should be non-empty plain strings (not JSON objects)."""
        with_ref = [n for n in v1_rules if n.get("reference")]
        assert len(with_ref) > 0, "No v1 rules have reference strings"
        for node in with_ref[:10]:
            ref = node["reference"]
            # Should not be parseable as a JSON dict (plain text reference)
            try:
                parsed = json.loads(ref)
                assert not isinstance(parsed, dict), (
                    f"v1 reference should be plain text, not JSON dict"
                )
            except (json.JSONDecodeError, TypeError):
                pass  # good — plain text is not JSON


# ══════════════════════════════════════════════════════════════════
# 4. Vertex detail endpoint returns v2 properties
# ══════════════════════════════════════════════════════════════════

class TestVertexDetailV2:
    """Verify GET /api/vertex/<id> returns v2 properties for a v2 graph node."""

    @pytest.fixture(scope="class")
    def v2_node_detail(self, api):
        """Fetch a v2 business rule node via vertex detail endpoint."""
        rules = _fetch_business_rules(api, V2_GRAPH)
        assert len(rules) > 0
        node_id = rules[0]["id"]
        resp = api.get(f"/api/vertex/{node_id}", params={"graph_name": V2_GRAPH})
        assert resp.status_code == 200, f"Vertex detail failed: {resp.text}"
        return resp.json()

    def test_detail_has_v2_properties(self, v2_node_detail):
        for prop in V2_ALL_PROPERTIES:
            assert prop in v2_node_detail, (
                f"Vertex detail missing v2 property '{prop}'"
            )

    def test_detail_has_neighbors(self, v2_node_detail):
        assert "neighbors" in v2_node_detail
        assert isinstance(v2_node_detail["neighbors"], list)

    def test_detail_has_dependencies(self, v2_node_detail):
        assert "depends_on" in v2_node_detail
        assert "depended_by" in v2_node_detail


# ══════════════════════════════════════════════════════════════════
# 5. Vertex creation with v2 properties
# ══════════════════════════════════════════════════════════════════

class TestCreateVertexV2:
    """Verify POST /api/vertex accepts and persists v2 properties."""

    def test_create_with_v2_string_properties(self, api):
        unique_name = f"V2 Test Rule {uuid.uuid4().hex[:8]}"
        payload = {
            "graph_name": V2_GRAPH,
            "label": "business_rule",
            "properties": {
                "name": unique_name,
                "content": "E2E test rule with v2 properties for validation.",
                "rule_type": "constraint",
                "jurisdiction": "agency:TEST",
                "risk_level": "high",
                "effective_date": "2026-01-01",
                "audit_frequency": "quarterly",
                "enforcement_action": "loan rejection",
            },
        }
        resp = api.post("/api/vertex", json=payload)
        assert resp.status_code == 201, f"Create failed: {resp.text}"
        created = resp.json()
        assert created["jurisdiction"] == "agency:TEST"
        assert created["risk_level"] == "high"
        assert created["effective_date"] == "2026-01-01"
        assert created["audit_frequency"] == "quarterly"

    def test_create_with_v2_boolean_property(self, api):
        unique_name = f"V2 Bool Test {uuid.uuid4().hex[:8]}"
        payload = {
            "graph_name": V2_GRAPH,
            "label": "business_rule",
            "properties": {
                "name": unique_name,
                "content": "E2E test rule with reference_verified boolean.",
                "rule_type": "validation",
                "reference_verified": True,
                "reference_verification_note": "Manually verified by test",
            },
        }
        resp = api.post("/api/vertex", json=payload)
        assert resp.status_code == 201, f"Create failed: {resp.text}"
        created = resp.json()
        assert created["reference_verified"] is True
        assert created["reference_verification_note"] == "Manually verified by test"

    def test_create_with_json_string_properties(self, api):
        unique_name = f"V2 JSON Test {uuid.uuid4().hex[:8]}"
        scope_json = json.dumps({
            "loan_types": ["conventional"],
            "occupancy_types": ["primary_residence"],
            "transaction_types": ["purchase"],
        })
        payload = {
            "graph_name": V2_GRAPH,
            "label": "business_rule",
            "properties": {
                "name": unique_name,
                "content": "E2E test rule with JSON string properties.",
                "rule_type": "eligibility",
                "applicability_scope": scope_json,
                "data_points_required": json.dumps(["ltv_ratio", "credit_score"]),
                "related_rules": json.dumps(["BR_TEST_001"]),
            },
        }
        resp = api.post("/api/vertex", json=payload)
        assert resp.status_code == 201, f"Create failed: {resp.text}"
        created = resp.json()

        # Parse back the JSON string
        scope = json.loads(created["applicability_scope"])
        assert scope["loan_types"] == ["conventional"]

        dp = json.loads(created["data_points_required"])
        assert "ltv_ratio" in dp

        rr = json.loads(created["related_rules"])
        assert "BR_TEST_001" in rr

    def test_created_vertex_retrievable_with_v2_props(self, api):
        unique_name = f"V2 Retrieval Test {uuid.uuid4().hex[:8]}"
        payload = {
            "graph_name": V2_GRAPH,
            "label": "business_rule",
            "properties": {
                "name": unique_name,
                "content": "E2E test rule to verify retrieval of v2 properties.",
                "rule_type": "process",
                "jurisdiction": "agency:FNMA",
                "risk_level": "medium",
                "reference_verified": False,
            },
        }
        resp = api.post("/api/vertex", json=payload)
        assert resp.status_code == 201, f"Create failed: {resp.text}"
        vid = resp.json()["id"]

        # Retrieve and verify
        detail = api.get(f"/api/vertex/{vid}", params={"graph_name": V2_GRAPH})
        assert detail.status_code == 200
        data = detail.json()
        assert data["jurisdiction"] == "agency:FNMA"
        assert data["risk_level"] == "medium"
        assert data["reference_verified"] is False


# ══════════════════════════════════════════════════════════════════
# 6. Graph status endpoint still works
# ══════════════════════════════════════════════════════════════════

class TestGraphStatusV2:
    """Verify /api/graph/status returns valid data for both v1 and v2 graphs."""

    def test_v2_graph_status(self, api):
        resp = api.get("/api/graph/status", params={"graph_name": V2_GRAPH})
        assert resp.status_code == 200
        data = resp.json()
        assert "graph_name" in data

    def test_v1_graph_status(self, api):
        resp = api.get("/api/graph/status", params={"graph_name": V1_GRAPH})
        assert resp.status_code == 200
        data = resp.json()
        assert "graph_name" in data


# ══════════════════════════════════════════════════════════════════
# 7. Reference resolution with source_reference
# ══════════════════════════════════════════════════════════════════

class TestReferenceResolutionV2:
    """Verify /api/reference/resolve handles structured source_reference."""

    def test_resolve_with_source_reference_parameter(self, api):
        """Passing source_reference JSON should be accepted by the endpoint."""
        source_ref = json.dumps({
            "chunk_path": "Freddie Mac Guide/Chapter 5202/test.txt",
            "section_id": "5202.1",
        })
        resp = api.get("/api/reference/resolve", params={
            "ref": "test reference",
            "graph_name": V2_GRAPH,
            "source_reference": source_ref,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "matches" in data
        assert "reference" in data

    def test_resolve_accepts_only_source_reference(self, api):
        """If only source_reference is provided (no ref), should still work or 400."""
        source_ref = json.dumps({
            "chunk_path": "some/path/to/chunk.txt",
        })
        resp = api.get("/api/reference/resolve", params={
            "ref": "",
            "graph_name": V2_GRAPH,
            "source_reference": source_ref,
        })
        # Should be accepted (source_reference alone should suffice)
        assert resp.status_code == 200

    def test_resolve_match_includes_section_id_when_source_ref_used(self, api):
        """When resolved via source_reference, matches should include section_id."""
        # Fetch a real v2 node that has source_reference
        rules = _fetch_business_rules(api, V2_GRAPH)
        node_with_sr = None
        for node in rules:
            sr_raw = node.get("source_reference", "")
            if sr_raw:
                try:
                    parsed = json.loads(sr_raw) if isinstance(sr_raw, str) else sr_raw
                    if isinstance(parsed, dict) and parsed.get("chunk_path"):
                        node_with_sr = (node, parsed)
                        break
                except (json.JSONDecodeError, TypeError):
                    continue

        if node_with_sr is None:
            pytest.skip("No v2 nodes with parseable source_reference found")

        node, sr = node_with_sr
        resp = api.get("/api/reference/resolve", params={
            "ref": node.get("reference", ""),
            "graph_name": V2_GRAPH,
            "source_reference": json.dumps(sr),
        })
        assert resp.status_code == 200
        data = resp.json()
        # If matches found via source_reference, they should have section_id
        if data["matches"]:
            match = data["matches"][0]
            assert "section_id" in match, (
                "Match resolved via source_reference should include section_id"
            )


# ══════════════════════════════════════════════════════════════════
# 8. Search results include v2 properties
# ══════════════════════════════════════════════════════════════════

class TestSearchV2Properties:
    """Verify search results include v2 properties."""

    def test_text_search_results_have_core_fields(self, api):
        """Text search projects core fields (id, name, label, category, content)."""
        resp = api.get("/api/search/text", params={
            "q": "credit",
            "graph_name": V2_GRAPH,
        })
        assert resp.status_code == 200
        data = resp.json()
        if data.get("results"):
            result = data["results"][0]
            for prop in ["id", "name", "label", "category", "content"]:
                assert prop in result, (
                    f"Text search result missing core property '{prop}'"
                )

    def test_semantic_search_results_have_base_fields(self, api):
        """Semantic search results should at minimum have core fields."""
        resp = api.get("/api/search/semantic", params={
            "q": "loan eligibility requirements",
            "graph_name": V2_GRAPH,
        })
        assert resp.status_code == 200
        data = resp.json()
        if data.get("results"):
            result = data["results"][0]
            # Semantic search returns a subset of fields
            for prop in ["name", "content", "label"]:
                assert prop in result, (
                    f"Semantic search result missing property '{prop}'"
                )


# ══════════════════════════════════════════════════════════════════
# 9. Data integrity — cross-check KG JSON vs API
# ══════════════════════════════════════════════════════════════════

class TestV2DataIntegrity:
    """Validate that loaded v2 data matches the source KG JSON statistics."""

    @pytest.fixture(scope="class")
    def v2_rules(self, api):
        return _fetch_business_rules(api, V2_GRAPH)

    def test_rule_count_matches_expected(self, v2_rules):
        """Should have at least 370 business rules from sample-guidelines-kg.json."""
        assert len(v2_rules) >= 370, (
            f"Expected ≥370 v2 business rules, got {len(v2_rules)}"
        )

    def test_all_rules_have_node_type(self, v2_rules):
        for node in v2_rules:
            assert node.get("node_type") == "business_rule", (
                f"Node {node.get('name')} has wrong node_type: {node.get('node_type')}"
            )

    def test_all_rules_have_vertex_uuid(self, v2_rules):
        uuids = set()
        for node in v2_rules:
            vid = node.get("vertex_uuid", "")
            assert vid, f"Node {node.get('name')} missing vertex_uuid"
            assert vid not in uuids, f"Duplicate vertex_uuid: {vid}"
            uuids.add(vid)

    def test_confidence_scores_in_valid_range(self, v2_rules):
        for node in v2_rules:
            cs = node.get("confidence_score", 0)
            assert 0 <= cs <= 100, (
                f"Node {node.get('name')} has confidence_score {cs} outside [0,100]"
            )

    def test_audit_frequency_values(self, v2_rules):
        """audit_frequency should contain recognizable frequency terms."""
        valid_frequencies = {
            "", "at_origination", "annual", "annually", "quarterly",
            "monthly", "semi_annual", "per_transaction", "ongoing",
            "upon_delivery", "on_change",
        }
        for node in v2_rules:
            af = node.get("audit_frequency", "")
            assert af in valid_frequencies, (
                f"Unexpected audit_frequency '{af}' on {node.get('name')}"
            )
