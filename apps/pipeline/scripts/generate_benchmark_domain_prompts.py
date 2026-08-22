#!/usr/bin/env python3
"""Generate the four benchmark-corpus domain prompt packs.

The packs under `domain-prompts/{commercial_contracts,nda_confidentiality,
privacy_policy,mobile_app_privacy}/` are produced by this script rather than
hand-authored, so that 4 domains x 13 templates stay structurally consistent and
satisfy every field contract in `tests/test_data_contracts.py`. The generated
`.txt` files are committed and are what `PromptManager` reads at runtime; this
script is the source of truth when they need to change.

    python3 scripts/generate_benchmark_domain_prompts.py           # write packs
    python3 scripts/generate_benchmark_domain_prompts.py --check   # verify only

Each pack ships 13 templates, not the conventional 11. Agents 2 and 3 request
`entity_extraction_compact` and `business_rules_extraction_compact`; without a
domain override for those two, the shared copies apply and they instruct the
model to "prefer concrete mortgage concepts" regardless of the active domain.
The non-compact `entity_extraction`/`business_rules_extraction` templates are
kept because the contract tests require them in every domain directory.

Profile text is injected with `string.Template` ($name), so the `{}` braces in
the prompt bodies are left exactly as written: `{{`/`}}` survive `str.format`
as literal JSON braces, and single-brace `{name}` stays a runtime placeholder.
"""
from __future__ import annotations

import argparse
import re
import sys
import textwrap
from dataclasses import dataclass, field
from pathlib import Path
from string import Template

ROOT = Path(__file__).resolve().parent.parent
DOMAIN_PROMPTS = ROOT / "domain-prompts"

# Placeholders each agent actually passes, used by --check to prove every
# generated template survives str.format() with the real call signature.
RUNTIME_KWARGS = {
    "document_structure_analysis": {"content": "X"},
    "entity_extraction_compact": {"sample_content": "X", "max_entities": 8, "max_relationships": 6},
    "entity_extraction": {"sample_content": "X"},
    "business_rules_extraction_compact": {
        "entity_context": "X", "sample_content": "X", "batch_num": 1, "rules_per_batch": 10,
    },
    "business_rules_extraction": {
        "entity_context": "X", "sample_content": "X", "batch_num": 1, "rules_per_batch": 10,
    },
    "entity_refinement": {"entities_json": "X", "iteration_number": 1},
    "entity_resolution": {"entities_by_source": "X", "source_documents": "X"},
    "rule_resolution": {"rules_by_source": "X", "source_documents": "X"},
    "rule_deduplication": {"rules_json": "X", "total_rules": 10},
    "dependency_analysis": {"rules_json": "X", "total_rules": 10},
    "rule_matcher": {"g1_name": "A", "g2_name": "B", "rule_a": "X", "rule_b": "Y"},
    "rule_matcher_batch": {"g1_name": "A", "g2_name": "B", "num_pairs": 3, "rule_pairs_json": "X"},
    "validation_report": {"metrics_json": "X"},
}

TEMPLATE_NAMES = list(RUNTIME_KWARGS)


@dataclass
class Profile:
    """Everything that makes one domain pack different from the others."""

    key: str
    title: str
    benchmark: str
    persona: str
    genre: str
    corpus_note: str
    entity_types: list[tuple[str, str, str, str]]  # NAME, definition, attributes, example
    relationships: list[tuple[str, str, str, str]]  # NAME, source, target, definition
    rule_types: list[str]
    rule_type_notes: str
    colors: dict[str, str]
    priority_filters: list[str]
    scope_fields: list[str]
    segmentation: str
    dedup_rules: str
    dependency_examples: str
    matcher_axes: str
    validation_criteria: str
    worked_rule: str
    language_note: str = ""
    extra_extraction_note: str = ""

    def entity_block(self) -> str:
        lines = []
        for name, definition, attrs, example in self.entity_types:
            lines.append(f"- {name} — {definition}\n  attributes: {attrs}\n  example: {example}")
        return "\n".join(lines)

    def relationship_block(self) -> str:
        return "\n".join(
            f"- {name} ({src} → {tgt}) — {definition}"
            for name, src, tgt, definition in self.relationships
        )

    def rule_type_list(self) -> str:
        return ", ".join(self.rule_types)

    def rule_type_enum(self) -> str:
        """Pipe-separated form, for JSON enum positions where a comma list reads
        like a literal value rather than a choice."""
        return "|".join(self.rule_types)

    def scope_block(self) -> str:
        return ", ".join(f"{f} (array)" for f in self.scope_fields)

    def mapping(self) -> dict[str, str]:
        return {
            "key": self.key,
            "title": self.title,
            "benchmark": self.benchmark,
            "persona": self.persona,
            "genre": self.genre,
            "corpus_note": self.corpus_note,
            "entities": self.entity_block(),
            "relationships": self.relationship_block(),
            "rule_types": self.rule_type_list(),
            "rule_type_notes": self.rule_type_notes,
            "primary_entity": self.entity_types[0][0],
            "primary_relationship": self.relationships[0][0],
            "scope_fields": self.scope_block(),
            "segmentation": self.segmentation,
            "dedup_rules": self.dedup_rules,
            "dependency_examples": self.dependency_examples,
            "matcher_axes": self.matcher_axes,
            "validation_criteria": self.validation_criteria,
            "worked_rule": self.worked_rule,
            "language_note": self.language_note,
            "extra_extraction_note": self.extra_extraction_note,
            "rule_types_enum": self.rule_type_enum(),
        }


# ═══════════════════════════════════════════════════════════════════════════
# Domain profiles — one per benchmark corpus
# ═══════════════════════════════════════════════════════════════════════════

