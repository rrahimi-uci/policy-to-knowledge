"""E2E tests for the Reference Resolution & Chunk API.

Tests verify that:
1. /api/reference/resolve correctly maps node references to document chunks
2. /api/reference/chunk serves the correct chunk content
3. The section codes in references match the resolved chunk titles
4. Each node's reference resolves to a chunk containing the same section code
"""

import re
import pytest


# ── Section code regex: e.g. B2-1.5-05, C1-2-02, E-3-23
SECTION_CODE_RE = re.compile(r"[A-Z]\d[\-\.\d]+")


class TestReferenceResolve:
    """Tests for GET /api/reference/resolve"""

    def test_missing_ref_returns_400(self, api):
        r = api.get("/api/reference/resolve", params={"graph_name": "fannie_mae_g"})
        assert r.status_code == 400
        assert "ref" in r.json().get("error", "").lower()

    def test_empty_ref_returns_400(self, api):
        r = api.get("/api/reference/resolve", params={"ref": "", "graph_name": "fannie_mae_g"})
        assert r.status_code == 400

    def test_valid_ref_returns_matches(self, api):
        """A known good reference should resolve to at least one match."""
        r = api.get("/api/reference/resolve", params={
            "ref": "B2-1.5-05",
            "graph_name": "fannie_mae_g",
        })
        assert r.status_code == 200
        data = r.json()
        assert "matches" in data
        assert "reference" in data
        assert data["reference"] == "B2-1.5-05"
        assert len(data["matches"]) >= 1

    def test_match_has_required_fields(self, api):
        r = api.get("/api/reference/resolve", params={
            "ref": "B2-1.5-05",
            "graph_name": "fannie_mae_g",
        })
        data = r.json()
        match = data["matches"][0]
        for key in ("title", "chunk_id", "path", "url"):
            assert key in match, f"Missing key: {key}"

    def test_match_url_points_to_chunk_endpoint(self, api):
        r = api.get("/api/reference/resolve", params={
            "ref": "B2-1.5-05",
            "graph_name": "fannie_mae_g",
        })
        match = r.json()["matches"][0]
        assert "/api/reference/chunk" in match["url"]
        assert "graph_name=" in match["url"]
        assert "path=" in match["url"]

    def test_unknown_ref_returns_empty_matches(self, api):
        r = api.get("/api/reference/resolve", params={
            "ref": "ZZZZZ-NONEXISTENT-99999",
            "graph_name": "fannie_mae_g",
        })
        assert r.status_code == 200
        assert r.json()["matches"] == []

    def test_invalid_graph_name_for_docs(self, api):
        """A graph with no docs_folder configured should 404."""
        # sample_guidelines_g may or may not have docs — use a truly invalid name
        r = api.get("/api/reference/resolve", params={
            "ref": "anything",
            "graph_name": "nonexistent_graph_g",
        })
        # Could be 404 (no docs folder) or 200 with empty matches depending on fallback
        assert r.status_code in (200, 404)

    def test_section_code_in_match_title(self, api):
        """When ref contains a section code, the best match title should contain the same code."""
        ref = "B2-1.5-05"
        r = api.get("/api/reference/resolve", params={
            "ref": ref,
            "graph_name": "fannie_mae_g",
        })
        data = r.json()
        assert len(data["matches"]) >= 1
        best = data["matches"][0]
        ref_codes = set(SECTION_CODE_RE.findall(ref))
        title_codes = set(SECTION_CODE_RE.findall(best["title"]))
        assert ref_codes & title_codes, (
            f"Section code mismatch: ref has {ref_codes} but "
            f"best match title '{best['title']}' has {title_codes}"
        )

    def test_chunk_id_in_ref_resolves_correctly(self, api):
        """If a reference embeds a chunk_id like FAMA_097, the resolved chunk_id should match."""
        r = api.get("/api/reference/resolve", params={
            "ref": "FAMA_097",
            "graph_name": "fannie_mae_g",
        })
        data = r.json()
        assert len(data["matches"]) >= 1
        assert data["matches"][0]["chunk_id"] == "FAMA_097"

    def test_at_most_5_matches(self, api):
        """Resolve should return at most 5 matches."""
        r = api.get("/api/reference/resolve", params={
            "ref": "B",
            "graph_name": "fannie_mae_g",
        })
        assert len(r.json()["matches"]) <= 5


