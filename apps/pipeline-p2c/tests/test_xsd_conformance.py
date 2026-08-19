"""XSD conformance against the normative OMG schemas.

Opt-in, because the schemas are OMG documents that this repository does not
redistribute and because downloading them would make the default test run depend
on the network. Fetch them first, then run::

    python scripts/fetch_schemas.py --into schemas/omg
    python -m pytest tests/test_xsd_conformance.py --xsd-dir schemas/omg

The offline structural checks in :mod:`compilers.verify` cover what usually breaks;
this is the authority on what the standards actually accept.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from compilers.bpmn import compile_bpmn
from compilers.dmn import compile_dmn
from fixtures import all_fixtures
from policy_ir.enums import CompilerProfile
from validation import run_gate

PINNED = Path(__file__).resolve().parent.parent / "schemas" / "PINNED.json"

pytestmark = pytest.mark.xsd


@pytest.fixture(scope="module")
def pinned() -> dict:
    return json.loads(PINNED.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def validators(xsd_dir: Path, pinned: dict):
    etree = pytest.importorskip(
        "lxml.etree", reason="lxml is required for XSD validation"
    )
    built = {}
    for family in ("dmn", "bpmn"):
        schema_path = xsd_dir / pinned[family]["validate_with"]
        if not schema_path.exists():
            pytest.skip(f"{schema_path} is missing; run scripts/fetch_schemas.py")
        built[family] = etree.XMLSchema(etree.parse(str(schema_path)))
    return etree, built


def _assert_valid(etree, schema, xml: str, label: str) -> None:
    document = etree.fromstring(xml.encode("utf-8"))
    if not schema.validate(document):
        messages = "\n".join(
            f"line {entry.line}: {entry.message}" for entry in schema.error_log
        )
        pytest.fail(f"{label} is not schema-valid:\n{messages}")


@pytest.mark.parametrize(
    "name", ["eligibility_decision", "exception_clause", "fee_calculation", "notice_process"]
)
def test_emitted_dmn_validates_against_dmn_15(validators, name: str) -> None:
    etree, schemas = validators
    item = all_fixtures()[name]
    report = run_gate(item.ir, item.texts)
    artifact = compile_dmn(item.ir, report)
    if not artifact.emitted_ids:
        pytest.skip(f"{name} emits no decision")
    _assert_valid(etree, schemas["dmn"], artifact.xml, f"{name} DMN")


@pytest.mark.parametrize("profile", list(CompilerProfile))
def test_emitted_bpmn_validates_against_bpmn_202(validators, profile: CompilerProfile) -> None:
    etree, schemas = validators
    name = "notice_process" if profile is CompilerProfile.EXECUTABLE_SUBSET else "missing_actor_process"
    item = all_fixtures()[name]
    report = run_gate(item.ir, item.texts)
    artifact = compile_bpmn(item.ir, report, profile=profile)
    assert artifact.emitted_ids
    _assert_valid(etree, schemas["bpmn"], artifact.xml, f"{name} BPMN ({profile.value})")


def test_review_profile_dmn_is_also_schema_valid(validators) -> None:
    etree, schemas = validators
    item = all_fixtures()["numeric_drift"]
    report = run_gate(item.ir, item.texts)
    artifact = compile_dmn(item.ir, report, profile=CompilerProfile.REVIEW)
    assert artifact.emitted_ids
    _assert_valid(etree, schemas["dmn"], artifact.xml, "review DMN")


def test_pinned_schema_hashes_are_reproduced(xsd_dir: Path) -> None:
    """The bytes on disk must be the bytes the compiler was verified against."""
    import sys

    sys.path.insert(0, str(PINNED.parent.parent / "scripts"))
    from fetch_schemas import fetch

    assert fetch(xsd_dir, verify_only=True) == 0