COMMERCIAL_CONTRACTS = Profile(
    key="commercial_contracts",
    title="Commercial Contracts",
    benchmark="CUAD v1 (510 commercial agreements, 41 expert-labelled clause categories)",
    persona="an expert commercial contracts attorney specialising in transactional "
            "contract review for mergers, acquisitions, and investment diligence",
    genre="negotiated commercial agreements — licence, distribution, supply, "
          "co-branding, endorsement, franchise, hosting, outsourcing, joint venture, "
          "development, maintenance, service, and strategic alliance agreements",
    corpus_note="Clause categories a reviewing attorney looks for include governing law, "
                "exclusivity, non-compete, no-solicit, most-favoured-nation, change of "
                "control, anti-assignment, revenue or profit sharing, minimum commitment, "
                "IP ownership assignment, licence grant and its transferability, source code "
                "escrow, audit rights, liability caps and uncapped liability, liquidated "
                "damages, warranty duration, insurance, and third-party beneficiary rights.",
    entity_types=[
        ("CONTRACTING_PARTY", "A named legal person bound by the agreement",
         "legal_name, role, jurisdiction_of_organisation, notice_address, affiliate_scope",
         "I-ESCROW, INC., a California corporation, as service provider"),
        ("AGREEMENT", "The contract instrument itself and its lifecycle dates",
         "document_name, agreement_date, effective_date, expiration_date, renewal_term",
         "Co-Branding and Advertising Agreement dated June 21, 1999"),
        ("CLAUSE", "A numbered or captioned provision carrying one or more obligations",
         "clause_number, caption, category, governing_section, cross_references",
         "Section 8.2 Limitation of Liability"),
        ("LICENCE_GRANT", "A conveyance of rights in intellectual property",
         "licensed_property, exclusivity, transferability, territory, duration",
         "Non-exclusive, non-transferable licence to the Licensor marks"),
        ("CONSIDERATION", "Money or value flowing between the parties",
         "amount, currency, payment_trigger, revenue_share_percentage, minimum_commitment",
         "15% of net revenue, payable quarterly"),
        ("TERRITORY", "The geographic or market scope in which rights apply",
         "region, exclusivity, carve_outs, channel, field_of_use",
         "United States and Canada, excluding government channel"),
        ("TERMINATION_EVENT", "A condition that ends or may end the agreement",
         "trigger, notice_period, cure_period, convenience_right, survival_scope",
         "Termination for convenience on 90 days written notice"),
        ("LIABILITY_LIMIT", "A cap, carve-out, or exclusion on damages",
         "cap_amount, cap_basis, carve_outs, uncapped_categories, liquidated_damages",
         "Liability capped at fees paid in the preceding 12 months"),
    ],
    relationships=[
        ("PARTY_BOUND_BY_CLAUSE", "CONTRACTING_PARTY", "CLAUSE",
         "Identifies which party bears the obligation or restriction in a clause"),
        ("AGREEMENT_CONTAINS_CLAUSE", "AGREEMENT", "CLAUSE",
         "Structural containment of a provision within the instrument"),
        ("GRANT_COVERS_TERRITORY", "LICENCE_GRANT", "TERRITORY",
         "Scopes a licence to a region, channel, or field of use"),
        ("CLAUSE_LIMITS_LIABILITY", "CLAUSE", "LIABILITY_LIMIT",
         "Ties a liability cap or carve-out to the provision that creates it"),
    ],
    rule_types=["obligation", "restriction", "license_grant", "ip_assignment", "termination",
                "financial_term", "liability", "renewal", "governance", "exception"],
    rule_type_notes=(
        "obligation = an affirmative duty a party must perform; restriction = a negative "
        "covenant such as non-compete, exclusivity, no-solicit, or anti-assignment; "
        "license_grant = conveyance of IP rights including scope and transferability; "
        "ip_assignment = ownership transfer or joint ownership of IP; termination = "
        "termination, renewal-notice, and change-of-control triggers; financial_term = "
        "pricing, revenue share, minimum commitment, volume limits; liability = caps, "
        "uncapped categories, liquidated damages, indemnity, insurance; renewal = auto-renewal "
        "and notice periods; governance = governing law, venue, audit rights, third-party "
        "beneficiary; exception = an express carve-out from another rule."
    ),
    colors={"obligation": "#3b82f6", "restriction": "#ef4444", "license_grant": "#06b6d4",
            "ip_assignment": "#8b5cf6", "termination": "#f97316", "financial_term": "#10b981",
            "liability": "#dc2626", "renewal": "#f59e0b", "governance": "#6366f1",
            "exception": "#ec4899"},
    priority_filters=["obligation", "restriction", "liability"],
    scope_fields=["contract_types", "party_roles", "territories"],
    segmentation=(
        "Commercial agreements are segmented by their own numbering. Prefer, in order: "
        "an ARTICLE/SECTION hierarchy (Article V, Section 5.1, 5.1(a)); captioned provisions "
        "in bold or title case (\"Limitation of Liability\", \"Governing Law\"); recital blocks "
        "beginning WHEREAS; the signature block; and appended Exhibits, Schedules, and Annexes. "
        "Keep a full clause together with its sub-clauses — splitting 5.1 from 5.1(a) severs a "
        "condition from its exception. Treat each Exhibit or Schedule as its own top-level "
        "section, since they frequently carry pricing and service-level terms."
    ),
    dedup_rules=(
        "Two contract rules are duplicates only when they bind the same party role to the same "
        "obligation on the same trigger. Keep them separate when any of these differ: the "
        "party bearing the duty (Licensor vs Licensee duties are not interchangeable), the "
        "notice or cure period in days, a monetary cap or percentage, the territory or field "
        "of use, or whether the provision is mutual or one-way. Reciprocal obligations that "
        "mirror each other across the two parties are NOT duplicates."
    ),
    dependency_examples=(
        "- A termination-for-convenience right is a prerequisite for post-termination service "
        "obligations.\n"
        "- A licence grant is a prerequisite for any non-transferability restriction on it.\n"
        "- A liability cap and an uncapped-liability carve-out are contradictory on their face "
        "and must be linked so the carve-out is read as an override.\n"
        "- Renewal-notice deadlines are sequential with expiration dates.\n"
        "- Audit rights are complementary to revenue-share reporting duties.\n"
        "- An express exception clause overrides the general restriction it names."
    ),
    matcher_axes=(
        "party role bearing the duty, the triggering event, notice and cure periods in days, "
        "monetary caps and percentages, exclusivity and transferability flags, territory, and "
        "whether the obligation is mutual or unilateral"
    ),
    validation_criteria=(
        "A high-quality contract rule names the bound party by role, quotes the operative "
        "clause verbatim, carries the exact numeric term (days, percentage, currency amount) "
        "where the clause states one, and records any express carve-out as an exception rather "
        "than folding it into the description."
    ),
    worked_rule=(
        "\"Licensee May Not Assign the Agreement Without Prior Written Consent Upon Change of "
        "Control\" — rule_type restriction, bound to CONTRACTING_PARTY in the Licensee role, "
        "triggered by a change of control, with the consent requirement as the consequence and "
        "the permitted-affiliate transfer as an explicit exception."
    ),
)

