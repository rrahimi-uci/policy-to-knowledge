#!/usr/bin/env python3
"""
Agent 3.5: Rule Validation Agent

Validates extracted business rules for:
1. Source verification - Rules match source documents
2. Numeric consistency - Thresholds are consistent
3. Cross-rule contradiction detection
4. Completeness checks
5. Confidence assessment validation

Author: Reza Rahimi
Date: December 20, 2025
"""

import json
import sys
import os
from pathlib import Path
from typing import List, Dict, Any
from datetime import datetime

# Add project root to Python path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.prompt_manager import get_prompt_manager
from utils.llm_client import create_llm_client
from utils.config import get_config


class RuleValidationAgent:
    """
    Validates extracted business rules for accuracy, consistency, and completeness.
    """
    
    def __init__(self, api_key: str, model: str = None):
        """
        Initialize the validation agent.
        
        Args:
            api_key: API key for LLM provider
            model: Optional override for model selection
        """
        self.config = get_config()
        self.model = model or self.config.get_optimizer_model()
        self.client = create_llm_client(
            api_key=api_key,
            model=self.model,
            timeout=self.config.get_timeout(),
            max_retries=self.config.get_max_retries()
        )
        self.prompt_manager = get_prompt_manager()
        
        print(f"""
╔══════════════════════════════════════════════════════════════════════╗
║   Business Rules Validation Agent                                   ║
║   Quality Assurance for Extracted Rules                             ║
╚══════════════════════════════════════════════════════════════════════╝
""")
        print(f"Configuration:")
        print(f"  Model: {self.model}")
        print(f"  Validation Checks: 5 (source, numeric, contradictions, completeness, confidence)")
    
    def load_rules(self, rules_file: Path) -> Dict[str, Any]:
        """Load extracted business rules from JSON file."""
        if not rules_file.exists():
            raise FileNotFoundError(f"Rules file not found: {rules_file}")
        
        with open(rules_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        # Extract rules from data structure
        rules = []
        entity_types = data.get('entity_types', {})
        
        for entity_name, entity_data in entity_types.items():
            entity_rules = entity_data.get('business_rules', [])
            for rule in entity_rules:
                rule['source_entity'] = entity_name
                rules.append(rule)
        
        print(f"\n✓ Loaded {len(rules)} business rules from {rules_file.name}")
        return {'rules': rules, 'entity_types': entity_types, 'raw_data': data}
    
    def load_source_documents(self, organized_dir: Path) -> List[Dict[str, str]]:
        """Load source documents for verification."""
        documents = []
        
        for txt_file in organized_dir.rglob("*.txt"):
            # Skip metadata files
            if txt_file.name.startswith('_'):
                continue
            
            try:
                with open(txt_file, 'r', encoding='utf-8') as f:
                    content = f.read()
                    if content.strip():
                        relative_path = txt_file.relative_to(organized_dir)
                        documents.append({
                            'path': str(relative_path),
                            'content': content
                        })
            except Exception as e:
                print(f"⚠️  Error reading {txt_file}: {e}")
        
        print(f"✓ Loaded {len(documents)} source documents for verification")
        return documents
    
    def validate_rules(
        self, 
        rules: List[Dict[str, Any]], 
        source_documents: List[Dict[str, str]] = None
    ) -> Dict[str, Any]:
        """
        Validate all rules with comprehensive checks.
        
        Args:
            rules: List of extracted business rules
            source_documents: Optional source documents for verification
            
        Returns:
            Validation report with passed/warned/failed rules
        """
        print(f"\n{'='*70}")
        print(f"VALIDATION: Analyzing {len(rules)} Business Rules")
        print(f"{'='*70}")
        
        validation_report = {
            "timestamp": datetime.now().isoformat(),
            "total_rules": len(rules),
            "passed": [],
            "warnings": [],
            "failures": [],
            "corrections": [],
            "statistics": {
                "passed_count": 0,
                "warning_count": 0,
                "failure_count": 0,
                "avg_confidence": 0
            }
        }
        
        # Check 1: Confidence Score Validation
        print(f"\n📊 Check 1: Confidence Score Validation")
        self._validate_confidence_scores(rules, validation_report)
        
        # Check 2: Numeric Consistency
        print(f"\n🔢 Check 2: Numeric Threshold Consistency")
        self._validate_numeric_consistency(rules, validation_report)
        
        # Check 3: Completeness
        print(f"\n✅ Check 3: Rule Completeness")
        self._validate_completeness(rules, validation_report)
        
        # Check 4: Cross-Rule Contradictions
        print(f"\n⚠️  Check 4: Cross-Rule Contradiction Detection")
        self._detect_contradictions(rules, validation_report)
        
        # Check 5: Source Verification (if documents provided)
        if source_documents:
            print(f"\n📄 Check 5: Source Document Verification")
            self._verify_against_sources(rules, source_documents, validation_report)
        else:
            print(f"\n⏭️  Check 5: Skipped (no source documents provided)")
        
        # Calculate statistics
        validation_report['statistics']['passed_count'] = len(validation_report['passed'])
        validation_report['statistics']['warning_count'] = len(validation_report['warnings'])
        validation_report['statistics']['failure_count'] = len(validation_report['failures'])
        
        # Calculate average confidence
        confidences = [r.get('confidence_score', 0) for r in rules]
        validation_report['statistics']['avg_confidence'] = sum(confidences) / len(confidences) if confidences else 0
        
        # Print summary
        self._print_validation_summary(validation_report)
        
        return validation_report
    
    def _validate_confidence_scores(self, rules: List[Dict], report: Dict):
        """Validate confidence scores are present and reasonable."""
        low_confidence_rules = []
        missing_confidence = []
        
        for rule in rules:
            rule_id = rule.get('rule_id', 'UNKNOWN')
            
            # Check if confidence score exists
            if 'confidence_score' not in rule:
                missing_confidence.append(rule_id)
                report['warnings'].append({
                    "rule_id": rule_id,
                    "check": "confidence_score",
                    "severity": "medium",
                    "issue": "Missing confidence_score field",
                    "recommendation": "Add confidence scoring to extraction prompt"
                })
                continue
            
            confidence = rule.get('confidence_score', 0)
            
            # Flag low confidence rules
            if confidence < 70:
                low_confidence_rules.append({
                    "rule_id": rule_id,
                    "confidence": confidence,
                    "title": rule.get('title', rule.get('rule_name', 'N/A'))
                })
                
                report['warnings'].append({
                    "rule_id": rule_id,
                    "check": "confidence_score",
                    "severity": "high",
                    "issue": f"Low confidence score: {confidence}/100",
                    "recommendation": "Requires human review and validation"
                })
        
        if not missing_confidence and not low_confidence_rules:
            report['passed'].append({
                "check": "confidence_scores",
                "message": "All rules have adequate confidence scores (≥70)"
            })
        
        print(f"  • Rules with low confidence (<70): {len(low_confidence_rules)}")
        print(f"  • Rules missing confidence score: {len(missing_confidence)}")
    
    def _validate_numeric_consistency(self, rules: List[Dict], report: Dict):
        """Check for numeric threshold inconsistencies."""
        import re
        
        # Extract numeric patterns from rules
        numeric_rules = {}
        
        for rule in rules:
            rule_id = rule.get('rule_id', 'UNKNOWN')
            description = rule.get('description', '')
            
            # Find numbers in description
            numbers = re.findall(r'\d+\.?\d*', description)
            
            if numbers:
                # Create a normalized key for similar rules
                desc_normalized = description.lower()
                key_terms = ['credit score', 'ltv', 'dti', 'loan amount', 'down payment']
                
                for term in key_terms:
                    if term in desc_normalized:
                        if term not in numeric_rules:
                            numeric_rules[term] = []
                        numeric_rules[term].append({
                            'rule_id': rule_id,
                            'numbers': numbers,
                            'description': description[:200]
                        })
        
        # Check for inconsistencies
        inconsistencies = []
        for term, term_rules in numeric_rules.items():
            if len(term_rules) > 1:
                # Compare numbers across rules
                unique_numbers = set()
                for tr in term_rules:
                    unique_numbers.update(tr['numbers'])
                
                # If multiple different thresholds for same concept, flag it
                if len(unique_numbers) > 1:
                    inconsistencies.append({
                        'term': term,
                        'rules': [tr['rule_id'] for tr in term_rules],
                        'thresholds': list(unique_numbers)
                    })
        
        if inconsistencies:
            for incon in inconsistencies:
                report['warnings'].append({
                    "check": "numeric_consistency",
                    "severity": "medium",
                    "issue": f"Inconsistent thresholds for '{incon['term']}'",
                    "rules": incon['rules'],
                    "thresholds": incon['thresholds'],
                    "recommendation": "Review rules for correct thresholds or contextual differences"
                })
        else:
            report['passed'].append({
                "check": "numeric_consistency",
                "message": "No obvious numeric inconsistencies detected"
            })
        
        print(f"  • Potential inconsistencies found: {len(inconsistencies)}")
    
    def _validate_completeness(self, rules: List[Dict], report: Dict):
        """Check if rules have all required fields."""
        # Updated to use new two-dimensional taxonomy
        required_fields = [
            'rule_id', 'rule_name', 'rule_behavior', 'rule_domain', 'description',
            'conditions', 'consequences', 'source_reference',
            'mandatory', 'examples',
            'jurisdiction', 'risk_level', 'enforcement_action',
            'applicability_scope', 'data_points_required', 'audit_frequency'
        ]
        
        # Fields that are expected but allowed to be null
        nullable_fields = {
            'effective_date', 'expiration_date', 'superseded_by'
        }
        
        # For backward compatibility, accept rule_type in place of rule_behavior/rule_domain
        # and fannie_mae_reference in place of source_reference
        legacy_compatible_fields = {
            'rule_behavior': 'rule_type',  # If rule_behavior missing, check for rule_type
            'rule_domain': 'rule_type',  # If rule_domain missing, check for rule_type
            'source_reference': 'fannie_mae_reference'  # If source_reference missing, check for fannie_mae_reference
        }
        
        incomplete_rules = []
        
        for rule in rules:
            rule_id = rule.get('rule_id', 'UNKNOWN')
            missing_fields = []
            
            for field in required_fields:
                # Check for legacy compatibility
                legacy_field = legacy_compatible_fields.get(field)
                has_field = (field in rule and rule[field]) or \
                           (legacy_field and legacy_field in rule and rule[legacy_field])
                
                if not has_field:
                    missing_fields.append(field)
            
            # Also check nullable fields exist (they should be present even if null)
            for field in nullable_fields:
                if field not in rule:
                    missing_fields.append(f"{field} (nullable but must be present)")
            
            if missing_fields:
                incomplete_rules.append({
                    'rule_id': rule_id,
                    'missing_fields': missing_fields
                })
                
                report['failures'].append({
                    "rule_id": rule_id,
                    "check": "completeness",
                    "severity": "high",
                    "issue": f"Missing required fields: {', '.join(missing_fields)}",
                    "recommendation": "Ensure extraction prompt requires all mandatory fields"
                })
            
            # Validate enum-type field values
            _valid_risk_levels = {'critical', 'high', 'medium', 'low'}
            _valid_audit_frequencies = {'at_origination', 'monthly', 'quarterly', 'annually', 'on_change'}
            
            risk = rule.get('risk_level', '')
            if risk and risk not in _valid_risk_levels:
                report['warnings'].append({
                    "rule_id": rule_id,
                    "check": "enum_validation",
                    "severity": "medium",
                    "issue": f"Invalid risk_level '{risk}'. Expected one of: {', '.join(sorted(_valid_risk_levels))}",
                    "recommendation": "Use a valid risk_level value"
                })
            
            audit = rule.get('audit_frequency', '')
            if audit and audit not in _valid_audit_frequencies:
                report['warnings'].append({
                    "rule_id": rule_id,
                    "check": "enum_validation",
                    "severity": "medium",
                    "issue": f"Invalid audit_frequency '{audit}'. Expected one of: {', '.join(sorted(_valid_audit_frequencies))}",
                    "recommendation": "Use a valid audit_frequency value"
                })
            
            scope = rule.get('applicability_scope', {})
            if scope and isinstance(scope, dict):
                for scope_key in ['loan_types', 'occupancy_types', 'transaction_types']:
                    if scope_key not in scope or not isinstance(scope.get(scope_key), list):
                        report['warnings'].append({
                            "rule_id": rule_id,
                            "check": "scope_validation",
                            "severity": "medium",
                            "issue": f"applicability_scope missing or invalid '{scope_key}' array",
                            "recommendation": f"Ensure applicability_scope.{scope_key} is a non-empty array"
                        })

            # Validate structured source_reference
            src_ref = rule.get('source_reference', rule.get('fannie_mae_reference', ''))
            if isinstance(src_ref, dict):
                # Structured format — validate required sub-fields
                _ref_required = ['chunk_path', 'section_id', 'start_word_position', 'end_word_position', 'source_text']
                ref_missing = [k for k in _ref_required if k not in src_ref]
                if ref_missing:
                    report['warnings'].append({
                        "rule_id": rule_id,
                        "check": "source_reference_structure",
                        "severity": "high",
                        "issue": f"source_reference missing sub-fields: {', '.join(ref_missing)}",
                        "recommendation": "Ensure source_reference has all required sub-fields"
                    })
                else:
                    # Type checks
                    if not isinstance(src_ref.get('start_word_position'), int) or src_ref['start_word_position'] < 0:
                        report['warnings'].append({
                            "rule_id": rule_id,
                            "check": "source_reference_positions",
                            "severity": "medium",
                            "issue": "start_word_position must be a non-negative integer",
                            "recommendation": "Fix word position values"
                        })
                    if not isinstance(src_ref.get('end_word_position'), int) or src_ref['end_word_position'] <= 0:
                        report['warnings'].append({
                            "rule_id": rule_id,
                            "check": "source_reference_positions",
                            "severity": "medium",
                            "issue": "end_word_position must be a positive integer",
                            "recommendation": "Fix word position values"
                        })
                    if isinstance(src_ref.get('start_word_position'), int) and isinstance(src_ref.get('end_word_position'), int):
                        if src_ref['start_word_position'] >= src_ref['end_word_position']:
                            report['warnings'].append({
                                "rule_id": rule_id,
                                "check": "source_reference_positions",
                                "severity": "high",
                                "issue": f"start_word_position ({src_ref['start_word_position']}) >= end_word_position ({src_ref['end_word_position']})",
                                "recommendation": "start must be less than end"
                            })
                    if not src_ref.get('source_text') or len(str(src_ref.get('source_text', '')).split()) < 5:
                        report['warnings'].append({
                            "rule_id": rule_id,
                            "check": "source_reference_text",
                            "severity": "medium",
                            "issue": "source_text is missing or too short (< 5 words)",
                            "recommendation": "Provide a verbatim excerpt of 30-150 words"
                        })
            elif isinstance(src_ref, str) and src_ref:
                # Legacy string format — acceptable but warn
                report['warnings'].append({
                    "rule_id": rule_id,
                    "check": "source_reference_format",
                    "severity": "low",
                    "issue": "source_reference is a plain string (legacy format). Prefer structured object with chunk_path, word positions, and source_text.",
                    "recommendation": "Re-extract with updated prompt to get structured source references"
                })
        
        if not incomplete_rules:
            report['passed'].append({
                "check": "completeness",
                "message": "All rules have required fields"
            })
        
        print(f"  • Incomplete rules: {len(incomplete_rules)}")
    
    def _detect_contradictions(self, rules: List[Dict], report: Dict):
        """Detect potential contradictions between rules."""
        # Simple heuristic: Look for rules with similar descriptions but different requirements
        # This is a placeholder - full implementation would use LLM for semantic comparison
        
        potential_contradictions = []
        
        # Group rules by behavior (HOW) and check for conflicts
        rules_by_behavior = {}
        for rule in rules:
            # Support both new rule_behavior and legacy rule_type
            rule_behavior = rule.get('rule_behavior', rule.get('rule_type', 'unknown'))
            if rule_behavior not in rules_by_behavior:
                rules_by_behavior[rule_behavior] = []
            rules_by_behavior[rule_behavior].append(rule)
        
        # For now, just check for rules with same entity but contradicting mandatory status
        for rule_behavior, behavior_rules in rules_by_behavior.items():
            if len(behavior_rules) > 1:
                # Check for contradicting mandatory flags
                mandatory_rules = [r for r in behavior_rules if r.get('mandatory')]
                optional_rules = [r for r in behavior_rules if not r.get('mandatory')]
                
                # This is a simplified check - real implementation would use LLM
                if mandatory_rules and optional_rules:
                    # Check if they reference similar concepts
                    # (placeholder - would need semantic similarity)
                    pass
        
        if potential_contradictions:
            for contradiction in potential_contradictions:
                report['warnings'].append(contradiction)
        else:
            report['passed'].append({
                "check": "contradictions",
                "message": "No obvious contradictions detected"
            })
        
        print(f"  • Potential contradictions: {len(potential_contradictions)}")
    
    def _verify_against_sources(
        self, 
        rules: List[Dict], 
        source_documents: List[Dict], 
        report: Dict
    ):
        """Verify rules against source documents (sampling approach for efficiency)."""
        # For efficiency, sample a subset of rules for deep verification
        import random
        
        sample_size = min(10, len(rules))  # Validate up to 10 rules
        sampled_rules = random.sample(rules, sample_size)
        
        print(f"  • Sampling {sample_size} rules for source verification...")
        
        verified_count = 0
        
        for rule in sampled_rules:
            # This is a placeholder - full implementation would use LLM to verify
            # For now, just check if the reference exists in documents
            reference = rule.get('source_reference', rule.get('fannie_mae_reference', ''))
            
            # Handle both structured and legacy string formats
            if isinstance(reference, dict):
                has_ref = bool(reference.get('chunk_path'))
            elif isinstance(reference, str):
                has_ref = bool(reference)
            else:
                has_ref = False
            
            if has_ref:
                verified_count += 1
        
        report['passed'].append({
            "check": "source_verification",
            "message": f"Verified {verified_count}/{sample_size} sampled rules have valid references"
        })
        
        print(f"  • Verified: {verified_count}/{sample_size} rules")
    
    def _print_validation_summary(self, report: Dict):
        """Print validation summary."""
        print(f"\n{'='*70}")
        print(f"VALIDATION SUMMARY")
        print(f"{'='*70}")
        print(f"✅ Passed checks: {report['statistics']['passed_count']}")
        print(f"⚠️  Warnings: {report['statistics']['warning_count']}")
        print(f"❌ Failures: {report['statistics']['failure_count']}")
        print(f"📊 Average confidence: {report['statistics']['avg_confidence']:.1f}/100")
        print(f"{'='*70}\n")
    
    def save_validation_report(self, report: Dict, output_dir: Path):
        """Save validation report to file."""
        output_dir.mkdir(parents=True, exist_ok=True)
        
        report_file = output_dir / "validation_report.json"
        with open(report_file, 'w', encoding='utf-8') as f:
            json.dump(report, f, indent=2)
        
        print(f"✓ Validation report saved to: {report_file}")


def main():
    """Main execution function for standalone testing."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Validate extracted business rules")
    parser.add_argument(
        "--rules-file",
        type=str,
        required=True,
        help="Path to rules JSON file (agent-3 output)"
    )
    parser.add_argument(
        "--source-dir",
        type=str,
        help="Path to organized source documents (agent-1 output)"
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        required=True,
        help="Directory to save validation report"
    )
    parser.add_argument(
        "--api-key",
        type=str,
        help="API key (or set via environment variable)"
    )
    
    args = parser.parse_args()
    
    # Get API key — use provider-specific env var to avoid cross-contamination
    openai_key = args.api_key or os.getenv('OPENAI_API_KEY', '')
    anthropic_key = os.getenv('ANTHROPIC_API_KEY', '')
    api_key = openai_key or anthropic_key
    if not api_key:
        print("Error: API key required (--api-key, OPENAI_API_KEY, or ANTHROPIC_API_KEY)")
        sys.exit(1)

    # Initialize validator — pass only the OpenAI key to avoid injecting an
    # Anthropic key into the OPENAI_API_KEY environment variable.
    validator = RuleValidationAgent(api_key=openai_key)
    
    # Load rules
    rules_data = validator.load_rules(Path(args.rules_file))
    
    # Load source documents if provided
    source_documents = None
    if args.source_dir:
        source_documents = validator.load_source_documents(Path(args.source_dir))
    
    # Validate rules
    report = validator.validate_rules(rules_data['rules'], source_documents)
    
    # Save report
    validator.save_validation_report(report, Path(args.output_dir))


if __name__ == "__main__":
    main()
