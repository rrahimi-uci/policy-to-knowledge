#!/usr/bin/env python3
"""
Knowledge Graph Visualization Generator

Creates an interactive HTML visualization with:
1. Network graph showing entities, rules, and dependencies
2. Detailed rules table with filtering and search
3. Beautiful UI with good UX

Author: Reza Rahimi
Date: December 9, 2025
"""

import json
import sys
import os
import base64
from pathlib import Path
from datetime import datetime

# Add project root to Python path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class KnowledgeGraphVisualizer:
    """
    Generates interactive HTML visualizations for knowledge graphs.
    """
    
    def __init__(self, input_file: Path, output_file: Path):
        """
        Initialize the visualizer.
        
        Args:
            input_file: Path to business rules JSON file
            output_file: Path where HTML visualization will be saved
        """
        self.input_file = Path(input_file)
        self.output_file = Path(output_file)
        self.data = None
        self.rules = []
        self.entity_definitions = {}
        self.entity_types = {}
        
    def load_data(self):
        """Load business rules data from JSON file."""
        with open(self.input_file, 'r', encoding='utf-8') as f:
            self.data = json.load(f)
        
        self.rules = self.data.get('business_rules', [])
        metadata = self.data.get('metadata', {})
        
        # Load entity definitions - they're already in the data or load from Agent 2 output
        self.entity_definitions = self.data.get('entity_types', {})
        if not self.entity_definitions:
            # Try loading from Agent 2 output
            from utils.config import get_config
            config = get_config()
            entity_file = config.get_entity_relationship_dir() / 'entity_types_and_relationships.json'
            if entity_file.exists():
                with open(entity_file, 'r', encoding='utf-8') as f:
                    entity_data = json.load(f)
                    self.entity_definitions = entity_data.get('entity_types', {})
        
        # Build entity types map
        for rule in self.rules:
            entity = rule.get('entity_type', 'Unknown')
            if entity not in self.entity_types:
                self.entity_types[entity] = []
            self.entity_types[entity].append(rule)
    
    def generate(self):
        """Generate the HTML visualization."""
        self.load_data()
        html_content = self._generate_html()
        
        # Ensure output directory exists
        self.output_file.parent.mkdir(parents=True, exist_ok=True)
        
        # Write HTML file
        with open(self.output_file, 'w', encoding='utf-8') as f:
            f.write(html_content)
        
        print(f"✅ Visualization generated: {self.output_file}")
        print(f"   📊 {len(self.rules)} rules")
        print(f"   🏷️  {len(self.entity_types)} entities")
        
        # Count connections (dependencies)
        total_connections = sum(
            len(rule.get('dependencies', [])) + len(rule.get('dependent_rules', []))
            for rule in self.rules
        )
        print(f"   🔗 {total_connections} connections (dependencies)")
        print()
        print(f"🌐 Open in browser: file://{self.output_file.absolute()}")
    
    def _generate_html(self):
        """Internal method to generate HTML content."""
        # This calls the existing generate_html_content function
        return generate_html_content(self.data, self.rules, self.entity_types, self.entity_definitions)


def _get_rule_type_description(rule_type):
    """Get a description for each rule type (domain-aware)."""
    import os
    domain = os.getenv('KG_DOMAIN', 'mortgage')
    if domain == 'healthcare':
        descriptions = {
            'clinical_guideline': 'Rules based on clinical best practices and evidence-based care standards.',
            'patient_safety': 'Rules designed to prevent harm and ensure safe care delivery.',
            'hipaa_privacy': 'Rules governing the use and disclosure of protected health information under HIPAA.',
            'billing_compliance': 'Rules ensuring accurate and compliant medical billing and coding.',
            'documentation': 'Rules specifying required clinical documentation and record-keeping.',
            'consent_requirement': 'Rules governing patient consent and authorization requirements.',
            'credentialing': 'Rules for verifying and maintaining provider qualifications and credentials.',
            'quality_measure': 'Rules defining quality benchmarks and performance metrics.',
            'regulatory': 'Rules mandated by federal and state healthcare regulations.',
            'reporting': 'Rules requiring reporting to oversight bodies, registries, or public health agencies.',
            'unknown': 'Rules without a specified category.',
        }
    elif domain == 'aml':
        descriptions = {
            'reporting': 'Rules requiring reports to financial intelligence units or regulators.',
            'monitoring': 'Rules for ongoing surveillance of transactions and customer activity.',
            'screening': 'Rules for checking customers and transactions against watchlists.',
            'eligibility': 'Rules defining customer or product eligibility criteria.',
            'constraint': 'Rules that specify limits or restrictions on financial activities.',
            'compliance': 'Rules ensuring adherence to AML/CFT regulatory requirements.',
            'documentation': 'Rules specifying required records and documentation.',
            'process': 'Rules defining AML operational workflows and procedures.',
            'calculation': 'Rules for computing risk scores and financial metrics.',
            'validation': 'Rules that verify data accuracy and consistency.',
            'unknown': 'Rules without a specified category.',
        }
    elif domain == 'commercial_lending':
        descriptions = {
            'credit_policy': 'Rules governing credit assessment and lending decisions.',
            'collateral': 'Rules specifying collateral requirements, valuation, and perfection.',
            'covenant': 'Rules defining financial and operational covenants for borrowers.',
            'regulatory': 'Rules mandated by banking regulations and supervisory guidance.',
            'documentation': 'Rules specifying required loan documents and record-keeping.',
            'underwriting': 'Rules defining underwriting standards and approval criteria.',
            'risk_assessment': 'Rules for evaluating and quantifying credit and portfolio risk.',
            'compliance': 'Rules ensuring adherence to lending laws and internal policies.',
            'pricing': 'Rules governing interest rates, fees, and loan pricing.',
            'reporting': 'Rules requiring reporting to regulators or internal stakeholders.',
            'unknown': 'Rules without a specified category.',
        }
    else:
        descriptions = {
            'eligibility': 'Rules that define qualification criteria and requirements for loans, borrowers, or properties.',
            'constraint': 'Rules that specify limits, thresholds, or restrictions on values and conditions.',
            'compliance': 'Rules ensuring adherence to regulatory requirements and Fannie Mae policies.',
            'validation': 'Rules that verify data accuracy, completeness, and consistency.',
            'documentation': 'Rules specifying required documents, forms, and record-keeping requirements.',
            'process': 'Rules defining workflows, sequences, and operational procedures.',
            'calculation': 'Rules for computing values, ratios, and financial metrics.',
            'prohibition': 'Rules that explicitly forbid certain actions or conditions.',
            'definition': 'Rules that establish definitions and terminology.',
            'exception': 'Rules that define exceptions to standard requirements.',
            'unknown': 'Rules without a specified category.',
        }
    return descriptions.get(rule_type, 'Business rules in this category.')


def _lighten_color(hex_color):
    """Lighten a hex color by mixing with white."""
    # Remove # if present
    hex_color = hex_color.lstrip('#')
    
    # Convert to RGB
    r = int(hex_color[0:2], 16)
    g = int(hex_color[2:4], 16)
    b = int(hex_color[4:6], 16)
    
    # Mix with white (blend 60% original, 40% white)
    r = int(r * 0.6 + 255 * 0.4)
    g = int(g * 0.6 + 255 * 0.4)
    b = int(b * 0.6 + 255 * 0.4)
    
    return f'#{r:02x}{g:02x}{b:02x}'


def _get_logo_base64() -> str:
    """Load logo.svg as a base64-encoded data URI."""
    logo_path = Path(__file__).parent.parent / 'logo.svg'
    if logo_path.exists():
        with open(logo_path, 'rb') as f:
            encoded = base64.b64encode(f.read()).decode('utf-8')
        return f'data:image/png;base64,{encoded}'
    return ''