NDA_CONFIDENTIALITY = Profile(
    key="nda_confidentiality",
    title="NDA and Confidentiality",
    benchmark="ContractNLI (607 NDAs annotated against 17 confidentiality propositions)",
    persona="an expert confidentiality counsel who reviews non-disclosure agreements "
            "for scope of protected information and the limits of permitted use",
    genre="non-disclosure, confidentiality, and secrecy agreements — mutual and one-way, "
          "standalone and as annexes to procurement, employment, or diligence processes",
    corpus_note="The propositions a reviewer tests an NDA against include: whether all "
                "confidential information must be expressly identified or marked; whether "
                "verbally conveyed information is covered; whether the definition is limited "
                "to technical information; whether the Receiving Party may share with "
                "employees, or with third-party consultants, agents, and professional "
                "advisors; whether use is limited to a stated purpose; whether reverse "
                "engineering is barred; whether independently developed or third-party-sourced "
                "information is excluded; whether copies may be made; whether the Receiving "
                "Party must notify on legally compelled disclosure; whether information must "
                "be returned or destroyed on termination and whether any copy may be retained; "
                "whether the existence of the agreement itself is confidential; whether any "
                "licence or right in the information is granted; whether representatives may "
                "be solicited; and which obligations survive termination.",
    entity_types=[
        ("DISCLOSING_PARTY", "The party that supplies protected information",
         "legal_name, role, affiliate_scope, representative_classes, notice_address",
         "The Disclosing Party and its wholly owned subsidiaries"),
        ("RECEIVING_PARTY", "The party bound to protect information it receives",
         "legal_name, role, permitted_recipients, flow_down_duty, notice_address",
         "The Receiving Party and its professional advisors"),
        ("CONFIDENTIAL_INFORMATION", "The protected subject matter and its definition boundary",
         "information_classes, marking_requirement, oral_disclosure_treatment, "
         "technical_only_flag, exclusions",
         "Technical and commercial information, whether or not marked confidential"),
        ("PERMITTED_PURPOSE", "The stated purpose to which use of the information is limited",
         "purpose_statement, evaluation_scope, prohibited_uses, duration, project_reference",
         "Solely to evaluate a potential business relationship"),
        ("PERMITTED_RECIPIENT", "A class of person to whom onward disclosure is allowed",
         "recipient_class, need_to_know_test, flow_down_obligation, notification_duty, "
         "liability_for_breach",
         "Employees, consultants, agents, and professional advisors on a need-to-know basis"),
        ("DISCLOSURE_EXCEPTION", "A carve-out permitting or excusing disclosure",
         "exception_basis, notice_obligation, protective_order_duty, scope_limit, evidence_standard",
         "Disclosure compelled by law, regulation, or judicial process"),
        ("RETURN_DESTRUCTION_DUTY", "The obligation to give back or destroy information",
         "trigger, deadline_days, retention_carve_out, certification_requirement, backup_exception",
         "Return or destroy within 30 days of written request"),
        ("SURVIVAL_TERM", "The period obligations continue after the agreement ends",
         "duration, surviving_obligations, perpetual_categories, termination_trigger, tail_period",
         "Confidentiality obligations survive for 5 years after termination"),
    ],
    relationships=[
        ("RECEIVING_PARTY_PROTECTS_INFORMATION", "RECEIVING_PARTY", "CONFIDENTIAL_INFORMATION",
         "The core duty of care and non-disclosure over protected material"),
        ("INFORMATION_LIMITED_TO_PURPOSE", "CONFIDENTIAL_INFORMATION", "PERMITTED_PURPOSE",
         "Constrains use of the information to the stated purpose"),
        ("DISCLOSURE_ALLOWED_TO_RECIPIENT", "RECEIVING_PARTY", "PERMITTED_RECIPIENT",
         "Authorises onward disclosure to a defined class, usually with flow-down duties"),
        ("EXCEPTION_RELEASES_DUTY", "DISCLOSURE_EXCEPTION", "RECEIVING_PARTY",
         "Excuses an otherwise prohibited disclosure, often with a notice condition"),
    ],
    rule_types=["confidentiality_scope", "permitted_use", "permitted_disclosure",
                "disclosure_exception", "notification_duty", "return_destruction",
                "survival", "non_solicitation", "no_license", "marking_requirement"],
    rule_type_notes=(
        "confidentiality_scope = what counts as Confidential Information, including oral, "
        "technical-only, and express exclusions; permitted_use = the purpose limitation and "
        "bars such as no reverse engineering; permitted_disclosure = onward sharing with "
        "employees, affiliates, or third-party advisors; disclosure_exception = legally "
        "compelled, publicly available, independently developed, or third-party-sourced "
        "carve-outs; notification_duty = the obligation to notify before or after a compelled "
        "disclosure; return_destruction = return, destroy, certify, and any retention "
        "carve-out; survival = which obligations outlast termination and for how long; "
        "non_solicitation = restrictions on soliciting the other party's representatives; "
        "no_license = express statement that no right, licence, or interest is granted; "
        "marking_requirement = whether information must be identified or labelled to qualify."
    ),
    colors={"confidentiality_scope": "#3b82f6", "permitted_use": "#10b981",
            "permitted_disclosure": "#06b6d4", "disclosure_exception": "#f97316",
            "notification_duty": "#f59e0b", "return_destruction": "#dc2626",
            "survival": "#8b5cf6", "non_solicitation": "#ef4444",
            "no_license": "#6366f1", "marking_requirement": "#ec4899"},
    priority_filters=["confidentiality_scope", "permitted_use", "disclosure_exception"],
    scope_fields=["agreement_directions", "recipient_classes", "information_classes"],
    segmentation=(
        "NDAs are short and densely numbered. Segment on numbered clauses (1., 1.1, (a)), on "
        "captioned provisions (\"Definition of Confidential Information\", \"Exclusions\", "
        "\"Term and Termination\", \"Return of Materials\"), on the recital or preamble block, "
        "and on the signature block. Never split a definition from its enumerated exclusions, "
        "and never split a disclosure permission from the conditions attached to it — the "
        "conditions are what distinguish a permission from a prohibition."
    ),
    dedup_rules=(
        "NDA obligations look alike because the vocabulary is formulaic. Two rules are "
        "duplicates only when they bind the same party in the same direction to the same duty "
        "with the same trigger. Keep separate: mutual versus one-way statements of the same "
        "duty; a permission for employees versus one for third-party advisors; a return "
        "obligation versus a destruction obligation where the text offers a choice; and any "
        "two rules whose survival periods or notice deadlines differ in days or years."
    ),
    dependency_examples=(
        "- A definition of Confidential Information is a prerequisite for every use and "
        "disclosure restriction that references it.\n"
        "- A notification duty is conditional on a compelled-disclosure exception being "
        "triggered.\n"
        "- An express exclusion for independently developed information overrides the general "
        "confidentiality scope.\n"
        "- Return and destruction duties are sequential with termination.\n"
        "- A retention carve-out for archival copies is contradictory with an unqualified "
        "destruction duty and must be linked.\n"
        "- Flow-down obligations on permitted recipients are complementary to the primary "
        "non-disclosure duty, and a marking requirement acts as a validation gate on scope."
    ),
    matcher_axes=(
        "which party bears the duty and whether the agreement is mutual, the class of permitted "
        "recipient, the purpose limitation, notice deadlines in days, survival period in years, "
        "and whether a carve-out is present for compelled disclosure, public information, "
        "independent development, or third-party receipt"
    ),
    validation_criteria=(
        "A high-quality NDA rule states the direction of the duty (which party owes it to "
        "whom), quotes the operative sentence, and separates the permission from its conditions "
        "— a rule that says information may be shared with advisors without capturing the "
        "need-to-know test and the flow-down duty is incomplete."
    ),
    worked_rule=(
        "\"Receiving Party Must Notify Disclosing Party Before Disclosing Confidential "
        "Information Compelled by Judicial Process\" — rule_type notification_duty, bound to "
        "RECEIVING_PARTY, conditioned on a subpoena or court order, with the consequence of "
        "prior written notice and cooperation in seeking a protective order, and an exception "
        "where notice is itself prohibited by law."
    ),
)