class TestReferenceChunk:
    """Tests for GET /api/reference/chunk"""

    def _get_valid_chunk_path(self, api):
        """Helper: resolve a reference and return the path of the first match."""
        r = api.get("/api/reference/resolve", params={
            "ref": "B2-1.5-05",
            "graph_name": "fannie_mae_g",
        })
        matches = r.json().get("matches", [])
        assert matches, "Need at least one match to test chunk serving"
        return matches[0]["path"]

    def test_missing_path_returns_400(self, api):
        r = api.get("/api/reference/chunk", params={"graph_name": "fannie_mae_g"})
        assert r.status_code == 400
        assert "path" in r.json().get("error", "").lower()

    def test_valid_chunk_returns_html(self, api):
        path = self._get_valid_chunk_path(api)
        r = api.get("/api/reference/chunk", params={
            "graph_name": "fannie_mae_g",
            "path": path,
        })
        assert r.status_code == 200
        assert "text/html" in r.headers.get("Content-Type", "")
        assert "<html" in r.text.lower()

    def test_chunk_html_contains_content(self, api):
        """Chunk HTML should contain meaningful text, not just an empty page."""
        path = self._get_valid_chunk_path(api)
        r = api.get("/api/reference/chunk", params={
            "graph_name": "fannie_mae_g",
            "path": path,
        })
        assert len(r.text) > 200, "Chunk HTML seems too short to have meaningful content"

    def test_nonexistent_chunk_returns_404(self, api):
        r = api.get("/api/reference/chunk", params={
            "graph_name": "fannie_mae_g",
            "path": "DOESNOTEXIST/no-file.txt",
        })
        assert r.status_code == 404

    def test_path_traversal_blocked(self, api):
        """Attempting path traversal should be rejected."""
        r = api.get("/api/reference/chunk", params={
            "graph_name": "fannie_mae_g",
            "path": "../../etc/passwd",
        })
        assert r.status_code in (403, 404)

    def test_theme_parameter_accepted(self, api):
        path = self._get_valid_chunk_path(api)
        for theme in ("light", "dark"):
            r = api.get("/api/reference/chunk", params={
                "graph_name": "fannie_mae_g",
                "path": path,
                "theme": theme,
            })
            assert r.status_code == 200