def generate_html_content(data, rules, entity_types, entity_definitions):
    """Generate the actual HTML content (legacy function maintained for compatibility)."""
    import re as _re
    from utils.config import get_config

    config = get_config()
    source_file = config.get_source_file_name() or config.get_batch_name()

    def _norm_key(s: str) -> str:
        return _re.sub(r'[\s\-]+', '_', s.strip().upper())

    # Build normalized lookup so Agent-3 entity names (mixed case/spaces) resolve
    # to Agent-2 schema definitions (UPPER_SNAKE_CASE) when exact key is missing.
    _entity_def_norm = {_norm_key(k): v for k, v in entity_definitions.items()}

    def _get_entity_def(name: str) -> dict:
        return entity_definitions.get(name) or _entity_def_norm.get(_norm_key(name), {})

    metadata = data.get('metadata', {})
    optimization_summary = data.get('optimization_summary', {})
    
    # Calculate confidence statistics
    confidence_scores = [r.get('confidence_score', 0) for r in rules if r.get('confidence_score', 0) > 0]
    avg_confidence = sum(confidence_scores) / len(confidence_scores) if confidence_scores else 0
    low_confidence_count = sum(1 for r in rules if r.get('confidence_score', 0) < 70 and r.get('confidence_score', 0) > 0)
    
    # Build dependency graph data with RULE TYPES as nodes AND individual rules
    nodes = []
    edges = []
    node_ids = set()
    
    # Group rules by type
    rules_by_type = {}
    for rule in rules:
        rule_type = rule.get('rule_type', 'unknown')
        if rule_type not in rules_by_type:
            rules_by_type[rule_type] = []
        rules_by_type[rule_type].append(rule)
    
    # Colors for different rule types — domain-aware (mortgage vs AML)
    rule_type_colors = config.get_rule_type_colors()
    
    # Add rule type nodes (larger, central nodes)
    for rule_type, type_rules in rules_by_type.items():
        node_id = f"type_{rule_type}"
        color = rule_type_colors.get(rule_type, '#64748b')
        
        nodes.append({
            'id': node_id,
            'label': f"{rule_type.title()}",
            'title': f"{rule_type.title()}: {len(type_rules)} rules",
            'group': 'rule_type',
            'value': 60 + len(type_rules) * 2,  # Large size based on rule count
            'color': {
                'background': color,
                'border': color,
                'highlight': {
                    'background': color,
                    'border': '#ffffff'
                }
            },
            'font': {'color': '#ffffff', 'size': 20, 'bold': True},
            'rule_count': len(type_rules),
            'rule_type': rule_type,
            'shape': 'box',
            'margin': 15
        })
        node_ids.add(node_id)
    
    # Add individual rule nodes (smaller, satellite nodes)
    rule_id_counter = {}  # Track duplicate IDs
    for idx, rule in enumerate(rules):
        rule['_rule_index'] = idx  # Store index for JS lookup
        rule_id = rule.get('rule_id', '')
        rule_type = rule.get('rule_type', 'unknown')
        rule_name = rule.get('rule_name', rule_id)
        color = rule_type_colors.get(rule_type, '#64748b')
        
        # Handle duplicate rule IDs by adding a unique suffix
        unique_rule_id = rule_id
        if rule_id in node_ids:
            # This is a duplicate, add a counter suffix
            if rule_id not in rule_id_counter:
                rule_id_counter[rule_id] = 1
            else:
                rule_id_counter[rule_id] += 1
            unique_rule_id = f"{rule_id}_dup{rule_id_counter[rule_id]}"
        
        # Make color lighter for individual rules
        lighter_color = _lighten_color(color)
        
        reference = rule.get('source_reference', rule.get('fannie_mae_reference', ''))
        # Format structured source_reference for tooltip
        if isinstance(reference, dict):
            ref_display = reference.get('chunk_path', '')
            sec = reference.get('section_id', '')
            if sec and sec != 'N/A':
                ref_display += f" | {sec}"
            wp_start = reference.get('start_word_position', '')
            wp_end = reference.get('end_word_position', '')
            if isinstance(wp_start, int) and isinstance(wp_end, int):
                ref_display += f" [words {wp_start}-{wp_end}]"
            ref_verified = rule.get('reference_verified', None)
            if ref_verified is True:
                ref_display += " ✓"
            elif ref_verified is False:
                ref_display += " ✗"
        elif isinstance(reference, list):
            # Multiple merged references
            parts = []
            for r in reference:
                if isinstance(r, dict):
                    parts.append(r.get('chunk_path', ''))
                else:
                    parts.append(str(r))
            ref_display = '; '.join(parts)
        else:
            ref_display = str(reference) if reference else ''
        ref_line = f"\nRef: {ref_display}" if ref_display else ""
        risk_level = rule.get('risk_level', '')
        risk_line = f"\nRisk: {risk_level}" if risk_level else ""
        jurisdiction = rule.get('jurisdiction', '')
        jurisdiction_line = f"\nJurisdiction: {jurisdiction}" if jurisdiction else ""
        
        nodes.append({
            'id': unique_rule_id,
            'label': rule_id,  # Display original ID
            'title': f"{rule_id}: {rule_name}\nType: {rule_type}\nMandatory: {rule.get('mandatory', False)}{ref_line}{risk_line}{jurisdiction_line}",
            'group': f'rule_{rule_type}',
            'value': 15,  # Smaller size for individual rules
            'color': {
                'background': lighter_color,
                'border': color,
                'highlight': {
                    'background': color,
                    'border': '#ffffff'
                }
            },
            'font': {'color': '#1e293b', 'size': 10},
            'rule_type': rule_type,
            'mandatory': rule.get('mandatory', False),
            'shape': 'dot',
            'original_rule_id': rule_id,  # Store original ID for reference
            '_rule_index': idx  # Index into rulesData for click lookup
        })
        node_ids.add(unique_rule_id)
        
        # Update rule with unique ID for dependency matching
        rule['_unique_id'] = unique_rule_id
        
        # Add edge from rule to its type category
        type_node_id = f"type_{rule_type}"
        edges.append({
            'from': type_node_id,
            'to': unique_rule_id,
            'type': 'category',
            'color': {
                'color': color + '40',  # Semi-transparent
                'highlight': color
            },
            'width': 1,
            'smooth': {
                'enabled': True,
                'type': 'curvedCW',
                'roundness': 0.2
            },
            'dashes': False
        })
    
    # Add dependency edges between individual rules
    dependency_count = 0
    
    # Create a map of original rule IDs to unique IDs for dependency matching
    rule_id_map = {rule.get('rule_id', ''): rule.get('_unique_id', rule.get('rule_id', '')) for rule in rules}
    
    for rule in rules:
        rule_unique_id = rule.get('_unique_id', rule.get('rule_id', ''))
        dependencies = rule.get('dependencies', [])
        
        for dep in dependencies:
            dep_rule_id = dep.get('depends_on_rule', '')
            dep_type = dep.get('dependency_type', 'related')
            
            # Map the dependency to its unique ID
            dep_unique_id = rule_id_map.get(dep_rule_id, dep_rule_id)
            
            if dep_unique_id and dep_unique_id in node_ids:
                # Color by dependency type - using distinct warm/earthy tones to differentiate from rule types
                dep_colors = {
                    'prerequisite': '#b91c1c',      # Dark red
                    'sequential': '#7c2d12',        # Dark brown/orange
                    'conditional': '#ca8a04',       # Dark gold
                    'complementary': '#059669',     # Dark teal
                    'contradictory': '#5b21b6',     # Dark purple
                    'override': '#be185d',          # Dark pink/magenta
                    'validation': '#0e7490'         # Dark cyan
                }
                
                edges.append({
                    'from': dep_unique_id,
                    'to': rule_unique_id,
                    'type': dep_type,
                    'color': {
                        'color': dep_colors.get(dep_type, '#64748b'),
                        'highlight': dep_colors.get(dep_type, '#64748b')
                    },
                    'width': 3,
                    'label': dep_type,
                    'arrows': {
                        'to': {
                            'enabled': True,
                            'scaleFactor': 1.2
                        }
                    },
                    'font': {
                        'size': 11,
                        'align': 'middle',
                        'background': '#ffffff',
                        'strokeWidth': 2,
                        'strokeColor': '#ffffff'
                    },
                    'smooth': {
                        'enabled': True,
                        'type': 'curvedCW',
                        'roundness': 0.3
                    }
                })
                dependency_count += 1
    
    # ── Add Entity nodes and entity-to-rule edges ──
    # Group rules by entity_or_relationship to create entity nodes
    rules_by_entity = {}
    for rule in rules:
        entity_name = rule.get('entity_or_relationship', '')
        if entity_name:
            if entity_name not in rules_by_entity:
                rules_by_entity[entity_name] = []
            rules_by_entity[entity_name].append(rule)

    # Entity node color palette (distinct from rule type colors)
    entity_node_color = '#0d9488'       # Teal-600
    entity_node_border = '#0f766e'      # Teal-700
    entity_node_light = '#99f6e4'       # Teal-200

    for entity_name, entity_rules in rules_by_entity.items():
        entity_node_id = f"entity_{entity_name}"
        # Look up entity definition for tooltip
        entity_def = _get_entity_def(entity_name)
        entity_desc = entity_def.get('description', '') if isinstance(entity_def, dict) else ''
        entity_kind = entity_def.get('type', '') if isinstance(entity_def, dict) else ''
        tooltip_lines = [f"{entity_name}", f"Connected rules: {len(entity_rules)}"]
        if entity_kind:
            tooltip_lines.insert(1, f"Kind: {entity_kind}")
        if entity_desc:
            tooltip_lines.append(f"Description: {entity_desc[:120]}")

        nodes.append({
            'id': entity_node_id,
            'label': entity_name.replace('_', ' ').title()[:30],
            'title': '\n'.join(tooltip_lines),
            'group': 'entity',
            'value': 30 + len(entity_rules) * 3,
            'color': {
                'background': entity_node_color,
                'border': entity_node_border,
                'highlight': {
                    'background': entity_node_light,
                    'border': entity_node_border
                }
            },
            'font': {'color': '#ffffff', 'size': 12, 'bold': True},
            'shape': 'diamond',
            'entity_name': entity_name,
            'rule_count': len(entity_rules),
        })
        node_ids.add(entity_node_id)

        # Edges from entity node to each connected rule
        for rule in entity_rules:
            rule_unique_id = rule.get('_unique_id', rule.get('rule_id', ''))
            if rule_unique_id in node_ids:
                edges.append({
                    'from': entity_node_id,
                    'to': rule_unique_id,
                    'type': 'entity_rule',
                    'color': {
                        'color': entity_node_color + '30',  # Very transparent
                        'highlight': entity_node_color
                    },
                    'width': 1,
                    'smooth': {
                        'enabled': True,
                        'type': 'curvedCCW',
                        'roundness': 0.15
                    },
                    'dashes': [4, 4],
                    'arrows': {
                        'to': {
                            'enabled': True,
                            'scaleFactor': 0.6
                        }
                    }
                })

    entity_count = len(rules_by_entity)

    # Build entity cards HTML
    entity_cards_html = []
    for entity_name, entity_rules in sorted(rules_by_entity.items(), key=lambda x: len(x[1]), reverse=True)[:20]:
        entity_def = _get_entity_def(entity_name)
        entity_desc = entity_def.get('description', 'No definition available.') if isinstance(entity_def, dict) else 'No definition available.'
        entity_kind = entity_def.get('type', '') if isinstance(entity_def, dict) else ''
        sample_items = ''.join([
            f'<li><strong>{rule.get("rule_id", "")}</strong>: {rule.get("rule_name", "")[:60]}{"..." if len(rule.get("rule_name", "")) > 60 else ""}</li>'
            for rule in entity_rules[:5]
        ])
        more_text = f'<p style="color: #64748b; font-style: italic; margin-top: 10px;">...and {len(entity_rules) - 5} more rules</p>' if len(entity_rules) > 5 else ''
        kind_badge = f'<span class="badge" style="background: #0d948820; color: #0d9488; margin-left: 5px;">{entity_kind}</span>' if entity_kind else ''

        card_html = f'''<div class="entity-card" style="border-left: 4px solid {entity_node_color}">
                    <div class="entity-card-header">
                        <h3 style="color: {entity_node_color}">{entity_name.replace('_', ' ').title()}{kind_badge}</h3>
                        <div>
                            <span class="badge" style="background: {entity_node_color}20; color: {entity_node_color};">
                                {len(entity_rules)} rules
                            </span>
                        </div>
                    </div>
                    <div class="entity-card-content">
                        <p class="entity-definition">{entity_desc[:200]}</p>
                        <div class="rule-samples"><strong>Connected Rules:</strong><ul style="margin-top: 8px;">{sample_items}</ul>{more_text}</div>
                    </div>
                </div>'''
        entity_cards_html.append(card_html)

    entity_cards_html_str = '\n'.join(entity_cards_html)

    # Build rule type cards HTML
    rule_type_cards_html = []
    for rule_type, type_rules in sorted(rules_by_type.items(), key=lambda x: len(x[1]), reverse=True):
        color = rule_type_colors.get(rule_type, '#64748b')
        
        # Count mandatory rules
        mandatory_count = sum(1 for r in type_rules if r.get('mandatory', False))
        
        # Sample rules (show first 5)
        sample_rules_html = ''
        if type_rules:
            sample_items = ''.join([
                f'<li><strong>{rule.get("rule_id", "")}</strong>: {rule.get("rule_name", "")[:60]}{"..." if len(rule.get("rule_name", "")) > 60 else ""}</li>'
                for rule in type_rules[:5]
            ])
            more_text = f'<p style="color: #64748b; font-style: italic; margin-top: 10px;">...and {len(type_rules) - 5} more rules</p>' if len(type_rules) > 5 else ''
            sample_rules_html = f'<div class="rule-samples"><strong>Sample Rules:</strong><ul style="margin-top: 8px;">{sample_items}</ul>{more_text}</div>'
        
        card_html = f'''<div class="entity-card" style="border-left: 4px solid {color}">
                    <div class="entity-card-header">
                        <h3 style="color: {color}">{rule_type.title()}</h3>
                        <div>
                            <span class="badge" style="background: {color}20; color: {color}; margin-right: 5px;">
                                {len(type_rules)} rules
                            </span>
                            <span class="badge" style="background: #ef444420; color: #ef4444;">
                                {mandatory_count} mandatory
                            </span>
                        </div>
                    </div>
                    <div class="entity-card-content">
                        <p class="entity-definition">
                            {_get_rule_type_description(rule_type)}
                        </p>
                        {sample_rules_html}
                    </div>
                </div>'''
        rule_type_cards_html.append(card_html)
    
    rule_type_cards_html_str = '\n'.join(rule_type_cards_html)

    # Build domain-aware legend items and quick-filter buttons
    rule_type_legend_html = '\n'.join(
        f'<div class="legend-item">'
        f'<div class="legend-color" style="background: {color};"></div>'
        f'<span class="legend-label">{rule_type.title()}</span>'
        f'</div>'
        for rule_type, color in rule_type_colors.items()
        if rule_type != 'unknown'
    )
    filter_buttons_html = '\n'.join(
        f'<button class="filter-btn" data-filter="{rt}" data-filter-type="rule">{rt.title()}</button>'
        for rt in config.get_domain_priority_filter_types()
    )

    # Load logo
    logo_data_uri = _get_logo_base64()
    
    # Build page title with source document info
    page_title = "Knowledge Graph Visualization"
    if source_file:
        page_title = f"{source_file} - Knowledge Graph Visualization"
    
    # Generate HTML
    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{page_title}</title>
    <script src="https://unpkg.com/vis-network/standalone/umd/vis-network.min.js"></script>
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}
        
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: #1e293b;
            line-height: 1.6;
        }}
        
        .container {{
            max-width: 1600px;
            margin: 0 auto;
            padding: 20px;
        }}
        
        header {{
            background: white;
            border-radius: 16px;
            padding: 30px;
            margin-bottom: 20px;
            box-shadow: 0 10px 30px rgba(0, 0, 0, 0.1);
        }}
        
        .logo-container {{
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 1.5rem;
            margin-bottom: 1.5rem;
        }}
        
        .source-logo {{
            background: white;
            padding: 1rem 2rem;
            border-radius: 12px;
            box-shadow: 0 4px 12px rgba(0,0,0,0.15);
            display: inline-flex;
            align-items: center;
            gap: 0.5rem;
        }}
        
        .source-logo svg {{
            flex-shrink: 0;
        }}
        
        .logo-text {{
            font-size: 1.8rem;
            font-weight: bold;
            color: #003d7a;
            font-family: 'Arial', sans-serif;
            line-height: 1.2;
        }}
        
        h1 {{
            font-size: 2.5em;
            font-weight: 700;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            margin-bottom: 10px;
        }}
        
        .subtitle {{
            color: #64748b;
            font-size: 1.1em;
        }}
        
        .stats {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 15px;
            margin-top: 20px;
        }}
        
        .stat-card {{
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 20px;
            border-radius: 12px;
            text-align: center;
        }}
        
        .stat-value {{
            font-size: 2.5em;
            font-weight: 700;
            margin-bottom: 5px;
        }}
        
        .stat-label {{
            font-size: 0.9em;
            opacity: 0.9;
        }}
        
        .graph-container {{
            background: white;
            border-radius: 16px;
            padding: 20px;
            margin-bottom: 20px;
            box-shadow: 0 10px 30px rgba(0, 0, 0, 0.1);
        }}
        
        .section-title {{
            font-size: 1.8em;
            font-weight: 600;
            margin-bottom: 15px;
            color: #1e293b;
        }}
        
        #network {{
            width: 100%;
            height: 700px;
            border: 2px solid #e2e8f0;
            border-radius: 12px;
            background: #f8fafc;
        }}
        
        .legend {{
            display: flex;
            flex-wrap: wrap;
            gap: 20px;
            margin-top: 20px;
            padding: 20px;
            background: #f8fafc;
            border-radius: 12px;
        }}
        
        .legend-item {{
            display: flex;
            align-items: center;
            gap: 8px;
        }}
        
        .legend-color {{
            width: 20px;
            height: 20px;
            border-radius: 4px;
        }}
        
        .legend-label {{
            font-size: 0.9em;
            color: #475569;
        }}
        
        .entity-definitions-container {{
            background: white;
            border-radius: 12px;
            padding: 30px;
            margin: 30px 0;
            box-shadow: 0 2px 8px rgba(0,0,0,0.08);
        }}
        
        .entity-cards {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(400px, 1fr));
            gap: 20px;
            margin-top: 20px;
        }}
        
        .entity-card {{
            background: white;
            border: 1px solid #e2e8f0;
            border-radius: 8px;
            padding: 20px;
            transition: transform 0.2s, box-shadow 0.2s;
        }}
        
        .entity-card:hover {{
            transform: translateY(-2px);
            box-shadow: 0 4px 12px rgba(0,0,0,0.1);
        }}
        
        .entity-card-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 15px;
            padding-bottom: 15px;
            border-bottom: 2px solid #f1f5f9;
        }}
        
        .entity-card-header h3 {{
            margin: 0;
            font-size: 20px;
            font-weight: 600;
        }}
        
        .entity-card-content {{
            font-size: 14px;
            line-height: 1.6;
        }}
        
        .entity-definition {{
            color: #334155;
            margin-bottom: 15px;
            font-style: italic;
        }}
        
        .entity-attributes {{
            margin: 10px 0;
            padding: 10px;
            background: #f8fafc;
            border-radius: 6px;
            color: #475569;
        }}
        
        .entity-examples {{
            margin-top: 15px;
        }}
        
        .entity-examples strong {{
            color: #1e293b;
        }}
        
        .entity-examples ul {{
            margin: 8px 0 0 0;
            padding-left: 20px;
        }}
        
        .entity-examples li {{
            color: #64748b;
            margin: 5px 0;
        }}
        
        .controls {{
            display: flex;
            gap: 15px;
            margin-bottom: 20px;
            flex-wrap: wrap;
        }}
        
        .search-box {{
            flex: 1;
            min-width: 300px;
            padding: 12px 20px;
            font-size: 1em;
            border: 2px solid #e2e8f0;
            border-radius: 8px;
            transition: all 0.3s;
        }}
        
        .search-box:focus {{
            outline: none;
            border-color: #667eea;
            box-shadow: 0 0 0 3px rgba(102, 126, 234, 0.1);
        }}
        
        .filter-btn {{
            padding: 12px 24px;
            background: white;
            border: 2px solid #e2e8f0;
            border-radius: 8px;
            cursor: pointer;
            transition: all 0.3s;
            font-weight: 500;
        }}
        
        .filter-btn:hover {{
            border-color: #667eea;
            color: #667eea;
            transform: translateY(-2px);
        }}
        
        .filter-btn.active {{
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            border-color: transparent;
        }}
        
        .table-container {{
            background: white;
            border-radius: 16px;
            padding: 20px;
            box-shadow: 0 10px 30px rgba(0, 0, 0, 0.1);
            overflow-x: auto;
        }}
        
        table {{
            width: 100%;
            border-collapse: separate;
            border-spacing: 0;
            table-layout: fixed;
            min-width: 2800px;
        }}
        
        /* Column widths for all 14 columns */
        th:nth-child(1), td:nth-child(1) {{ width: 160px; min-width: 160px; }}   /* Rule ID */
        th:nth-child(2), td:nth-child(2) {{ width: 200px; min-width: 200px; }}   /* Rule Name */
        th:nth-child(3), td:nth-child(3) {{ width: 110px; min-width: 110px; }}   /* Type */
        th:nth-child(4), td:nth-child(4) {{ width: 300px; min-width: 300px; }}   /* Description */
        th:nth-child(5), td:nth-child(5) {{ width: 90px;  min-width: 90px;  }}   /* Confidence */
        th:nth-child(6), td:nth-child(6) {{ width: 90px;  min-width: 90px;  }}   /* Mandatory */
        th:nth-child(7), td:nth-child(7) {{ width: 80px;  min-width: 80px;  }}   /* Risk */
        th:nth-child(8), td:nth-child(8) {{ width: 130px; min-width: 130px; }}   /* Jurisdiction */
        th:nth-child(9), td:nth-child(9) {{ width: 160px; min-width: 160px; }}   /* Scope */
        th:nth-child(10), td:nth-child(10) {{ width: 200px; min-width: 200px; }} /* Dependencies */
        th:nth-child(11), td:nth-child(11) {{ width: 350px; min-width: 350px; }} /* Dependency Evidence */
        th:nth-child(12), td:nth-child(12) {{ width: 300px; min-width: 300px; }} /* Reference */
        th:nth-child(13), td:nth-child(13) {{ width: 160px; min-width: 160px; }} /* Enforcement */
        th:nth-child(14), td:nth-child(14) {{ width: 110px; min-width: 110px; }} /* Audit */
        
        thead {{
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
        }}
        
        th {{
            padding: 15px 12px;
            text-align: left;
            font-weight: 600;
            position: sticky;
            top: 0;
            z-index: 10;
            font-size: 0.9em;
            background: inherit;
            box-sizing: border-box;
        }}
        
        td {{
            padding: 12px 12px;
            border-bottom: 1px solid #e2e8f0;
            word-wrap: break-word;
            overflow-wrap: break-word;
            hyphens: auto;
            vertical-align: top;
            box-sizing: border-box;
            overflow: hidden;
            text-overflow: ellipsis;
        }}
        
        /* Specific styling for dependencies column */
        td:nth-child(10) {{
            overflow: visible;
        }}
        
        /* Specific styling for dependency evidence column */
        td:nth-child(11) {{
            overflow: visible;
        }}
        
        tbody tr {{
            transition: all 0.2s;
        }}
        
        tbody tr:hover {{
            background: #f8fafc;
            transform: scale(1.01);
            box-shadow: 0 4px 12px rgba(0, 0, 0, 0.05);
        }}
        
        .rule-id {{
            font-weight: 600;
            color: #667eea;
        }}
        
        .badge {{
            display: inline-block;
            padding: 4px 10px;
            border-radius: 20px;
            font-size: 0.75em;
            font-weight: 600;
            white-space: nowrap;
            text-align: center;
        }}
        
        .badge-eligibility {{ background: #dbeafe; color: #1e40af; }}
        .badge-constraint {{ background: #fee2e2; color: #991b1b; }}
        .badge-calculation {{ background: #cffafe; color: #155e75; }}
        .badge-validation {{ background: #fef3c7; color: #92400e; }}
        .badge-process {{ background: #fce7f3; color: #9f1239; }}
        .badge-compliance {{ background: #d1fae5; color: #065f46; }}
        .badge-documentation {{ background: #f3e8ff; color: #6b21a8; }}
        .badge-prohibition {{ background: #fecaca; color: #7f1d1d; }}
        .badge-definition {{ background: #e0e7ff; color: #3730a3; }}
        .badge-exception {{ background: #ffedd5; color: #9a3412; }}
        
        .badge-mandatory {{ background: #dc2626; color: white; }}
        .badge-optional {{ background: #64748b; color: white; }}
        
        .entity-badge {{
            display: inline-block;
            padding: 6px 14px;
            border-radius: 6px;
            font-size: 0.9em;
            font-weight: 600;
            border: 2px solid;
        }}
        
        .entity-MortgageLoan {{ background: #dbeafe; color: #1e40af; border-color: #3b82f6; }}
        .entity-MBS_Trade {{ background: #fee2e2; color: #991b1b; border-color: #ef4444; }}
        .entity-MortgageBackedSecurity {{ background: #d1fae5; color: #065f46; border-color: #10b981; }}
        .entity-MBSLoan {{ background: #fef3c7; color: #92400e; border-color: #f59e0b; }}
        .entity-MBS_Loan {{ background: #f3e8ff; color: #6b21a8; border-color: #8b5cf6; }}
        .entity-ARM_MBS_Pool {{ background: #fce7f3; color: #9f1239; border-color: #ec4899; }}
        
        .dependency-badge {{
            display: inline-block;
            padding: 3px 6px;
            margin: 2px 2px 2px 0;
            border-radius: 3px;
            font-size: 0.7em;
            font-weight: 600;
            white-space: normal;
            max-width: 100%;
            word-break: break-word;
            line-height: 1.4;
        }}
        
        .dep-prerequisite {{ background: #f3e8ff; color: #6b21a8; }}
        .dep-sequential {{ background: #cffafe; color: #155e75; }}
        .dep-conditional {{ background: #fed7aa; color: #9a3412; }}
        .dep-complementary {{ background: #d1fae5; color: #065f46; }}
        .dep-contradictory {{ background: #fce7f3; color: #831843; }}
        .dep-override {{ background: #fef3c7; color: #92400e; }}
        .dep-validation {{ background: #e0f2fe; color: #075985; }}
        
        .confidence-high {{ background: #d1fae5; color: #065f46; font-weight: 600; }}
        .confidence-medium {{ background: #fef3c7; color: #92400e; font-weight: 600; }}
        .confidence-low {{ background: #fee2e2; color: #991b1b; font-weight: 600; }}
        .confidence-unknown {{ background: #f1f5f9; color: #64748b; font-weight: 600; }}
        
        .detail-cell {{
            white-space: normal;
            line-height: 1.5;
            color: #334155;
            font-size: 0.9em;
            word-break: break-word;
            overflow-wrap: break-word;
            max-width: 100%;
            overflow: hidden;
        }}
        
        .dependency-evidence-cell {{
            font-size: 0.85em;
            line-height: 1.6;
            background: #f8fafc;
            padding: 10px;
            word-break: break-word;
            overflow-wrap: break-word;
            max-width: 100%;
            overflow: hidden;
            position: relative;
        }}
        
        .dep-evidence {{
            margin-bottom: 10px;
            padding: 10px;
            background: white;
            border-left: 3px solid #3b82f6;
            border-radius: 4px;
            word-break: break-word;
            overflow-wrap: break-word;
        }}
        
        .dep-evidence strong {{
            color: #1e40af;
            font-size: 0.95em;
            display: block;
            margin-bottom: 6px;
            word-break: break-word;
        }}
        
        .dep-evidence em {{
            color: #64748b;
            font-weight: 600;
            font-style: normal;
            margin-right: 4px;
        }}
        
        .rule-id {{
            font-family: 'Courier New', monospace;
            font-weight: 600;
            color: #667eea;
            font-size: 0.85em;
            word-break: break-all;
        }}
        
        .no-results {{
            text-align: center;
            padding: 40px;
            color: #64748b;
            font-size: 1.2em;
        }}
        
        /* ── Detail Modal ── */
        .modal-overlay {{
            display: none;
            position: fixed;
            inset: 0;
            background: rgba(0,0,0,0.55);
            z-index: 9999;
            justify-content: center;
            align-items: flex-start;
            padding: 40px 20px;
            overflow-y: auto;
        }}
        .modal-overlay.active {{
            display: flex;
        }}
        .modal {{
            background: white;
            border-radius: 16px;
            max-width: 960px;
            width: 100%;
            box-shadow: 0 25px 60px rgba(0,0,0,0.3);
            position: relative;
            animation: modalIn 0.2s ease;
        }}
        @keyframes modalIn {{
            from {{ opacity: 0; transform: translateY(-20px); }}
            to   {{ opacity: 1; transform: translateY(0); }}
        }}
        .modal-header {{
            padding: 24px 28px 16px;
            border-bottom: 2px solid #f1f5f9;
            display: flex;
            justify-content: space-between;
            align-items: flex-start;
        }}
        .modal-header h2 {{
            margin: 0;
            font-size: 1.3em;
            color: #1e293b;
            word-break: break-word;
        }}
        .modal-header .modal-close {{
            background: none;
            border: none;
            font-size: 1.6em;
            cursor: pointer;
            color: #94a3b8;
            padding: 0 4px;
            line-height: 1;
        }}
        .modal-header .modal-close:hover {{ color: #ef4444; }}
        .modal-body {{
            padding: 20px 28px 28px;
            max-height: 75vh;
            overflow-y: auto;
        }}
        .modal-section {{
            margin-bottom: 20px;
        }}
        .modal-section-title {{
            font-weight: 700;
            font-size: 0.85em;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            color: #667eea;
            margin-bottom: 8px;
            padding-bottom: 4px;
            border-bottom: 1px solid #e2e8f0;
        }}
        .modal-grid {{
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 10px 24px;
        }}
        .modal-field {{
            margin-bottom: 6px;
        }}
        .modal-field-label {{
            font-size: 0.78em;
            font-weight: 600;
            color: #64748b;
            text-transform: uppercase;
            letter-spacing: 0.03em;
        }}
        .modal-field-value {{
            font-size: 0.92em;
            color: #1e293b;
            line-height: 1.5;
            word-break: break-word;
        }}
        .modal-field-value.mono {{
            font-family: 'Courier New', monospace;
            font-size: 0.85em;
        }}
        .modal-tags {{
            display: flex;
            flex-wrap: wrap;
            gap: 4px;
        }}
        .modal-tag {{
            display: inline-block;
            padding: 2px 8px;
            border-radius: 4px;
            font-size: 0.78em;
            background: #f1f5f9;
            color: #475569;
        }}
        .source-text-block {{
            background: #f8fafc;
            border: 1px solid #e2e8f0;
            border-radius: 8px;
            padding: 14px;
            font-size: 0.9em;
            line-height: 1.7;
            color: #334155;
            white-space: pre-wrap;
            word-break: break-word;
            max-height: 300px;
            overflow-y: auto;
        }}
        .source-text-block mark {{
            background: #fde68a;
            color: #92400e;
            padding: 1px 2px;
            border-radius: 2px;
            font-weight: 600;
        }}
        .confidence-bar {{
            display: flex;
            align-items: center;
            gap: 8px;
            margin: 3px 0;
        }}
        .confidence-bar-label {{
            width: 140px;
            font-size: 0.8em;
            color: #64748b;
        }}
        .confidence-bar-track {{
            flex: 1;
            height: 8px;
            background: #e2e8f0;
            border-radius: 4px;
            overflow: hidden;
        }}
        .confidence-bar-fill {{
            height: 100%;
            border-radius: 4px;
            transition: width 0.3s;
        }}
        .confidence-bar-value {{
            width: 36px;
            font-size: 0.8em;
            font-weight: 600;
            text-align: right;
        }}
        .clickable-rule-id {{
            cursor: pointer;
            text-decoration: underline;
            color: #667eea;
        }}
        .clickable-rule-id:hover {{
            color: #4f46e5;
        }}
        
        @media (max-width: 768px) {{
            .stats {{
                grid-template-columns: 1fr;
            }}
            
            .controls {{
                flex-direction: column;
            }}
            
            .search-box {{
                min-width: 100%;
            }}
            
            /* Make table scrollable on small screens */
            .table-container {{
                overflow-x: auto;
                -webkit-overflow-scrolling: touch;
            }}
            
            table {{
                min-width: 2800px;
            }}
            
            .logo-container {{
                flex-direction: column;
                gap: 1rem;
            }}
            
            .source-logo svg {{
                width: 70px;
                height: 70px;
            }}
            
            .logo-text {{
                font-size: 1.4rem;
            }}
            
            .modal-grid {{
                grid-template-columns: 1fr;
            }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <header>
            <div class="logo-container">
                <div class="source-logo">
                    <img src="{logo_data_uri}" alt="Policy to Knowledge" style="height: 80px; width: auto;" />
                    <div style="display: flex; flex-direction: column; align-items: flex-start;">
                        <span class="logo-text">{source_file if source_file else 'Policy to Knowledge'}</span>
                        <span style="font-size: 0.8rem; color: #666; font-weight: normal;">Compliance Knowledge Graph</span>
                    </div>
                </div>
            </div>
            <h1>Knowledge Graph{f' – {source_file}' if source_file else ''}</h1>
            <p class="subtitle">Interactive visualization of business rules, entities, and dependencies{f' extracted from {source_file}' if source_file else ''}</p>
            
            <div class="stats">
                <div class="stat-card">
                    <div class="stat-value">{len(rules)}</div>
                    <div class="stat-label">Business Rules</div>
                </div>
                <div class="stat-card">
                    <div class="stat-value">{metadata.get('dependencies_added_count', 0)}</div>
                    <div class="stat-label">Dependencies</div>
                </div>
                <div class="stat-card">
                    <div class="stat-value">{avg_confidence:.0f}/100</div>
                    <div class="stat-label">Avg Confidence</div>
                </div>
                <div class="stat-card">
                    <div class="stat-value">{low_confidence_count}</div>
                    <div class="stat-label">Low Confidence (&lt;70)</div>
                </div>
                <div class="stat-card">
                    <div class="stat-value">{metadata.get('rules_removed_count', 0)}</div>
                    <div class="stat-label">Duplicates Removed</div>
                </div>
            </div>
        </header>
        
        <div class="graph-container">
            <h2 class="section-title">📊 Knowledge Graph Network</h2>
            <p style="color: #64748b; margin-bottom: 15px; text-align: center;">
                Large colored boxes represent rule categories • Diamonds represent entities • Small dots represent individual business rules • Dashed arrows connect entities to their rules • Solid arrows show dependencies
            </p>
            <div id="network"></div>
            
            <div class="legend">
                <div style="font-weight: 600; width: 100%; margin-bottom: 10px;">Node Types:</div>
                <div class="legend-item">
                    <div class="legend-color" style="background: #3b82f6; width: 30px; height: 30px; border-radius: 4px;"></div>
                    <span class="legend-label">Rule Type Category (Large Box)</span>
                </div>
                <div class="legend-item">
                    <div class="legend-color" style="background: #0d9488; width: 22px; height: 22px; transform: rotate(45deg); border-radius: 2px;"></div>
                    <span class="legend-label">Entity / Relationship (Diamond) — {entity_count} entities</span>
                </div>
                <div class="legend-item">
                    <div class="legend-color" style="background: #93c5fd; width: 15px; height: 15px; border-radius: 50%; border: 2px solid #3b82f6;"></div>
                    <span class="legend-label">Individual Business Rule (Small Dot)</span>
                </div>
            </div>
            
            <div class="legend">
                <div style="font-weight: 600; width: 100%; margin-bottom: 10px;">Dependency Types:</div>
                <div class="legend-item">
                    <div class="legend-color" style="background: #b91c1c;"></div>
                    <span class="legend-label">Prerequisite</span>
                </div>
                <div class="legend-item">
                    <div class="legend-color" style="background: #7c2d12;"></div>
                    <span class="legend-label">Sequential</span>
                </div>
                <div class="legend-item">
                    <div class="legend-color" style="background: #ca8a04;"></div>
                    <span class="legend-label">Conditional</span>
                </div>
                <div class="legend-item">
                    <div class="legend-color" style="background: #059669;"></div>
                    <span class="legend-label">Complementary</span>
                </div>
                <div class="legend-item">
                    <div class="legend-color" style="background: #5b21b6;"></div>
                    <span class="legend-label">Contradictory</span>
                </div>
                <div class="legend-item">
                    <div class="legend-color" style="background: #be185d;"></div>
                    <span class="legend-label">Override</span>
                </div>
                <div class="legend-item">
                    <div class="legend-color" style="background: #0e7490;"></div>
                    <span class="legend-label">Validation</span>
                </div>
            </div>
            
            <div class="legend" style="margin-top: 20px;">
                <div style="font-weight: 600; width: 100%; margin-bottom: 10px;">Rule Type Colors ({len(rule_type_colors) - 1} Categories):</div>
                {rule_type_legend_html}
            </div>
        </div>
        
        <div class="entity-definitions-container">
            <h2 class="section-title">� Entities & Relationships ({entity_count} connected to rules)</h2>
            <p style="color: #64748b; margin-bottom: 15px;">Each entity is semantically connected to the business rules that govern it. Diamond nodes in the graph above show these connections.</p>
            <div class="entity-cards">
                {entity_cards_html_str}
            </div>
        </div>

        <div class="entity-definitions-container">
            <h2 class="section-title">�📚 Rule Type Categories</h2>
            <div class="entity-cards">
                {rule_type_cards_html_str}
            </div>
        </div>
        
        <div class="table-container">
            <h2 class="section-title">📋 Business Rules Details</h2>
            
            <div class="controls">
                <input type="text" id="searchBox" class="search-box" placeholder="🔍 Search rules by ID, name, description...">
                <button class="filter-btn active" data-filter="all" data-filter-type="rule">All Rules</button>
                {filter_buttons_html}
                <button class="filter-btn" data-filter="mandatory" data-filter-type="rule">Mandatory Only</button>
                <button class="filter-btn" data-filter="low_confidence" data-filter-type="rule">⚠️ Low Confidence</button>
            </div>
            
            <table id="rulesTable">
                <thead>
                    <tr>
                        <th>Rule ID</th>
                        <th>Rule Name</th>
                        <th>Type</th>
                        <th>Description</th>
                        <th>Confidence</th>
                        <th>Mandatory</th>
                        <th>Risk</th>
                        <th>Jurisdiction</th>
                        <th>Scope</th>
                        <th>Dependencies</th>
                        <th>Dependency Evidence</th>
                        <th>Reference</th>
                        <th>Enforcement</th>
                        <th>Audit</th>
                    </tr>
                </thead>
                <tbody id="rulesBody">
                </tbody>
            </table>
            <div id="noResults" class="no-results" style="display: none;">
                No rules match your search criteria
            </div>
        </div>
    </div>
    
    <!-- Detail Modal -->
    <div id="ruleModal" class="modal-overlay" onclick="if(event.target===this)closeModal()">
        <div class="modal">
            <div class="modal-header">
                <h2 id="modalTitle"></h2>
                <button class="modal-close" onclick="closeModal()">&times;</button>
            </div>
            <div class="modal-body" id="modalBody"></div>
        </div>
    </div>
    
    <script>
        // Data
        const rulesData = {json.dumps(rules, indent=2)};
        
        const nodesData = {json.dumps(nodes, indent=2)};
        
        const edgesData = {json.dumps(edges, indent=2)};
        
        // Wait for DOM and vis.js to be ready
        document.addEventListener('DOMContentLoaded', function() {{
            try {{
                console.log('Starting visualization initialization...');
                console.log('Rules data:', rulesData.length);
                console.log('Nodes data:', nodesData.length);
                console.log('Edges data:', edgesData.length);
                
                // Initialize network graph
                const container = document.getElementById('network');
                if (!container) {{
                    throw new Error('Network container not found!');
                }}
                console.log('Container found:', container);
                
                if (typeof vis === 'undefined') {{
                    throw new Error('vis.js library not loaded!');
                }}
                console.log('vis.js loaded:', typeof vis);
                
                console.log('Creating DataSets...');
                const data = {{
                    nodes: new vis.DataSet(nodesData),
                    edges: new vis.DataSet(edgesData)
                }};
                console.log('DataSets created successfully');
                
                const options = {{
                    nodes: {{
                        font: {{
                            size: 14,
                            color: '#1e293b'
                        }},
                        borderWidth: 2,
                        borderWidthSelected: 4,
                        shadow: {{
                            enabled: true,
                            color: 'rgba(0,0,0,0.2)',
                            size: 10,
                            x: 2,
                            y: 2
                        }}
                    }},
                    edges: {{
                        width: 2,
                        arrows: {{
                            to: {{
                                enabled: true,
                                scaleFactor: 0.8
                            }}
                        }},
                        smooth: {{
                            enabled: true,
                            type: 'curvedCW',
                            roundness: 0.2
                        }},
                        shadow: {{
                            enabled: true,
                            color: 'rgba(0,0,0,0.1)',
                            size: 5,
                            x: 1,
                            y: 1
                        }}
                    }},
                    physics: {{
                        enabled: true,
                        stabilization: {{
                            enabled: true,
                            iterations: 300,
                            updateInterval: 25
                        }},
                        barnesHut: {{
                            gravitationalConstant: -4000,
                            centralGravity: 0.5,
                            springLength: 200,
                            springConstant: 0.02,
                            damping: 0.5,
                            avoidOverlap: 0.2
                        }},
                        maxVelocity: 50,
                        minVelocity: 0.75,
                        solver: 'barnesHut'
                    }},
                    interaction: {{
                        hover: true,
                        tooltipDelay: 100,
                        navigationButtons: true,
                        keyboard: true,
                        zoomView: true,
                        dragView: true
                    }},
                    layout: {{
                        improvedLayout: true,
                        hierarchical: false
                    }}
                }};
                
                console.log('Creating network with options...');
                const network = new vis.Network(container, data, options);
                console.log('Network created successfully!');
                
                // Add click event for nodes
                network.on("click", function(params) {{
                    if (params.nodes.length > 0) {{
                        const nodeId = params.nodes[0];
                        // Look up the node to get _rule_index
                        const nodeData = data.nodes.get(nodeId);
                        if (nodeData && typeof nodeData._rule_index === 'number') {{
                            showRuleDetail(rulesData[nodeData._rule_index]);
                        }} else {{
                            // Might be a category node — filter by that type instead
                            const rule = rulesData.find(r => r.rule_id === nodeId || r._unique_id === nodeId);
                            if (rule) {{
                                showRuleDetail(rule);
                            }} else if (nodeId.startsWith('entity_')) {{
                                // Entity node clicked — filter table to rules for this entity
                                const entityName = nodeId.replace('entity_', '');
                                const searchBox = document.getElementById('searchBox');
                                searchBox.value = entityName;
                                document.querySelectorAll('.filter-btn[data-filter-type="rule"]').forEach(b => {{
                                    b.classList.remove('active');
                                }});
                                document.querySelector('.filter-btn[data-filter="all"]').classList.add('active');
                                currentRuleFilter = 'all';
                                filterRules();
                                document.getElementById('rulesTable').scrollIntoView({{ behavior: 'smooth' }});
                            }} else if (nodeId.startsWith('type_')) {{
                                const ruleType = nodeId.replace('type_', '');
                                const searchBox = document.getElementById('searchBox');
                                searchBox.value = '';
                                // Click the matching filter button
                                document.querySelectorAll('.filter-btn[data-filter-type="rule"]').forEach(b => {{
                                    b.classList.remove('active');
                                    if (b.dataset.filter === ruleType || (ruleType && b.dataset.filter === ruleType)) b.classList.add('active');
                                }});
                                currentRuleFilter = ruleType;
                                filterRules();
                                document.getElementById('rulesTable').scrollIntoView({{ behavior: 'smooth' }});
                            }}
                        }}
                    }}
                }});
                
                // ── Modal helpers ──
                function closeModal() {{
                    document.getElementById('ruleModal').classList.remove('active');
                }}
                // Make closeModal globally accessible
                window.closeModal = closeModal;
                
                // Escape key closes modal
                document.addEventListener('keydown', function(e) {{
                    if (e.key === 'Escape') closeModal();
                }});
                
                function highlightSourceText(text, startWord, endWord) {{
                    if (!text) return '<em style="color:#94a3b8;">No source text available</em>';
                    if (typeof startWord !== 'number' || typeof endWord !== 'number') return escHtml(text);
                    const words = text.split(/(\s+)/);
                    let wordIdx = 0;
                    let result = '';
                    let inHighlight = false;
                    for (let i = 0; i < words.length; i++) {{
                        // Whitespace tokens are not counted as words
                        if (/^\s+$/.test(words[i])) {{
                            result += words[i];
                            continue;
                        }}
                        if (wordIdx === startWord && !inHighlight) {{
                            result += '<mark>';
                            inHighlight = true;
                        }}
                        result += escHtml(words[i]);
                        if (wordIdx === endWord && inHighlight) {{
                            result += '</mark>';
                            inHighlight = false;
                        }}
                        wordIdx++;
                    }}
                    if (inHighlight) result += '</mark>';
                    return result;
                }}
                
                function escHtml(s) {{
                    if (!s) return '';
                    return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
                }}
                
                function confidenceColor(v) {{
                    if (v >= 85) return '#10b981';
                    if (v >= 70) return '#f59e0b';
                    return '#ef4444';
                }}
                
                function renderConfidenceBreakdown(bd) {{
                    if (!bd || typeof bd !== 'object') return '<span style="color:#94a3b8;">N/A</span>';
                    const labels = {{
                        extraction_clarity: 'Extraction Clarity',
                        numeric_precision: 'Numeric Precision',
                        context_completeness: 'Context Completeness',
                        source_authority: 'Source Authority',
                        logical_consistency: 'Logical Consistency'
                    }};
                    return Object.entries(bd).map(([k, v]) => {{
                        const label = labels[k] || k;
                        const pct = Math.min(100, Math.max(0, v));
                        return `<div class="confidence-bar">
                            <span class="confidence-bar-label">${{label}}</span>
                            <div class="confidence-bar-track"><div class="confidence-bar-fill" style="width:${{pct}}%;background:${{confidenceColor(pct)}}"></div></div>
                            <span class="confidence-bar-value">${{pct}}</span>
                        </div>`;
                    }}).join('');
                }}
                
                function renderList(arr) {{
                    if (!arr || !arr.length) return '<span style="color:#94a3b8;">None</span>';
                    return '<div class="modal-tags">' + arr.map(v => `<span class="modal-tag">${{escHtml(String(v))}}</span>`).join('') + '</div>';
                }}
                
                function renderExamples(arr) {{
                    if (!arr || !arr.length) return '<span style="color:#94a3b8;">None</span>';
                    return '<ol style="margin:0;padding-left:18px;">' + arr.map(e => `<li style="margin:3px 0;font-size:0.9em;color:#334155;">${{escHtml(e)}}</li>`).join('') + '</ol>';
                }}
                
                function showRuleDetail(rule) {{
                    if (!rule) return;
                    const m = document.getElementById('ruleModal');
                    document.getElementById('modalTitle').innerHTML =
                        `<span style="color:#667eea;font-family:monospace;">${{escHtml(rule.rule_id)}}</span> &mdash; ${{escHtml(rule.rule_name || 'Untitled')}}`;
                    
                    const ref = rule.source_reference || {{}};
                    const isRefObj = ref && typeof ref === 'object' && !Array.isArray(ref);
                    const chunkPath = isRefObj ? (ref.chunk_path || 'N/A') : (Array.isArray(ref) ? ref.map(r => typeof r === 'object' ? r.chunk_path : r).join('; ') : String(ref || 'N/A'));
                    const sectionId = isRefObj ? (ref.section_id || 'N/A') : 'N/A';
                    const sourceText = isRefObj ? (ref.source_text || ref.source_text_approximate || '') : '';
                    const wordStart = isRefObj ? ref.start_word_position : undefined;
                    const wordEnd = isRefObj ? ref.end_word_position : undefined;
                    const matchScore = isRefObj && typeof ref.text_match_score === 'number' ? ref.text_match_score.toFixed(3) : 'N/A';
                    
                    const scope = rule.applicability_scope || {{}};
                    const entityDef = rule.entity_definition || {{}};
                    const relDef = rule.relationship_definition || {{}};
                    
                    let depHtml = '<span style="color:#94a3b8;">None</span>';
                    const deps = rule.dependencies || [];
                    if (deps.length) {{
                        depHtml = deps.map(d => `<div class="dep-evidence" style="margin-bottom:8px;">
                            <strong style="color:#1e40af;">→ ${{escHtml(d.depends_on_rule)}}</strong>
                            <span class="modal-tag" style="margin-left:6px;">${{escHtml(d.dependency_type)}}</span>
                            ${{d.strength ? `<span class="modal-tag">strength: ${{d.strength}}/5</span>` : ''}}
                            <div style="margin-top:4px;font-size:0.88em;color:#334155;">${{escHtml(d.rationale || '')}}</div>
                            ${{d.impact_if_fails ? `<div style="margin-top:2px;font-size:0.85em;color:#b91c1c;"><strong>Impact:</strong> ${{escHtml(d.impact_if_fails)}}</div>` : ''}}
                        </div>`).join('');
                    }}
                    
                    let depRulesHtml = '<span style="color:#94a3b8;">None</span>';
                    const depRules = rule.dependent_rules || [];
                    if (depRules.length) {{
                        depRulesHtml = depRules.map(d => `<div class="dep-evidence" style="margin-bottom:8px;">
                            <strong style="color:#059669;">← ${{escHtml(d.rule_id || d.dependent_rule || '')}}</strong>
                            <span class="modal-tag">${{escHtml(d.dependency_type || '')}}</span>
                            ${{d.rationale ? `<div style="margin-top:4px;font-size:0.88em;color:#334155;">${{escHtml(d.rationale)}}</div>` : ''}}
                        </div>`).join('');
                    }}
                    
                    let dedupHtml = '';
                    if (rule.deduplication_info) {{
                        const di = rule.deduplication_info;
                        dedupHtml = `<div class="modal-section">
                            <div class="modal-section-title">Deduplication Info</div>
                            <div class="modal-field"><span class="modal-field-label">Action</span><div class="modal-field-value">${{escHtml(di.action || '')}}</div></div>
                            ${{di.merged_from ? `<div class="modal-field"><span class="modal-field-label">Merged From</span><div class="modal-field-value">${{renderList(di.merged_from)}}</div></div>` : ''}}
                            ${{di.rationale ? `<div class="modal-field"><span class="modal-field-label">Rationale</span><div class="modal-field-value">${{escHtml(di.rationale)}}</div></div>` : ''}}
                        </div>`;
                    }}
                    
                    let reviewHtml = '';
                    if (rule.requires_review) {{
                        reviewHtml = `<div style="background:#fef3c7;border:1px solid #f59e0b;border-radius:8px;padding:10px 14px;margin-bottom:16px;">
                            <strong style="color:#92400e;">⚠️ Requires Review</strong>
                            ${{rule.review_reason ? `<div style="margin-top:4px;font-size:0.9em;color:#92400e;">${{escHtml(rule.review_reason)}}</div>` : ''}}
                        </div>`;
                    }}
                    
                    const html = `
                        ${{reviewHtml}}
                        <div class="modal-section">
                            <div class="modal-section-title">Core Details</div>
                            <div class="modal-grid">
                                <div class="modal-field"><span class="modal-field-label">Rule Type</span><div class="modal-field-value"><span class="badge badge-${{rule.rule_type || 'unknown'}}">${{(rule.rule_type || 'unknown').toUpperCase()}}</span></div></div>
                                <div class="modal-field"><span class="modal-field-label">Mandatory</span><div class="modal-field-value"><span class="badge ${{rule.mandatory ? 'badge-mandatory' : 'badge-optional'}}">${{rule.mandatory ? 'Yes' : 'No'}}</span></div></div>
                                <div class="modal-field"><span class="modal-field-label">Risk Level</span><div class="modal-field-value">${{escHtml((rule.risk_level || 'N/A').toUpperCase())}}</div></div>
                                <div class="modal-field"><span class="modal-field-label">Jurisdiction</span><div class="modal-field-value">${{escHtml(rule.jurisdiction || 'N/A')}}</div></div>
                                <div class="modal-field"><span class="modal-field-label">Entity</span><div class="modal-field-value">${{escHtml(rule.entity_or_relationship || 'N/A')}} <small>(${{escHtml(rule.entity_type || '')}})</small></div></div>
                                <div class="modal-field"><span class="modal-field-label">Enforcement</span><div class="modal-field-value">${{escHtml(rule.enforcement_action || 'N/A')}}</div></div>
                                <div class="modal-field"><span class="modal-field-label">Audit Frequency</span><div class="modal-field-value">${{escHtml(rule.audit_frequency || 'N/A')}}</div></div>
                                <div class="modal-field"><span class="modal-field-label">Effective Date</span><div class="modal-field-value">${{escHtml(rule.effective_date || 'N/A')}}</div></div>
                                <div class="modal-field"><span class="modal-field-label">Expiration Date</span><div class="modal-field-value">${{escHtml(rule.expiration_date || 'N/A')}}</div></div>
                                <div class="modal-field"><span class="modal-field-label">Superseded By</span><div class="modal-field-value">${{escHtml(rule.superseded_by || 'N/A')}}</div></div>
                            </div>
                        </div>
                        
                        <div class="modal-section">
                            <div class="modal-section-title">Description &amp; Logic</div>
                            <div class="modal-field"><span class="modal-field-label">Description</span><div class="modal-field-value">${{escHtml(rule.description || 'N/A')}}</div></div>
                            <div class="modal-field" style="margin-top:8px;"><span class="modal-field-label">Conditions</span><div class="modal-field-value">${{escHtml(rule.conditions || 'N/A')}}</div></div>
                            <div class="modal-field" style="margin-top:8px;"><span class="modal-field-label">Consequences</span><div class="modal-field-value">${{escHtml(rule.consequences || 'N/A')}}</div></div>
                            <div class="modal-field" style="margin-top:8px;"><span class="modal-field-label">Exceptions</span><div class="modal-field-value">${{escHtml(rule.exceptions || 'N/A')}}</div></div>
                        </div>
                        
                        <div class="modal-section">
                            <div class="modal-section-title">Examples</div>
                            ${{renderExamples(rule.examples)}}
                        </div>
                        
                        <div class="modal-section">
                            <div class="modal-section-title">Source Reference (Document Chunk)</div>
                            <div class="modal-grid">
                                <div class="modal-field"><span class="modal-field-label">Chunk Path</span><div class="modal-field-value mono">${{escHtml(chunkPath)}}</div></div>
                                <div class="modal-field"><span class="modal-field-label">Section</span><div class="modal-field-value">${{escHtml(sectionId)}}</div></div>
                                <div class="modal-field"><span class="modal-field-label">Word Range</span><div class="modal-field-value">${{typeof wordStart === 'number' ? wordStart + ' – ' + wordEnd : 'N/A'}}</div></div>
                                <div class="modal-field"><span class="modal-field-label">Text Match Score</span><div class="modal-field-value">${{matchScore}}</div></div>
                                <div class="modal-field"><span class="modal-field-label">Verified</span><div class="modal-field-value">${{rule.reference_verified === true ? '✅ Yes' : (rule.reference_verified === false ? '❌ No' : 'N/A')}}</div></div>
                                <div class="modal-field"><span class="modal-field-label">Verification Note</span><div class="modal-field-value">${{escHtml(rule.reference_verification_note || 'N/A')}}</div></div>
                            </div>
                            <div style="margin-top:12px;">
                                <span class="modal-field-label">Source Text <small>(highlighted region = words ${{typeof wordStart === 'number' ? wordStart : '?'}}–${{typeof wordEnd === 'number' ? wordEnd : '?'}})</small></span>
                                <div class="source-text-block">${{highlightSourceText(sourceText, wordStart, wordEnd)}}</div>
                            </div>
                        </div>
                        
                        <div class="modal-section">
                            <div class="modal-section-title">Confidence</div>
                            <div class="modal-grid">
                                <div class="modal-field"><span class="modal-field-label">Overall Score</span><div class="modal-field-value"><span class="badge ${{(rule.confidence_score||0) >= 85 ? 'confidence-high' : (rule.confidence_score||0) >= 70 ? 'confidence-medium' : 'confidence-low'}}">${{rule.confidence_score ? rule.confidence_score.toFixed(0) + '/100' : 'N/A'}}</span></div></div>
                            </div>
                            <div style="margin-top:8px;">
                                <span class="modal-field-label">Breakdown</span>
                                ${{renderConfidenceBreakdown(rule.confidence_breakdown)}}
                            </div>
                            ${{rule.extraction_notes ? `<div class="modal-field" style="margin-top:8px;"><span class="modal-field-label">Extraction Notes</span><div class="modal-field-value">${{escHtml(rule.extraction_notes)}}</div></div>` : ''}}
                        </div>
                        
                        <div class="modal-section">
                            <div class="modal-section-title">Applicability Scope</div>
                            <div class="modal-grid">
                                <div class="modal-field"><span class="modal-field-label">Loan Types</span><div class="modal-field-value">${{renderList(scope.loan_types)}}</div></div>
                                <div class="modal-field"><span class="modal-field-label">Occupancy Types</span><div class="modal-field-value">${{renderList(scope.occupancy_types)}}</div></div>
                                <div class="modal-field"><span class="modal-field-label">Transaction Types</span><div class="modal-field-value">${{renderList(scope.transaction_types)}}</div></div>
                                <div class="modal-field"><span class="modal-field-label">Data Points Required</span><div class="modal-field-value">${{renderList(rule.data_points_required)}}</div></div>
                            </div>
                        </div>
                        
                        <div class="modal-section">
                            <div class="modal-section-title">Entity / Relationship Definition</div>
                            <div class="modal-field"><span class="modal-field-label">Description</span><div class="modal-field-value">${{escHtml(entityDef.description || relDef.description || 'N/A')}}</div></div>
                            ${{(entityDef.key_attributes || relDef.key_attributes || []).length ? `<div class="modal-field" style="margin-top:6px;"><span class="modal-field-label">Key Attributes</span><div class="modal-field-value">${{renderList(entityDef.key_attributes || relDef.key_attributes)}}</div></div>` : ''}}
                            ${{(entityDef.examples || relDef.examples || []).length ? `<div class="modal-field" style="margin-top:6px;"><span class="modal-field-label">Examples</span><div class="modal-field-value">${{renderList(entityDef.examples || relDef.examples)}}</div></div>` : ''}}
                        </div>
                        
                        <div class="modal-section">
                            <div class="modal-section-title">Dependencies (rules this depends on)</div>
                            ${{depHtml}}
                        </div>
                        
                        <div class="modal-section">
                            <div class="modal-section-title">Dependent Rules (rules that depend on this)</div>
                            ${{depRulesHtml}}
                        </div>
                        
                        <div class="modal-section">
                            <div class="modal-section-title">Related Rules</div>
                            ${{renderList(rule.related_rules)}}
                        </div>
                        
                        ${{dedupHtml}}
                    `;
                    
                    document.getElementById('modalBody').innerHTML = html;
                    m.classList.add('active');
                }}
                // Make showRuleDetail globally accessible
                window.showRuleDetail = showRuleDetail;
                
                // Populate table
                function populateTable(rules) {{
                    const tbody = document.getElementById('rulesBody');
                    const noResults = document.getElementById('noResults');
                    
                    if (rules.length === 0) {{
                        tbody.innerHTML = '';
                        noResults.style.display = 'block';
                        return;
                    }}
                    
                    noResults.style.display = 'none';
                    
                    tbody.innerHTML = rules.map(rule => {{
                const ruleTypeBadge = `badge badge-${{rule.rule_type || 'unknown'}}`;
                const mandatoryBadge = rule.mandatory ? 'badge badge-mandatory' : 'badge badge-optional';
                const mandatoryText = rule.mandatory ? 'Mandatory' : 'Optional';
                
                const deps = rule.dependencies || [];
                const depsHTML = deps.length > 0 
                    ? deps.map(dep => 
                        `<span class="dependency-badge dep-${{dep.dependency_type}}">
                            ${{dep.depends_on_rule}} (${{dep.dependency_type}})
                        </span>`
                    ).join('')
                    : '<span style="color: #94a3b8;">None</span>';
                
                // Dependency evidence (rationale)
                const depsEvidenceHTML = deps.length > 0
                    ? deps.map(dep => {{
                        const rationale = dep.rationale || 'No rationale provided';
                        const strength = dep.strength || 'N/A';
                        const impact = dep.impact_if_fails || '';
                        return `<div class="dep-evidence">
                            <strong>→ ${{dep.depends_on_rule}}:</strong><br/>
                            <em>Type:</em> ${{dep.dependency_type}} (Strength: ${{strength}}/5)<br/>
                            <em>Rationale:</em> ${{rationale}}
                            ${{impact ? `<br/><em>Impact:</em> ${{impact}}` : ''}}
                        </div>`;
                    }}).join('<hr style="margin: 8px 0; border: none; border-top: 1px solid #e2e8f0;">')
                    : '<span style="color: #94a3b8;">No dependencies</span>';
                
                // Confidence score badge
                const confidence = rule.confidence_score || 0;
                let confidenceClass = 'confidence-unknown';
                let confidenceText = 'N/A';
                
                if (confidence > 0) {{
                    confidenceText = `${{confidence.toFixed(0)}}/100`;
                    if (confidence >= 85) {{
                        confidenceClass = 'confidence-high';
                    }} else if (confidence >= 70) {{
                        confidenceClass = 'confidence-medium';
                    }} else {{
                        confidenceClass = 'confidence-low';
                    }}
                }}
                
                // Format source_reference for display
                let refDisplay = 'N/A';
                const srcRef = rule.source_reference || rule.fannie_mae_reference;
                if (srcRef && typeof srcRef === 'object' && !Array.isArray(srcRef)) {{
                    const cp = srcRef.chunk_path || '';
                    const sec = srcRef.section_id && srcRef.section_id !== 'N/A' ? ` | ${{srcRef.section_id}}` : '';
                    const wp = (typeof srcRef.start_word_position === 'number' && typeof srcRef.end_word_position === 'number')
                        ? ` <span class="badge" style="font-size:0.65em;background:#e2e8f0;color:#475569;">words ${{srcRef.start_word_position}}-${{srcRef.end_word_position}}</span>` : '';
                    const verified = rule.reference_verified === true ? ' ✅' : (rule.reference_verified === false ? ' ❌' : '');
                    refDisplay = `${{cp}}${{sec}}${{wp}}${{verified}}`;
                    if (srcRef.source_text) {{
                        refDisplay += `<br/><small style="color:#64748b;" title="${{srcRef.source_text}}">"${{srcRef.source_text.substring(0, 80)}}${{srcRef.source_text.length > 80 ? '…' : ''}}"</small>`;
                    }}
                }} else if (Array.isArray(srcRef)) {{
                    refDisplay = srcRef.map(r => typeof r === 'object' ? (r.chunk_path || '') : String(r)).join('<br/>');
                }} else if (typeof srcRef === 'string' && srcRef) {{
                    refDisplay = srcRef;
                }}

                        return `
                            <tr data-rule-id="${{rule.rule_id}}" data-rule-type="${{rule.rule_type}}" data-mandatory="${{rule.mandatory}}">
                                <td><span class="rule-id clickable-rule-id" onclick="showRuleDetail(rulesData[${{rule._rule_index}}])">${{rule.rule_id}}</span></td>
                                <td><strong>${{rule.rule_name || 'N/A'}}</strong></td>
                                <td><span class="${{ruleTypeBadge}}">${{(rule.rule_type || 'unknown').toUpperCase()}}</span></td>
                                <td class="detail-cell">
                                    ${{rule.description || 'N/A'}}
                                </td>
                                <td><span class="badge ${{confidenceClass}}">${{confidenceText}}</span></td>
                                <td><span class="${{mandatoryBadge}}">${{mandatoryText}}</span></td>
                                <td><span class="badge badge-${{(rule.risk_level || 'unknown').toLowerCase()}}">${{(rule.risk_level || 'N/A').toUpperCase()}}</span></td>
                                <td><small>${{rule.jurisdiction || 'N/A'}}</small></td>
                                <td class="detail-cell"><small>${{rule.applicability_scope ? (rule.applicability_scope.loan_types || []).join(', ') : 'N/A'}}</small></td>
                                <td class="detail-cell">${{depsHTML}}</td>
                                <td class="detail-cell dependency-evidence-cell">${{depsEvidenceHTML}}</td>
                                <td class="detail-cell">${{refDisplay}}</td>
                                <td><small>${{rule.enforcement_action || 'N/A'}}</small></td>
                                <td><small>${{rule.audit_frequency || 'N/A'}}</small></td>
                            </tr>
                        `;
                    }}).join('');
                }}
                
                // Filter functionality
                let currentRuleFilter = 'all';
                let searchTerm = '';
                
                function filterRules() {{
                    searchTerm = document.getElementById('searchBox').value.toLowerCase();
                    
                    const filtered = rulesData.filter(rule => {{
                        // Apply rule type filter
                        let ruleTypeMatch = true;
                        if (currentRuleFilter === 'mandatory') {{
                            ruleTypeMatch = rule.mandatory === true;
                        }} else if (currentRuleFilter === 'low_confidence') {{
                            ruleTypeMatch = (rule.confidence_score || 0) < 70 && (rule.confidence_score || 0) > 0;
                        }} else if (currentRuleFilter !== 'all') {{
                            ruleTypeMatch = rule.rule_type === currentRuleFilter;
                        }}
                        
                        // Apply search filter
                        let searchMatch = true;
                        if (searchTerm) {{
                            searchMatch = 
                                (rule.rule_id || '').toLowerCase().includes(searchTerm) ||
                                (rule.rule_name || '').toLowerCase().includes(searchTerm) ||
                                (rule.description || '').toLowerCase().includes(searchTerm) ||
                                (rule.entity_or_relationship || '').toLowerCase().includes(searchTerm);
                        }}
                    
                    return ruleTypeMatch && searchMatch;
                }});
                
                populateTable(filtered);
                }}                // Search box event
                document.getElementById('searchBox').addEventListener('input', filterRules);
                
                // Filter buttons
                document.querySelectorAll('.filter-btn').forEach(btn => {{
                    btn.addEventListener('click', function() {{
                        const filterType = this.dataset.filterType;
                        
                        // Remove active from buttons of the same type
                        document.querySelectorAll(`.filter-btn[data-filter-type="${{filterType}}"]`).forEach(b => b.classList.remove('active'));
                        this.classList.add('active');
                        
                        // Update rule filter
                        if (filterType === 'rule') {{
                            currentRuleFilter = this.dataset.filter;
                        }}
                        
                        filterRules();
                    }});
                }});
                
                // Initial population
                populateTable(rulesData);
                
                console.log('✅ Knowledge Graph Visualization loaded successfully');
                console.log(`📊 Total rules: ${{rulesData.length}}`);
                console.log(`🔗 Total nodes: ${{nodesData.length}}`);
                console.log(`➡️  Total edges: ${{edgesData.length}}`);
            }} catch (error) {{
                console.error('❌ Error initializing visualization:', error);
                console.error('Error name:', error.name);
                console.error('Error message:', error.message);
                console.error('Error stack:', error.stack);
                const container = document.getElementById('network');
                if (container) {{
                    container.innerHTML = '<div style="padding: 20px; color: red; background: #fee; border: 2px solid red; border-radius: 8px; margin: 20px;"><h3>Error loading visualization</h3><p>' + error.message + '</p><p style="font-size: 12px;">Check browser console (F12) for detailed error information.</p></div>';
                }}
            }}
        }});
    </script>
</body>
</html>
"""
    
    return html_content


def main():
    """Main entry point."""
    from utils.config import get_config
    
    config = get_config()
    
    # Try to use optimized version first, fall back to non-optimized
    optimized_file = config.get_optimized_dir() / "optimized_compliance_knowledge_graph.json"
    rules_with_entities_file = config.get_rules_with_entities_dir() / "compliance_knowledge_graph.json"
    
    if optimized_file.exists():
        json_file = optimized_file
        print("📊 Using optimized business rules")
    elif rules_with_entities_file.exists():
        json_file = rules_with_entities_file
        print("📊 Using non-optimized business rules (Agent 4 output)")
    else:
        print(f"❌ Error: No input file found.")
        print(f"   Looked for:")
        print(f"     - {optimized_file}")
        print(f"     - {rules_with_entities_file}")
        print("   Please run the pipeline up to step 4 or 5 first.")
        sys.exit(1)
    
    # Name the HTML file after the source file or batch for clarity
    source_name = config.get_batch_name() or config.get_source_file_name()
    if source_name:
        html_filename = f"{source_name}_knowledge_graph.html"
    else:
        html_filename = "knowledge_graph_visualization.html"
    html_file = config.get_visualization_dir() / html_filename
    
    if not json_file.exists():
        print(f"❌ Error: Input file not found: {json_file}")
        print("   Please run the pipeline up to step 5 (optimization) first.")
        sys.exit(1)
    
    print("=" * 80)
    print("KNOWLEDGE GRAPH VISUALIZATION GENERATOR")
    print("=" * 80)
    print()
    
    # Generate visualization using the class
    visualizer = KnowledgeGraphVisualizer(json_file, html_file)
    visualizer.generate()
    
    print()
    print("=" * 80)
    print("✅ VISUALIZATION COMPLETE")
    print("=" * 80)


if __name__ == "__main__":
    main()