PRIVACY_POLICY = Profile(
    key="privacy_policy",
    title="Website Privacy Policy",
    benchmark="OPP-115 (115 website privacy policies, 23k annotated data practices in 10 categories)",
    persona="an expert privacy analyst who reads website privacy policies and reduces them "
            "to the concrete data practices they disclose",
    genre="consumer-facing website privacy policies and notices",
    corpus_note="The data-practice categories an analyst annotates are: First Party "
                "Collection/Use, Third Party Sharing/Collection, User Choice/Control, "
                "User Access/Edit/Deletion, Data Retention, Data Security, Policy Change, "
                "Do Not Track, and International and Specific Audiences. Every practice is "
                "further characterised by what information is collected, how and why it is "
                "collected, who it is shared with, and what choice the user is given.",
    entity_types=[
        ("FIRST_PARTY", "The operator of the site that collects the data",
         "operator_name, service_scope, contact_channel, jurisdiction, affiliate_scope",
         "The website operator and its corporate affiliates"),
        ("USER", "The individual whose information is collected",
         "user_category, account_status, age_bracket, geographic_scope, consent_state",
         "Registered users and unauthenticated visitors"),
        ("INFORMATION_TYPE", "A category of collected data",
         "data_category, identifiability, sensitivity, source, optional_flag",
         "Contact information, cookies and tracking identifiers, location"),
        ("COLLECTION_PRACTICE", "A described act of gathering information",
         "collection_mode, collection_process, purpose, trigger, disclosure_position",
         "Collected automatically via cookies when a page is loaded"),
        ("THIRD_PARTY", "An external recipient of shared information",
         "recipient_class, sharing_purpose, named_entity, onward_transfer, opt_out_available",
         "Advertising networks and analytics providers"),
        ("USER_CHOICE", "A control the policy offers over a practice",
         "choice_type, choice_scope, mechanism, default_state, effect_of_refusal",
         "Opt-out of targeted advertising via a preference centre"),
        ("RETENTION_PERIOD", "How long information is kept and on what basis",
         "duration, retention_purpose, deletion_trigger, aggregation_state, legal_hold",
         "Retained until the account is closed plus 90 days"),
        ("SECURITY_MEASURE", "A stated safeguard over collected information",
         "measure_type, scope, standard_referenced, breach_notification, access_control",
         "Encryption in transit and at rest"),
    ],
    relationships=[
        ("FIRST_PARTY_COLLECTS_INFORMATION", "FIRST_PARTY", "INFORMATION_TYPE",
         "The core first-party collection practice and its stated purpose"),
        ("INFORMATION_SHARED_WITH_THIRD_PARTY", "INFORMATION_TYPE", "THIRD_PARTY",
         "Onward disclosure of a data category to an external recipient"),
        ("USER_EXERCISES_CHOICE", "USER", "USER_CHOICE",
         "The control a user is offered over a collection or sharing practice"),
        ("INFORMATION_SUBJECT_TO_RETENTION", "INFORMATION_TYPE", "RETENTION_PERIOD",
         "Binds a data category to how long it is kept and when it is deleted"),
    ],
    rule_types=["collection", "sharing", "user_choice", "access_rights", "retention",
                "security", "policy_change", "do_not_track", "audience_scope",
                "purpose_limitation"],
    rule_type_notes=(
        "collection = first-party gathering of data, including what, how, and why; sharing = "
        "third-party disclosure or third-party collection on the site; user_choice = opt-in, "
        "opt-out, and control mechanisms; access_rights = the user's ability to view, edit, or "
        "delete their data; retention = how long data is kept and deletion triggers; security = "
        "stated safeguards; policy_change = how changes are announced and what notice is given; "
        "do_not_track = treatment of DNT browser signals; audience_scope = practices specific "
        "to children, to a jurisdiction, or to international transfers; purpose_limitation = an "
        "express statement bounding the use of collected data."
    ),
    colors={"collection": "#3b82f6", "sharing": "#ef4444", "user_choice": "#10b981",
            "access_rights": "#06b6d4", "retention": "#f59e0b", "security": "#8b5cf6",
            "policy_change": "#ec4899", "do_not_track": "#6366f1",
            "audience_scope": "#f97316", "purpose_limitation": "#14b8a6"},
    priority_filters=["collection", "sharing", "user_choice"],
    scope_fields=["user_categories", "information_types", "jurisdictions"],
    segmentation=(
        "Privacy policies are already written in short topical blocks. Segment on headed "
        "sections (\"Information We Collect\", \"How We Share Information\", \"Your Choices\", "
        "\"Data Security\", \"Changes to This Policy\"), and where headings are absent, on "
        "paragraph boundaries — a paragraph is the natural unit of a data practice. Keep a "
        "bulleted list of data categories attached to the sentence that introduces it, and keep "
        "an opt-out mechanism attached to the practice it applies to."
    ),
    dedup_rules=(
        "Privacy policies restate practices in overview and detail sections. Two rules are "
        "duplicates only when the actor, the information type, the purpose, and the user choice "
        "all match. Keep separate: first-party collection versus third-party collection of the "
        "same data type; the same data type collected for different purposes; a practice stated "
        "for all users versus one stated for children or for a specific jurisdiction; and an "
        "opt-in versus an opt-out mechanism over the same practice."
    ),
    dependency_examples=(
        "- A collection practice is a prerequisite for any sharing rule over the same data type.\n"
        "- An opt-out mechanism is conditional on the practice it governs being active.\n"
        "- A retention rule is sequential with the collection that starts the clock.\n"
        "- A children-specific practice overrides the general practice for that audience.\n"
        "- A blanket statement that data is never sold is contradictory with a sharing rule that "
        "discloses data to advertising partners for consideration.\n"
        "- Security measures are complementary to retention rules, and access rights act as a "
        "validation path over the accuracy of collected data."
    ),
    matcher_axes=(
        "the acting party (first versus third party), the information type, the stated purpose, "
        "the collection mode, whether a choice is offered and whether it is opt-in or opt-out, "
        "the retention duration, and the audience or jurisdiction the practice is limited to"
    ),
    validation_criteria=(
        "A high-quality privacy rule names the actor, the specific information type, and the "
        "purpose, rather than restating a vague sentence. A rule that says \"we may collect "
        "information to improve our services\" without pinning the data category is low value; "
        "prefer rules that carry a concrete category, a mechanism, and a user control."
    ),
    worked_rule=(
        "\"Contact Information Collected at Registration Is Shared With Advertising Partners "
        "Unless the User Opts Out\" — rule_type sharing, bound to the "
        "INFORMATION_SHARED_WITH_THIRD_PARTY relationship, conditioned on the user not having "
        "exercised the opt-out, with the preference-centre mechanism captured as the user "
        "choice and children's accounts recorded as an exception."
    ),
)