class TestNodeReferenceIntegrity:
    """Critical tests: every node's reference must resolve to the correct document chunk.

    These tests catch the bug where clicking a node link opens the wrong document chunk.
    For each node with a reference, we verify that:
    1. The reference resolves to at least one chunk match
    2. The section code in the reference matches the section code in the chunk title
    3. The chunk URL is valid and serves HTML content

    Coverage: vertices across all 3 graphs.
    """

    # ── Graph-level expected counts & thresholds ──────────────────────────
    GRAPH_EXPECTATIONS = {
        "fannie_mae_g":        {"min_nodes": 400, "min_refs": 380, "resolve_pct": 95},
        "sample_guidelines_g":  {"min_nodes": 350, "min_refs": 320, "resolve_pct": 85},
        "overlays_g":          {"min_nodes": 60,  "min_refs": 40,  "resolve_pct": 75},
    }

    ALL_GRAPHS = list(GRAPH_EXPECTATIONS.keys())

    # ── Fixtures ──────────────────────────────────────────────────────────
    @pytest.fixture(scope="class")
    def all_graph_nodes(self, api):
        """Load every node from every graph once.  Returns {graph: [nodes]}."""
        result = {}
        for graph in self.ALL_GRAPHS:
            r = api.get("/api/graph", params={"graph_name": graph})
            assert r.status_code == 200, f"Failed to load graph {graph}"
            result[graph] = r.json()["nodes"]
        return result

    @pytest.fixture(scope="class")
    def all_graph_refs(self, all_graph_nodes):
        """Subset of nodes that have a non-empty reference.  {graph: [nodes]}."""
        result = {}
        for graph, nodes in all_graph_nodes.items():
            result[graph] = [
                n for n in nodes
                if n.get("reference") and n["reference"].lower() not in ("not provided", "n/a")
            ]
        return result

    # ── 1. Sanity: node & reference counts match expectations ─────────────
    @pytest.mark.parametrize("graph", ALL_GRAPHS)
    def test_node_count_above_minimum(self, all_graph_nodes, graph):
        expected = self.GRAPH_EXPECTATIONS[graph]["min_nodes"]
        actual = len(all_graph_nodes[graph])
        assert actual >= expected, (
            f"{graph}: expected >= {expected} nodes, got {actual}"
        )

    @pytest.mark.parametrize("graph", ALL_GRAPHS)
    def test_reference_count_above_minimum(self, all_graph_refs, graph):
        expected = self.GRAPH_EXPECTATIONS[graph]["min_refs"]
        actual = len(all_graph_refs[graph])
        assert actual >= expected, (
            f"{graph}: expected >= {expected} nodes with references, got {actual}"
        )

    # ── 2. All-node reference resolution rate per graph ───────────────────
    @pytest.mark.parametrize("graph", ALL_GRAPHS)
    def test_reference_resolve_rate(self, api, all_graph_refs, graph):
        """Every reference should resolve; those that don't must stay under threshold.

        Unresolvable references are typically references to external docs not in
        the knowledge-base corpus.  Each graph has its own acceptable threshold.
        """
        nodes = all_graph_refs[graph]
        if not nodes:
            pytest.skip(f"No references in {graph}")

        resolved = 0
        failures = []
        for node in nodes:
            ref = node["reference"]
            r = api.get("/api/reference/resolve", params={
                "ref": ref,
                "graph_name": graph,
            })
            if r.status_code == 200 and r.json().get("matches"):
                resolved += 1
            else:
                failures.append(
                    f"  Node {node['id']} ({node.get('name', '')[:40]}): "
                    f"ref='{ref[:80]}'"
                )

        rate = resolved / len(nodes) * 100
        threshold = self.GRAPH_EXPECTATIONS[graph]["resolve_pct"]
        assert rate >= threshold, (
            f"{graph}: resolve rate {rate:.1f}% < {threshold}% threshold.  "
            f"{len(failures)} unresolved:\n" + "\n".join(failures[:10])
        )

    # ── 3. Section-code mismatch detection (the critical wrong-chunk bug) ─
    @pytest.mark.parametrize("graph", ALL_GRAPHS)
    def test_section_code_match(self, api, all_graph_refs, graph):
        """When a reference and its best match both contain section codes,
        the codes MUST overlap.  A mismatch means the user would open the
        wrong document chunk.
        """
        mismatches = []
        for node in all_graph_refs[graph]:
            ref = node["reference"]
            ref_codes = set(SECTION_CODE_RE.findall(ref))
            if not ref_codes:
                continue

            r = api.get("/api/reference/resolve", params={
                "ref": ref,
                "graph_name": graph,
            })
            if r.status_code != 200:
                continue
            matches = r.json().get("matches", [])
            if not matches:
                continue

            best = matches[0]
            title_codes = set(SECTION_CODE_RE.findall(best["title"]))
            chunk_id_codes = set(SECTION_CODE_RE.findall(best.get("chunk_id", "")))
            all_target_codes = title_codes | chunk_id_codes
            if all_target_codes and not (ref_codes & all_target_codes):
                mismatches.append(
                    f"  Node {node['id']} ({node.get('name', '')[:40]}): "
                    f"ref codes {ref_codes} != chunk codes {all_target_codes} "
                    f"(chunk: {best['chunk_id']} '{best['title'][:50]}')"
                )

        assert not mismatches, (
            f"{graph}: {len(mismatches)} section code mismatches (wrong chunk):\n"
            + "\n".join(mismatches[:15])
        )

    # ── 4. Chunk-ID matching: refs that embed _NNN should map correctly ───
    @pytest.mark.parametrize("graph", ALL_GRAPHS)
    def test_chunk_id_embedded_in_ref(self, api, all_graph_refs, graph):
        """When a reference embeds a chunk-id pattern like 'FAMA_097' or '2006_017',
        the resolved chunk_id should contain that same pattern.
        """
        chunk_id_re = re.compile(r"(\w+_\d{3})")
        mismatches = []
        for node in all_graph_refs[graph]:
            ref = node["reference"]
            ref_ids = set(chunk_id_re.findall(ref))
            if not ref_ids:
                continue

            r = api.get("/api/reference/resolve", params={
                "ref": ref,
                "graph_name": graph,
            })
            if r.status_code != 200:
                continue
            matches = r.json().get("matches", [])
            if not matches:
                continue

            best_chunk = matches[0]["chunk_id"]
            best_ids = set(chunk_id_re.findall(best_chunk))
            # At least one chunk-id from the ref should appear in the resolved chunk_id
            if not (ref_ids & best_ids):
                # Looser check: any ref_id is a substring of best_chunk
                if not any(rid in best_chunk for rid in ref_ids):
                    mismatches.append(
                        f"  Node {node['id']}: ref_ids {ref_ids} not in "
                        f"chunk_id '{best_chunk}'"
                    )

        # Threshold: at most 5% mismatch (some refs embed IDs for related chunks)
        if not mismatches:
            return
        total_with_ids = sum(
            1 for n in all_graph_refs[graph]
            if chunk_id_re.findall(n["reference"])
        )
        assert len(mismatches) / total_with_ids < 0.05, (
            f"{graph}: {len(mismatches)}/{total_with_ids} chunk-id mismatches:\n"
            + "\n".join(mismatches[:10])
        )

    # ── 5. Chunk URLs serve valid HTML (spot-check per graph) ─────────────
    @pytest.mark.parametrize("graph", ALL_GRAPHS)
    def test_chunk_urls_serve_html(self, api, all_graph_refs, graph):
        """For each graph, spot-check up to 10 unique chunk URLs to ensure
        they return 200 with text/html content.
        """
        checked = 0
        failures = []
        seen_urls = set()

        for node in all_graph_refs[graph]:
            ref = node["reference"]
            r = api.get("/api/reference/resolve", params={
                "ref": ref,
                "graph_name": graph,
            })
            if r.status_code != 200:
                continue
            matches = r.json().get("matches", [])
            if not matches:
                continue

            url = matches[0]["url"]
            if url in seen_urls:
                continue
            seen_urls.add(url)

            chunk_r = api.get(url)
            if chunk_r.status_code != 200 or "text/html" not in chunk_r.headers.get("Content-Type", ""):
                failures.append(
                    f"  Node {node['id']}: URL returned {chunk_r.status_code}, "
                    f"Content-Type={chunk_r.headers.get('Content-Type', 'none')}"
                )
            checked += 1
            if checked >= 10:
                break

        assert checked > 0, f"No chunk URLs checked for {graph}"
        assert not failures, (
            f"{graph}: {len(failures)} chunk URLs failed:\n" + "\n".join(failures)
        )

    # ── 6. Total vertex count across all graphs ──────────────────────────
    def test_total_vertex_count(self, all_graph_nodes):
        """All graphs combined must have >= 1200 vertices (currently 1260)."""
        total = sum(len(nodes) for nodes in all_graph_nodes.values())
        assert total >= 1200, f"Expected >= 1200 total vertices, got {total}"

    # ── 7. Per-graph round-trip: node → resolve → chunk → content ────────
    @pytest.mark.parametrize("graph", ALL_GRAPHS)
    def test_round_trip_node_to_chunk_content(self, api, all_graph_refs, graph):
        """Full round-trip for the first resolvable node in each graph:
        get reference → resolve to chunk → fetch chunk HTML → verify content
        relates to the node.
        """
        for node in all_graph_refs[graph]:
            ref = node["reference"]
            r = api.get("/api/reference/resolve", params={
                "ref": ref,
                "graph_name": graph,
            })
            if r.status_code != 200:
                continue
            matches = r.json().get("matches", [])
            if not matches:
                continue

            # Fetch chunk HTML
            chunk_r = api.get(matches[0]["url"])
            assert chunk_r.status_code == 200, (
                f"{graph}: chunk URL failed for ref '{ref[:60]}'"
            )
            chunk_html = chunk_r.text.lower()
            assert len(chunk_html) > 100, (
                f"{graph}: chunk HTML too short ({len(chunk_html)} chars) for ref '{ref[:60]}'"
            )

            # Verify content relevance: at least one section code or significant
            # word from the node name appears in the chunk
            ref_codes = SECTION_CODE_RE.findall(ref)
            node_name = node.get("name", "")
            found_code = any(code.lower() in chunk_html for code in ref_codes)
            found_name = any(
                w.lower() in chunk_html
                for w in node_name.split() if len(w) > 4
            )
            assert found_code or found_name, (
                f"{graph}: chunk for ref '{ref[:60]}' has no section code "
                f"{ref_codes} or word from name '{node_name[:40]}'"
            )
            return  # One successful round-trip per graph is sufficient

        pytest.skip(f"No resolvable references in {graph}")

    # ── 8. Vertex detail reference resolves (any graph) ──────────────────
    def test_vertex_detail_reference_resolves(self, api, any_node_id):
        """The reference on a vertex detail view should resolve to a valid chunk."""
        r = api.get(f"/api/vertex/{any_node_id}", params={"graph_name": "fannie_mae_g"})
        if r.status_code != 200:
            pytest.skip("Could not fetch vertex detail")

        ref = r.json().get("reference", "")
        if not ref:
            pytest.skip("Node has no reference")

        resolve_r = api.get("/api/reference/resolve", params={
            "ref": ref,
            "graph_name": "fannie_mae_g",
        })
        assert resolve_r.status_code == 200
        matches = resolve_r.json().get("matches", [])
        assert len(matches) >= 1, (
            f"Reference '{ref}' on vertex {any_node_id} resolved to 0 matches"
        )

    # ── 9. No duplicate chunk-id mappings (same ref → diff chunks) ───────
    @pytest.mark.parametrize("graph", ALL_GRAPHS)
    def test_no_conflicting_resolutions(self, api, all_graph_refs, graph):
        """If two nodes share the exact same reference string, they must
        resolve to the same best-match chunk.  Otherwise one of them is wrong.
        """
        ref_to_chunk = {}
        conflicts = []
        for node in all_graph_refs[graph]:
            ref = node["reference"]
            r = api.get("/api/reference/resolve", params={
                "ref": ref,
                "graph_name": graph,
            })
            if r.status_code != 200:
                continue
            matches = r.json().get("matches", [])
            if not matches:
                continue

            best_chunk = matches[0]["chunk_id"]
            if ref in ref_to_chunk:
                if ref_to_chunk[ref] != best_chunk:
                    conflicts.append(
                        f"  ref='{ref[:60]}': node {node['id']} → "
                        f"'{best_chunk}' vs earlier → '{ref_to_chunk[ref]}'"
                    )
            else:
                ref_to_chunk[ref] = best_chunk

        assert not conflicts, (
            f"{graph}: {len(conflicts)} conflicting chunk resolutions:\n"
            + "\n".join(conflicts[:10])
        )