MOBILE_APP_PRIVACY = Profile(
    key="mobile_app_privacy",
    title="Mobile App Privacy (GDPR, bilingual)",
    benchmark="MAPP Corpus (64 English and 91 German mobile-app privacy policies, "
              "GDPR-era annotation with an explicit legal-basis attribute)",
    persona="an expert data-protection analyst who reads mobile application privacy "
            "policies under the GDPR and records both the data practice and its lawful basis",
    genre="mobile application privacy policies published for app-store distribution, "
          "written in English or German",
    corpus_note="Practices are annotated as either first-party collection/use or third-party "
                "collection/use, and each carries attributes for Information Type, Purpose, "
                "Collection Process, Collection Mode, Third-Party Entity, Choice Type, Choice "
                "Scope, User Type, Anonymization, and — distinctively for this corpus — Legal "
                "Basis for Collection. The legal basis is the GDPR Article 6 ground: consent, "
                "performance of a contract, legal obligation, vital interests, public task, or "
                "legitimate interests.",
    entity_types=[
        ("DATA_CONTROLLER", "The app publisher that determines purposes and means of processing",
         "controller_name, app_identifier, establishment, dpo_contact, representative_in_eu",
         "The app publisher named as controller under GDPR Article 4(7)"),
        ("DATA_SUBJECT", "The individual whose personal data the app processes",
         "user_type, age_bracket, account_status, residency, consent_state",
         "App users resident in the European Economic Area"),
        ("PERSONAL_DATA_TYPE", "A category of personal data processed by the app",
         "data_category, special_category_flag, identifiability, source, anonymisation_state",
         "Device identifiers, precise location, contact information"),
        ("PROCESSING_PURPOSE", "The stated reason a data category is processed",
         "purpose_statement, necessity_basis, secondary_use, profiling_flag, retention_link",
         "Advertising and marketing measurement"),
        ("LEGAL_BASIS", "The GDPR Article 6 ground relied on for a processing activity",
         "basis_type, consent_mechanism, legitimate_interest_test, contract_reference, "
         "withdrawal_route",
         "Consent under Article 6(1)(a), withdrawable in app settings"),
        ("THIRD_PARTY_PROCESSOR", "An external recipient or processor of app data",
         "recipient_name, recipient_role, sdk_identifier, transfer_mechanism, onward_sharing",
         "Analytics SDK acting as processor under a data-processing agreement"),
        ("DATA_SUBJECT_RIGHT", "A GDPR right the policy tells the user how to exercise",
         "right_type, exercise_mechanism, response_deadline, verification_step, complaint_route",
         "Right of erasure exercisable by email, answered within one month"),
        ("CROSS_BORDER_TRANSFER", "A transfer of personal data outside the EEA",
         "destination, transfer_mechanism, adequacy_decision, safeguards, onward_transfer",
         "Transfer to the United States under Standard Contractual Clauses"),
    ],
    relationships=[
        ("CONTROLLER_PROCESSES_DATA", "DATA_CONTROLLER", "PERSONAL_DATA_TYPE",
         "The first-party processing activity and the data categories it covers"),
        ("PROCESSING_RELIES_ON_BASIS", "PROCESSING_PURPOSE", "LEGAL_BASIS",
         "Binds a purpose to the Article 6 ground the policy claims for it"),
        ("DATA_SHARED_WITH_PROCESSOR", "PERSONAL_DATA_TYPE", "THIRD_PARTY_PROCESSOR",
         "Disclosure to an SDK, analytics provider, or advertising partner"),
        ("SUBJECT_EXERCISES_RIGHT", "DATA_SUBJECT", "DATA_SUBJECT_RIGHT",
         "The mechanism and deadline for exercising a GDPR right"),
    ],
    rule_types=["collection", "third_party_sharing", "legal_basis", "purpose_limitation",
                "data_subject_rights", "consent", "retention", "security",
                "cross_border_transfer", "minors"],
    rule_type_notes=(
        "collection = first-party processing of a data category, with mode and process; "
        "third_party_sharing = disclosure to a named SDK, processor, or advertising partner; "
        "legal_basis = the Article 6 ground claimed for a processing activity, which is the "
        "distinguishing axis of this domain and must be captured whenever the text states or "
        "clearly implies one; purpose_limitation = an express bound on secondary use; "
        "data_subject_rights = access, rectification, erasure, portability, restriction, "
        "objection, and the mechanism and deadline for each; consent = how consent is obtained, "
        "recorded, and withdrawn; retention = storage periods and deletion triggers; security = "
        "technical and organisational measures; cross_border_transfer = transfers outside the "
        "EEA and the safeguard relied on; minors = practices specific to children."
    ),
    colors={"collection": "#3b82f6", "third_party_sharing": "#ef4444", "legal_basis": "#8b5cf6",
            "purpose_limitation": "#14b8a6", "data_subject_rights": "#10b981",
            "consent": "#06b6d4", "retention": "#f59e0b", "security": "#6366f1",
            "cross_border_transfer": "#f97316", "minors": "#ec4899"},
    priority_filters=["collection", "legal_basis", "data_subject_rights"],
    scope_fields=["user_types", "data_categories", "jurisdictions"],
    segmentation=(
        "App privacy policies follow the GDPR disclosure order. Segment on headed sections in "
        "either language — \"Information We Collect\" / \"Welche Daten wir erheben\", \"Legal "
        "Basis\" / \"Rechtsgrundlage\", \"Your Rights\" / \"Ihre Rechte\", \"Data Retention\" / "
        "\"Speicherdauer\", \"Third Parties\" / \"Weitergabe an Dritte\" — and on paragraph "
        "boundaries where headings are absent. Keep a legal-basis statement attached to the "
        "processing purpose it justifies; separating them destroys the corpus's central signal."
    ),
    dedup_rules=(
        "Two rules are duplicates only when the controller, the data category, the purpose, AND "
        "the legal basis all match. A rule differing only in legal basis is NOT a duplicate — "
        "the same data collected under consent versus under legitimate interests is two distinct "
        "practices with different user rights attached. Also keep separate: German-source and "
        "English-source rules from different policies, first-party versus processor processing "
        "of the same category, and practices limited to minors."
    ),
    dependency_examples=(
        "- A legal basis is a prerequisite for every processing purpose that relies on it.\n"
        "- A consent mechanism is conditional on the legal basis being consent under Article "
        "6(1)(a).\n"
        "- A withdrawal-of-consent route is sequential with the consent that precedes it.\n"
        "- A cross-border transfer safeguard is complementary to the sharing rule that triggers "
        "the transfer.\n"
        "- A minors-specific practice overrides the general practice for that user type.\n"
        "- A claim of legitimate interests is contradictory with a statement that processing "
        "occurs only with consent, and a retention limit acts as a validation bound on the "
        "collection it follows."
    ),
    matcher_axes=(
        "the controller, the data category, the processing purpose, the Article 6 legal basis, "
        "the named third-party processor or SDK, the choice type and its scope, the retention "
        "duration, the transfer destination and safeguard, and the user type the practice "
        "applies to"
    ),
    validation_criteria=(
        "A high-quality rule in this domain carries the data category, the purpose, and the "
        "legal basis together. A processing rule with no legal basis recorded is incomplete "
        "unless the source text genuinely states none — in that case set the basis explicitly "
        "to not_stated rather than omitting the field. Rules extracted from German text must "
        "carry the German source quotation while the rule fields themselves are normalised."
    ),
    worked_rule=(
        "\"Precise Location Is Collected for Advertising on the Basis of Consent, Withdrawable "
        "in App Settings\" — rule_type legal_basis, bound to the PROCESSING_RELIES_ON_BASIS "
        "relationship, conditioned on the user granting the location permission, with the "
        "Article 6(1)(a) ground and the in-app withdrawal route as consequences, and processing "
        "of coarse location under legitimate interests recorded as a separate rule."
    ),
    language_note=(
        "Source text is English OR German. Read both languages natively. Quote source_text "
        "verbatim in the original language, but write every rule_name, description, condition, "
        "and consequence in English so that rules from the two halves of the corpus merge into "
        "one graph. Record the detected language on each rule."
    ),
    extra_extraction_note=(
        "Capture the GDPR legal basis on every processing rule. Use exactly one of: consent, "
        "contract, legal_obligation, vital_interests, public_task, legitimate_interests, or "
        "not_stated."
    ),
)

PROFILES = [COMMERCIAL_CONTRACTS, NDA_CONFIDENTIALITY, PRIVACY_POLICY, MOBILE_APP_PRIVACY]


# ═══════════════════════════════════════════════════════════════════════════
# Prompt templates — $name is profile injection, {name} is a runtime placeholder,
# and {{ }} are literal JSON braces that survive str.format().
# ═══════════════════════════════════════════════════════════════════════════

HEADER = """# $title domain — $name_slug.txt
# Benchmark corpus: $benchmark
"""

DOCUMENT_STRUCTURE = """You are $persona.

Split the document below into logical sections for downstream rule extraction.
Source genre: $genre.

SEGMENTATION GUIDANCE
$segmentation

Return ONLY one valid JSON object, no Markdown:
{{
  "has_toc": true,
  "sections": [
    {{
      "section_id": "S1",
      "title": "Section heading exactly as it appears",
      "level": 1,
      "start_marker": "first 8-12 words of the section, verbatim",
      "end_marker": "last 8-12 words of the section, verbatim",
      "summary": "one sentence on what this section governs",
      "rule_bearing": true
    }}
  ],
  "structure_notes": "how the document was segmented and why"
}}

Rules:
- start_marker and end_marker MUST be verbatim substrings of the document; the
  organiser slices on them and a paraphrase silently drops the section.
- Set rule_bearing false for pure boilerplate (signature blocks, addresses).
- Prefer 8-40 sections. Do not split a provision from its sub-provisions.

DOCUMENT:
{content}
"""

ENTITY_EXTRACTION_COMPACT = """You build the small, source-grounded entity foundation for a $title
compliance knowledge graph. You are $persona.
Use only concepts supported by the excerpts below. Prefer concrete $key concepts
over generic words, and do not invent a complete domain model; detailed rule
extraction happens later from the full corpus.

$language_note

CANONICAL ENTITY TYPES FOR THIS DOMAIN (prefer these names when supported):
$entities

CANONICAL RELATIONSHIPS:
$relationships

Return ONLY one valid JSON object, with no Markdown or explanation. Return at
{max_entities} entity types and {max_relationships} relationships. Keep every definition
under 20 words. Each entity needs exactly five short attribute names, one
excerpt-grounded example, and one short business-rule summary. Each relationship
needs source_entity, target_entity, definition, cardinality, one example, and
one business-rule summary.

Required JSON shape:
{{
  "entity_types": {{
    "ENTITY_NAME": {{
      "definition": "...",
      "attributes": ["...", "...", "...", "...", "..."],
      "examples": ["..."],
      "business_rules": ["..."]
    }}
  }},
  "relationships": {{
    "RELATIONSHIP_NAME": {{
      "source_entity": "ENTITY_NAME",
      "target_entity": "ENTITY_NAME",
      "definition": "...",
      "cardinality": "one-to-one|one-to-many|many-to-many",
      "examples": ["..."],
      "business_rules": ["..."]
    }}
  }}
}}

EXCERPTS:
{sample_content}
"""

ENTITY_EXTRACTION = """You are $persona.

Extract the domain model — entity types and relationships — from $genre.
$corpus_note

$language_note

CANONICAL ENTITY TYPES FOR THIS DOMAIN:
$entities

CANONICAL RELATIONSHIPS:
$relationships

Return ONLY one valid JSON object, no Markdown:
{{
  "entity_types": {{
    "ENTITY_NAME": {{
      "definition": "Clear business definition in $title context",
      "description": "Longer explanation of the role this entity plays",
      "attributes": ["attribute_one", "attribute_two", "attribute_three"],
      "examples": ["excerpt-grounded example"],
      "business_rules": ["High-level summary of a rule involving this entity"],
      "business_rule_summaries": ["Alternate summary list for downstream compatibility"]
    }}
  }},
  "relationships": {{
    "RELATIONSHIP_NAME": {{
      "source_entity": "SOURCE_ENTITY_NAME",
      "target_entity": "TARGET_ENTITY_NAME",
      "source": "SOURCE_ENTITY_NAME",
      "target": "TARGET_ENTITY_NAME",
      "definition": "What this relationship means in $title context",
      "description": "Directional semantics of the relationship",
      "cardinality": "one-to-one|one-to-many|many-to-many",
      "examples": ["excerpt-grounded example"],
      "business_rules": ["High-level summary of a rule governing this relationship"]
    }}
  }},
  "extraction_metadata": {{
    "source_document": "Document name or section",
    "entity_count": 0,
    "relationship_count": 0
  }}
}}

Ground every entity and relationship in the excerpts. Do not invent entities the
text does not support.

EXCERPTS:
{sample_content}
"""

BUSINESS_RULES_COMPACT = """You extract source-grounded $title business rules for a knowledge graph.
You are $persona.
Use the canonical entity and relationship names in the context below.
Read only the supplied batch excerpts; do not invent unsupported thresholds or
requirements. Extract up to {rules_per_batch} detailed rules for batch
{batch_num}. If the excerpts support fewer, return fewer rather than guessing.

$language_note
$extra_extraction_note

Return ONLY valid JSON, with no Markdown or explanation:
{{
  "entity_types": {{
    "CANONICAL_ENTITY": {{"business_rules": [RULE_OBJECT]}}
  }},
  "relationships": {{
    "CANONICAL_RELATIONSHIP": {{"business_rules": [RULE_OBJECT]}}
  }}
}}

Every RULE_OBJECT must contain:
- rule_id: globally unique and containing batch number {batch_num};
- rule_name, rule_type, description, conditions, consequences, exceptions;
- source_reference: {{"chunk_path": exact FILE path, "section_id": section,
  "start_word_position": integer, "end_word_position": integer,
  "source_text": verbatim 30-150 word excerpt}};
- mandatory (boolean), examples (array), effective_date, expiration_date,
  superseded_by, jurisdiction, risk_level, related_rules (array),
  enforcement_action, applicability_scope ($scope_fields),
  data_points_required (array), and audit_frequency.

Use one of these rule_type values: $rule_types.

$rule_type_notes

Worked example of a well-formed rule for this domain:
$worked_rule

Use exact source paths and verbatim source text so the rule can be verified. Do
not use TBD, placeholders, or paraphrased citations.

CANONICAL ENTITY/RELATIONSHIP CONTEXT:
{entity_context}

SOURCE BATCH EXCERPTS:
{sample_content}
"""

BUSINESS_RULES = """You are $persona. Extract comprehensive, actionable business rules from
$genre that will power a compliance knowledge graph.

$corpus_note

$language_note
$extra_extraction_note

Extract up to {rules_per_batch} rules for batch {batch_num}. Quality over
quantity: a complete rule with exact terms beats three vague ones.

RULE TYPES FOR THIS DOMAIN: $rule_types

$rule_type_notes

Worked example:
$worked_rule

Return ONLY valid JSON, no Markdown:
{{
  "batch_metadata": {{
    "batch_number": {batch_num},
    "rules_extracted": 0,
    "source_section": "Section name or title"
  }},
  "rules": [
    {{
      "rule_id": "BR_ENTITY_CATEGORY_BATCH_SEQ",
      "rule_name": "Human-readable title in plain English, no underscores",
      "rule_type": "$rule_types_enum",
      "entity": "$primary_entity",
      "relationship": "$primary_relationship",
      "description": "Complete, specific rule description",
      "conditions": ["Condition 1 (specific and checkable)", "Condition 2"],
      "consequences": {{
        "if_compliant": "What follows when the rule is satisfied",
        "if_violated": "Consequence, remedy, or exposure"
      }},
      "exceptions": ["Express carve-out stated in the source"],
      "source_reference": {{
        "chunk_path": "exact input FILE path",
        "section_id": "source section",
        "source_text": "verbatim quote supporting this rule"
      }},
      "mandatory": true,
      "confidence_score": 0.9,
      "examples": ["Concrete application of the rule"],
      "applicability_scope": {{"note": "$scope_fields"}},
      "related_rules": []
    }}
  ]
}}

Every rule MUST be traceable to verbatim source text. Do not invent thresholds.

CANONICAL ENTITY/RELATIONSHIP CONTEXT:
{entity_context}

SOURCE BATCH EXCERPTS:
{sample_content}
"""

ENTITY_REFINEMENT = """You are $persona reviewing an extracted $title domain model for quality.

This is refinement iteration {iteration_number}. Score the extraction, then
improve it: merge near-duplicate entities, split entities that conflate two
concepts, and drop entities the source does not support.

Quality bar for this domain:
$validation_criteria

CANONICAL ENTITY TYPES TO PREFER:
$entities

Return ONLY valid JSON, no Markdown:
{{
  "quality_score": 85,
  "assessment": {{
    "coverage": "Are the domain's core concepts represented?",
    "specificity": "Are entities concrete rather than generic?",
    "grounding": "Is every entity supported by source text?"
  }},
  "issues": [
    {{"entity": "ENTITY_NAME", "issue": "what is wrong", "severity": "high|medium|low"}}
  ],
  "refined_entity_types": {{
    "ENTITY_NAME": {{
      "definition": "...",
      "attributes": ["...", "...", "...", "...", "..."],
      "examples": ["..."],
      "business_rules": ["..."]
    }}
  }},
  "refined_relationships": {{
    "RELATIONSHIP_NAME": {{
      "source_entity": "ENTITY_NAME",
      "target_entity": "ENTITY_NAME",
      "definition": "...",
      "cardinality": "one-to-one|one-to-many|many-to-many"
    }}
  }},
  "changes_made": ["what was merged, split, renamed, or dropped"]
}}

CURRENT ENTITIES:
{entities_json}
"""

ENTITY_RESOLUTION = """You are $persona merging $title domain models extracted from several
documents into one canonical set.

Two entities are the same when they denote the same real-world concept, even if
named differently. Two entities are different when they differ in role,
direction, or scope — in this domain that most often means:
$dedup_rules

Return ONLY valid JSON, no Markdown:
{{
  "entity_clusters": [
    {{
      "canonical_name": "CANONICAL_ENTITY_NAME",
      "member_entities": ["NAME_IN_DOC_A", "NAME_IN_DOC_B"],
      "source_documents": ["doc_a", "doc_b"],
      "merged_definition": "definition covering every member",
      "merged_attributes": ["...", "..."],
      "rationale": "why these are the same concept",
      "confidence": "high|medium|low"
    }}
  ],
  "resolution_summary": {{
    "input_entity_count": 0,
    "canonical_entity_count": 0,
    "clusters_formed": 0,
    "unmerged_entities": []
  }}
}}

ENTITIES BY SOURCE:
{entities_by_source}

SOURCE DOCUMENTS:
{source_documents}
"""

RULE_RESOLUTION = """You are $persona reconciling $title business rules extracted from several
documents into one consistent set.

$dedup_rules

A conflict exists when two rules would require incompatible behaviour in the
same situation. Record conflicts rather than silently choosing a winner.

Return ONLY valid JSON, no Markdown:
{{
  "rule_clusters": [
    {{
      "canonical_rule_id": "BR_CANONICAL_001",
      "member_rule_ids": ["BR_A_001", "BR_B_007"],
      "source_documents": ["doc_a", "doc_b"],
      "merged_description": "description covering every member",
      "rationale": "why these express the same requirement",
      "confidence": "high|medium|low"
    }}
  ],
  "conflicts_detected": [
    {{
      "rule_ids": ["BR_A_003", "BR_B_012"],
      "conflict_type": "threshold|scope|direction|obligation",
      "description": "how the two rules disagree",
      "resolution_recommendation": "which governs and why, or escalate"
    }}
  ],
  "resolution_summary": {{
    "input_rule_count": 0,
    "canonical_rule_count": 0,
    "clusters_formed": 0,
    "conflict_count": 0
  }}
}}

RULES BY SOURCE:
{rules_by_source}

SOURCE DOCUMENTS:
{source_documents}
"""

RULE_DEDUPLICATION = """You are $persona deduplicating a $title knowledge graph containing
{total_rules} extracted rules.

Be conservative. Removing a genuinely distinct rule loses compliance coverage;
keeping a near-duplicate is cheap. When in doubt, do not merge.

WHAT COUNTS AS A DUPLICATE IN THIS DOMAIN
$dedup_rules

Return ONLY valid JSON, no Markdown:
{{
  "duplicate_groups": [
    {{
      "primary_rule_id": "BR_KEEP_THIS_001",
      "duplicate_rule_ids": ["BR_MERGE_AWAY_004", "BR_MERGE_AWAY_009"],
      "merged_description": "single description preserving every distinct detail",
      "rationale": "why these express the identical requirement",
      "confidence": "high|medium|low",
      "similarity_score": 0.95,
      "score_breakdown": {{
        "condition_overlap": 0.9,
        "consequence_overlap": 1.0,
        "scope_overlap": 0.95,
        "party_overlap": 1.0
      }},
      "primary_selection_reason": "why the primary was chosen as canonical",
      "merged_examples": ["examples carried over from every member"]
    }}
  ],
  "deduplication_summary": {{
    "input_rule_count": {total_rules},
    "groups_found": 0,
    "rules_removed": 0
  }}
}}

Only report a group when you are confident. Rules left out of every group are
kept as-is.

RULES:
{rules_json}
"""

DEPENDENCY_ANALYSIS = """You are $persona mapping dependencies across {total_rules} rules in a
$title knowledge graph.

Identify how rules relate. Use exactly these seven dependency_type values:
- prerequisite  — the target must hold before the source can apply
- sequential    — the rules apply in a defined order over time
- conditional   — the source applies only when the target is triggered
- complementary — the rules reinforce each other without ordering
- contradictory — the rules would require incompatible behaviour
- override      — the source displaces the target in its scope
- validation    — the source checks or bounds the target

TYPICAL DEPENDENCIES IN THIS DOMAIN
$dependency_examples

Return ONLY valid JSON, no Markdown:
{{
  "dependencies": [
    {{
      "source_rule_id": "BR_SOURCE_001",
      "target_rule_id": "BR_TARGET_002",
      "dependency_type": "prerequisite",
      "rationale": "why this dependency exists, citing both rules",
      "impact": "what breaks if the dependency is ignored",
      "strength": 4
    }}
  ],
  "dependency_chains": [
    {{
      "chain_id": "C1",
      "rule_sequence": ["BR_A_001", "BR_B_002", "BR_C_003"],
      "description": "what this chain governs end to end"
    }}
  ],
  "circular_dependencies": [
    {{
      "cycle": ["BR_A_001", "BR_B_002", "BR_A_001"],
      "severity": "high|medium|low",
      "recommendation": "how to break the cycle"
    }}
  ],
  "analysis_summary": {{
    "total_rules_analyzed": {total_rules},
    "dependencies_found": 0,
    "chains_found": 0,
    "cycles_found": 0
  }}
}}

strength is 1-5, where 5 means the dependency is stated explicitly in the source
and 1 means it is a weak inference. Report only dependencies you can justify.

RULES:
{rules_json}
"""

RULE_MATCHER = """You are $persona comparing one pair of rules drawn from two $title
knowledge graphs, {g1_name} and {g2_name}.

Classify the relationship as exactly one of:
- IDENTICAL     — the same requirement, same terms, same scope
- EQUIVALENT    — the same intent and outcome, wording or minor detail differs
- CONTRADICTORY — both apply to the same situation but require different results
- UNRELATED     — they govern different situations

COMPARE ALONG THESE AXES
$matcher_axes

Return ONLY valid JSON, no Markdown:
{{
  "relationship": "IDENTICAL|EQUIVALENT|CONTRADICTORY|UNRELATED",
  "confidence": 0.9,
  "similarity_score": 0.85,
  "reasoning": "which axes matched and which differed",
  "key_comparison": {{
    "matching_axes": ["..."],
    "differing_axes": ["..."]
  }},
  "conflict_detail": {{
    "conflict_type": "threshold|scope|direction|obligation",
    "g1_position": "what graph 1 requires",
    "g2_position": "what graph 2 requires"
  }}
}}

Set conflict_detail only when the relationship is CONTRADICTORY.

RULE A (from {g1_name}):
{rule_a}

RULE B (from {g2_name}):
{rule_b}
"""

RULE_MATCHER_BATCH = """You are $persona comparing {num_pairs} rule pairs drawn from two $title
knowledge graphs, {g1_name} and {g2_name}, in a single call.

Classify each pair as exactly one of:
- IDENTICAL     — the same requirement, same terms, same scope
- EQUIVALENT    — the same intent and outcome, wording or minor detail differs
- CONTRADICTORY — both apply to the same situation but require different results
- UNRELATED     — they govern different situations

COMPARE ALONG THESE AXES
$matcher_axes

Return ONLY a valid JSON array with one object per pair, no Markdown:
[
  {{
    "pair_id": 0,
    "relationship": "IDENTICAL|EQUIVALENT|CONTRADICTORY|UNRELATED",
    "confidence": 0.9,
    "similarity_score": 0.85,
    "reasoning": "which axes matched and which differed",
    "key_comparison": {{
      "matching_axes": ["..."],
      "differing_axes": ["..."]
    }},
    "conflict_detail": {{
      "conflict_type": "threshold|scope|direction|obligation",
      "g1_position": "what graph 1 requires",
      "g2_position": "what graph 2 requires"
    }}
  }}
]

Return exactly {num_pairs} objects with pair_id values matching the input. Set
conflict_detail only for CONTRADICTORY pairs.

RULE PAIRS:
{rule_pairs_json}
"""

VALIDATION_REPORT = """You are $persona assessing the quality of an extracted $title rule set.

QUALITY BAR FOR THIS DOMAIN
$validation_criteria

Rule types that should be represented: $rule_types

Return ONLY valid JSON, no Markdown:
{{
  "overall_score": 85,
  "rating": "excellent|good|acceptable|poor",
  "assessment": {{
    "completeness": {{"score": 85, "notes": "are the domain's core practices covered?"}},
    "specificity": {{"score": 80, "notes": "do rules carry concrete terms?"}},
    "traceability": {{"score": 90, "notes": "is every rule tied to verbatim source text?"}},
    "type_coverage": {{"score": 75, "notes": "which rule types are missing or over-represented?"}}
  }},
  "issues": [
    {{
      "rule_id": "BR_EXAMPLE_001",
      "issue": "what is wrong with this rule",
      "severity": "high|medium|low",
      "recommendation": "how to fix it"
    }}
  ],
  "missing_coverage": ["domain areas the rule set does not address"],
  "recommendations": ["ranked, actionable next steps"]
}}

EXTRACTION METRICS:
{metrics_json}
"""

TEMPLATES = {
    "document_structure_analysis": DOCUMENT_STRUCTURE,
    "entity_extraction_compact": ENTITY_EXTRACTION_COMPACT,
    "entity_extraction": ENTITY_EXTRACTION,
    "business_rules_extraction_compact": BUSINESS_RULES_COMPACT,
    "business_rules_extraction": BUSINESS_RULES,
    "entity_refinement": ENTITY_REFINEMENT,
    "entity_resolution": ENTITY_RESOLUTION,
    "rule_resolution": RULE_RESOLUTION,
    "rule_deduplication": RULE_DEDUPLICATION,
    "dependency_analysis": DEPENDENCY_ANALYSIS,
    "rule_matcher": RULE_MATCHER,
    "rule_matcher_batch": RULE_MATCHER_BATCH,
    "validation_report": VALIDATION_REPORT,
}


# Values that are flowing prose and should be wrapped to the prompt's column
# width. Everything else (entity blocks, bullet lists, single tokens) keeps the
# line structure the profile gives it.
_WRAPPED_FIELDS = {
    "persona", "genre", "corpus_note", "rule_type_notes", "worked_rule",
    "segmentation", "dedup_rules", "matcher_axes", "validation_criteria",
    "language_note", "extra_extraction_note", "rule_types",
    "dependency_examples", "entities", "relationships",
}
_WIDTH = 78


def _wrap(value: str) -> str:
    """Wrap to _WIDTH, preserving each line's own indentation and hanging bullets."""
    out = []
    for line in value.split("\n"):
        if not line.strip():
            out.append("")
            continue
        indent = line[: len(line) - len(line.lstrip())]
        # A bullet continues under its text, not under the marker.
        hang = indent + ("  " if line.lstrip().startswith("- ") else "")
        out.append(textwrap.fill(
            line.strip(), _WIDTH, initial_indent=indent, subsequent_indent=hang,
        ))
    return "\n".join(out)


def render(profile: Profile, name: str) -> str:
    mapping = profile.mapping()
    mapping["name_slug"] = name
    mapping = {k: (_wrap(v) if k in _WRAPPED_FIELDS else v) for k, v in mapping.items()}
    body = Template(TEMPLATES[name]).safe_substitute(mapping)
    head = Template(HEADER).safe_substitute(mapping)
    # Empty optional notes (language_note, extra_extraction_note) leave blank runs.
    return re.sub(r"\n{3,}", "\n\n", head + "\n" + body)


def verify(name: str, text: str) -> list[str]:
    """Return a list of problems with one rendered prompt."""
    problems = []
    if "$" in text:
        leftovers = {w for w in text.split() if w.startswith("$")}
        problems.append(f"unsubstituted profile token(s): {sorted(leftovers)}")
    try:
        text.format(**RUNTIME_KWARGS[name])
    except Exception as exc:  # noqa: BLE001 - surfaced to the caller as a message
        problems.append(f"str.format failed with real kwargs: {type(exc).__name__}: {exc}")
    if len(text.encode()) <= 100:
        problems.append("shorter than the 100-byte contract-test minimum")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true",
                        help="verify rendering and on-disk files without writing")
    args = parser.parse_args()

    failures = 0
    for profile in PROFILES:
        target = DOMAIN_PROMPTS / profile.key
        if not args.check:
            target.mkdir(parents=True, exist_ok=True)
        written = 0
        for name in TEMPLATE_NAMES:
            text = render(profile, name)
            for problem in verify(name, text):
                print(f"  FAIL {profile.key}/{name}.txt: {problem}")
                failures += 1
            path = target / f"{name}.txt"
            if args.check:
                if not path.exists():
                    print(f"  FAIL {profile.key}/{name}.txt: missing on disk")
                    failures += 1
                elif path.read_text(encoding="utf-8") != text:
                    print(f"  FAIL {profile.key}/{name}.txt: on-disk copy is stale")
                    failures += 1
            else:
                path.write_text(text, encoding="utf-8")
                written += 1
        verb = "checked" if args.check else "wrote"
        print(f"{profile.key:<24} {verb} {len(TEMPLATE_NAMES) if args.check else written} templates")

    if failures:
        print(f"\n{failures} problem(s)")
        return 1
    print("\nall templates render, format cleanly, and match disk" if args.check
          else "\nall templates written")
    return 0


if __name__ == "__main__":
    sys.exit(main())
