#!/usr/bin/env python3
"""
Set Operations Visualization Generator (Agent 10)

Creates separate HTML visualizations for each set operation:
- index.html: Summary dashboard with Venn diagram
- intersection.html: G1 ∩ G2 (rules in both graphs)
- g1_minus_g2.html: G1 - G2 (rules exclusive to G1)
- g2_minus_g1.html: G2 - G1 (rules exclusive to G2)
- union.html: G1 ∪ G2 (all unique rules)
- contradictions.html: Conflicting rule pairs

Visual encoding:
- ELLIPSE: Matched rules (from both graphs) - shows both rule IDs
- RECTANGLE: G1-only rules
- CIRCLE: G2-only rules

Author: Reza Rahimi
Date: December 20, 2025
"""

import json
import sys
import os
import base64
from pathlib import Path
from datetime import datetime
from collections import defaultdict
from typing import Dict, List

# Add project root to Python path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.config import get_config


# Rule type colours — combined across all supported domains.
# At runtime each method calls get_config().get_rule_type_colors() for the
# active-domain palette; this constant serves as a reference / fallback.
RULE_TYPE_COLORS = {
    # --- shared by all domains ---
    'eligibility':   '#3b82f6',  # Blue
    'constraint':    '#ef4444',  # Red
    'calculation':   '#06b6d4',  # Cyan
    'validation':    '#f59e0b',  # Amber
    'process':       '#ec4899',  # Pink
    'compliance':    '#10b981',  # Green
    'documentation': '#8b5cf6',  # Purple
    # --- mortgage-specific ---
    'prohibition':   '#dc2626',  # Dark Red
    'definition':    '#6366f1',  # Indigo
    'exception':     '#f97316',  # Orange
    # --- AML-specific ---
    'reporting':     '#e11d48',  # Rose
    'monitoring':    '#0284c7',  # Sky Blue
    'screening':     '#7c3aed',  # Violet
}

# Source colors
SOURCE_COLORS = {
    'g1': '#3b82f6',  # Blue for G1
    'g2': '#10b981'   # Green for G2
}


class SetOperationsVisualizer:
    """
    Generates HTML visualizations for set operations results.
    """

    _logo_cache = None  # Class-level cache for the base64 logo

    @classmethod
    def _get_logo_base64(cls) -> str:
        """Load logo.svg as a base64-encoded data URI (cached)."""
        if cls._logo_cache is None:
            logo_path = Path(__file__).parent.parent / 'logo.svg'
            if logo_path.exists():
                with open(logo_path, 'rb') as f:
                    encoded = base64.b64encode(f.read()).decode('utf-8')
                cls._logo_cache = f'data:image/png;base64,{encoded}'
            else:
                cls._logo_cache = ''
        return cls._logo_cache
    
    def __init__(self, provider: str = "openai", merge_subfolder: str = None):
        """
        Initialize the visualizer.
        
        Args:
            provider: The provider folder (openai)
            merge_subfolder: Subfolder name for merged outputs (e.g., 'graphA_graphB')
        """
        self.provider = provider
        self.merge_subfolder = merge_subfolder
        self.base_path = Path(__file__).parent.parent / "pipeline-output"
        self._setup_paths()
        self._original_rules_cache = {}  # Cache for original graph rules
    
    def _setup_paths(self):
        """Set up input/output paths based on merge_subfolder."""
        if self.merge_subfolder:
            self.input_dir = self.base_path / "_merged" / self.merge_subfolder / "agent-9-set-operations"
            self.output_dir = self.base_path / "_merged" / self.merge_subfolder / "agent-10-visualizations"
        else:
            self.input_dir = self.base_path / "_merged" / "agent-9-set-operations"
            self.output_dir = self.base_path / "_merged" / "agent-10-visualizations"
    
    def _detect_subfolder(self):
        """Detect subfolder from existing agent-9 output if not set."""
        if self.merge_subfolder:
            return
        
        # Check for subfolders in _merged that contain agent-9-set-operations
        merged_dir = self.base_path / "_merged"
        if merged_dir.exists():
            for item in merged_dir.iterdir():
                if item.is_dir() and not item.name.startswith('agent-'):
                    potential_input = item / "agent-9-set-operations"
                    if potential_input.exists() and potential_input.is_dir():
                        self.merge_subfolder = item.name
                        self._setup_paths()
                        print(f"   ℹ️  Detected merge subfolder: {self.merge_subfolder}")
                        return
        
    def _load_original_rules(self, graph_name: str) -> dict:
        """Load original rules from a source graph and return as {rule_id: rule} map."""
        if graph_name in self._original_rules_cache:
            return self._original_rules_cache[graph_name]
        
        # Try to load from agent-5-optimized
        graph_path = self.base_path / graph_name / "agent-5-optimized" / "optimized_compliance_knowledge_graph.json"
        if graph_path.exists():
            with open(graph_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                rules_map = {r.get('rule_id', ''): r for r in data.get('business_rules', [])}
                self._original_rules_cache[graph_name] = rules_map
                return rules_map
        
        return {}
        
    def load_operation_result(self, operation: str) -> dict:
        """Load a set operation result."""
        # Try to detect subfolder if not set
        self._detect_subfolder()
        
        file_path = self.input_dir / f"{operation}.json"
        if not file_path.exists():
            raise FileNotFoundError(f"Operation result not found: {file_path}")
        
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        # Update subfolder from metadata if available
        if not self.merge_subfolder and 'metadata' in data:
            g1_name = data['metadata'].get('g1_name')
            g2_name = data['metadata'].get('g2_name')
            if g1_name and g2_name:
                self.merge_subfolder = f"{g1_name}_{g2_name}"
                self._setup_paths()
        
        return data
    
    def _get_common_styles(self) -> str:
        """Return common CSS styles matching union.html purple gradient theme."""
        return '''
        * { margin: 0; padding: 0; box-sizing: border-box; }
        
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: #1e293b;
            line-height: 1.6;
            min-height: 100vh;
            padding: 20px;
        }
        
        .container { max-width: 1600px; margin: 0 auto; }
        
        .header {
            background: white;
            border-radius: 16px;
            padding: 30px;
            margin-bottom: 20px;
            box-shadow: 0 10px 30px rgba(0,0,0,0.1);
            text-align: center;
        }
        
        .header h1 {
            font-size: 2.5em;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            margin-bottom: 10px;
        }
        
        .header .subtitle {
            color: #64748b;
            font-size: 1.1em;
        }
        
        .logo-container {
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 1rem;
            margin-bottom: 1rem;
        }
        
        .logo-container img {
            height: 60px;
            width: auto;
        }
        
        .stats-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
            gap: 15px;
            margin-bottom: 20px;
        }
        
        .stat-card {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 20px;
            border-radius: 12px;
            text-align: center;
            box-shadow: 0 4px 15px rgba(0,0,0,0.1);
        }
        
        .stat-value {
            font-size: 2.5em;
            font-weight: 700;
        }
        
        .stat-label {
            font-size: 0.9em;
            opacity: 0.9;
            margin-top: 5px;
        }
        
        .graph-container {
            background: white;
            border-radius: 16px;
            padding: 20px;
            margin-bottom: 20px;
            box-shadow: 0 10px 30px rgba(0,0,0,0.1);
            height: 600px;
        }
        
        .legend {
            display: flex;
            flex-wrap: wrap;
            gap: 20px;
            margin-bottom: 20px;
            padding: 20px;
            background: white;
            border-radius: 12px;
            box-shadow: 0 4px 15px rgba(0,0,0,0.1);
            justify-content: center;
        }
        
        .legend-item {
            display: flex;
            align-items: center;
            gap: 8px;
            padding: 8px 16px;
            background: #f8fafc;
            border-radius: 8px;
        }
        
        .legend-shape {
            width: 24px;
            height: 16px;
        }
        
        .legend-ellipse {
            border-radius: 50%;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        }
        
        .legend-rect {
            background: #3b82f6;
            border-radius: 4px;
        }
        
        .legend-circle {
            width: 16px;
            height: 16px;
            border-radius: 50%;
            background: #10b981;
        }
        
        .rules-table {
            width: 100%;
            border-collapse: separate;
            border-spacing: 0;
            background: white;
            border-radius: 12px;
            overflow: hidden;
            box-shadow: 0 4px 15px rgba(0,0,0,0.1);
        }
        
        .rules-table th {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 15px 12px;
            text-align: left;
            font-weight: 600;
        }
        
        .rules-table td {
            padding: 12px;
            border-bottom: 1px solid #e2e8f0;
            vertical-align: top;
        }
        
        .rules-table tr:hover {
            background: #f8fafc;
        }
        
        .badge {
            display: inline-block;
            padding: 4px 10px;
            border-radius: 20px;
            font-size: 0.75em;
            font-weight: 600;
        }
        
        .badge-eligibility { background: #dbeafe; color: #1e40af; }
        .badge-constraint { background: #fee2e2; color: #991b1b; }
        .badge-calculation { background: #cffafe; color: #0e7490; }
        .badge-validation { background: #fef3c7; color: #92400e; }
        .badge-process { background: #fce7f3; color: #9d174d; }
        .badge-compliance { background: #d1fae5; color: #065f46; }
        .badge-documentation { background: #ede9fe; color: #5b21b6; }
        .badge-prohibition { background: #fee2e2; color: #991b1b; }
        .badge-definition { background: #e0e7ff; color: #3730a3; }
        .badge-exception { background: #ffedd5; color: #9a3412; }
        .badge-unknown { background: #f1f5f9; color: #475569; }
        
        .nav-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
            gap: 15px;
            margin-top: 20px;
        }
        
        .nav-card {
            background: white;
            border-radius: 12px;
            padding: 20px;
            text-decoration: none;
            color: #1e293b;
            border: 2px solid #e2e8f0;
            transition: all 0.3s;
            box-shadow: 0 4px 15px rgba(0,0,0,0.05);
        }
        
        .nav-card:hover {
            border-color: #667eea;
            transform: translateY(-3px);
            box-shadow: 0 10px 30px rgba(0,0,0,0.1);
        }
        
        .nav-card h3 {
            font-size: 1.25em;
            margin-bottom: 8px;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }
        
        .nav-card p {
            color: #64748b;
            font-size: 0.9em;
        }
        
        .venn-container {
            display: flex;
            justify-content: center;
            padding: 20px;
            background: white;
            border-radius: 16px;
            margin-bottom: 20px;
            box-shadow: 0 10px 30px rgba(0,0,0,0.1);
        }
        
        /* Section headings outside white containers */
        h2 {
            color: white;
            text-shadow: 0 2px 4px rgba(0,0,0,0.2);
        }
        
        /* Ensure legend text is readable */
        .legend-item span {
            color: #1e293b;
            font-weight: 500;
        }
        '''
    
    def _get_vis_network_script(self) -> str:
        """Return vis.js network configuration."""
        return '''
        <script src="https://unpkg.com/vis-network@9.1.2/standalone/umd/vis-network.min.js"></script>
        <link href="https://unpkg.com/vis-network@9.1.2/dist/dist/vis-network.min.css" rel="stylesheet">
        '''
    
    def _format_ref_for_tooltip(self, ref) -> str:
        """Format a source_reference (structured, list, or string) for plain text tooltip."""
        if isinstance(ref, dict):
            parts = [ref.get('chunk_path', '')]
            sec = ref.get('section_id', '')
            if sec and sec != 'N/A':
                parts[0] += f" | {sec}"
            wp_s = ref.get('start_word_position', '')
            wp_e = ref.get('end_word_position', '')
            if isinstance(wp_s, int) and isinstance(wp_e, int):
                parts[0] += f" [words {wp_s}-{wp_e}]"
            return parts[0]
        elif isinstance(ref, list):
            return '; '.join(self._format_ref_for_tooltip(r) for r in ref)
        elif isinstance(ref, str):
            return ref
        return 'N/A'

    def _build_tooltip(self, rule: dict, g1_name: str = "G1", g2_name: str = "G2") -> str:
        """Build a simple plain text tooltip for a rule node."""
        rule_name = rule.get('rule_name', 'N/A')
        reference = rule.get('source_reference', rule.get('legacy_source_reference', ''))
        
        provenance = rule.get('provenance', {})
        sources = provenance.get('sources', [])
        
        # For merged rules, show both G1 and G2 info
        if len(sources) == 2 and provenance.get('g1_rule') and provenance.get('g2_rule'):
            g1_info = provenance['g1_rule']
            g2_info = provenance['g2_rule']
            g1_ref = self._format_ref_for_tooltip(g1_info.get('source_reference', g1_info.get('legacy_source_reference', 'N/A')))
            g2_ref = self._format_ref_for_tooltip(g2_info.get('source_reference', g2_info.get('legacy_source_reference', 'N/A')))
            return (f"INTERSECTION ({g1_name} ∩ {g2_name})\n\n"
                    f"[G1] {g1_name}:\n"
                    f"  ID: {g1_info.get('rule_id', 'N/A')}\n"
                    f"  Name: {g1_info.get('rule_name', 'N/A')}\n"
                    f"  Ref: {g1_ref}\n\n"
                    f"[G2] {g2_name}:\n"
                    f"  ID: {g2_info.get('rule_id', 'N/A')}\n"
                    f"  Name: {g2_info.get('rule_name', 'N/A')}\n"
                    f"  Ref: {g2_ref}\n\n"
                    f"Confidence: {provenance.get('confidence', 0):.0%}")
        
        # For single source rules
        if len(sources) == 2:
            source_label = f"Intersection ({g1_name} ∩ {g2_name})"
        elif g1_name in sources:
            source_label = f"[G1] {g1_name}"
        else:
            source_label = f"[G2] {g2_name}"
        
        ref_display = self._format_ref_for_tooltip(reference)
        ref_line = f"\nRef: {ref_display}" if ref_display and ref_display != 'N/A' else ""
        risk_level = rule.get('risk_level', '')
        risk_line = f"\nRisk: {risk_level}" if risk_level else ""
        jurisdiction = rule.get('jurisdiction', '')
        jurisdiction_line = f"\nJurisdiction: {jurisdiction}" if jurisdiction else ""
        return f"{rule_name}\nSource: {source_label}{ref_line}{risk_line}{jurisdiction_line}"
    
    def generate_union_html(self, data: dict) -> str:
        """Generate HTML for UNION visualization with Agent 6 style."""
        g1_name = data['metadata']['g1_name']
        g2_name = data['metadata']['g2_name']
        rules = data['business_rules']
        stats = data['stats']
        
        # Load contradictions data if available
        contradictions_file = self.input_dir / "contradictions.json"
        contradiction_rule_ids = set()
        contradiction_details = {}  # Map rule_id -> contradiction details
        total_contradictions = 0
        if contradictions_file.exists():
            with open(contradictions_file, 'r') as f:
                contradictions_data = json.load(f)
                # Get total count from stats (matches index.html)
                total_contradictions = contradictions_data.get('stats', {}).get('total_contradictions', 0)
                # Contradictions are stored in 'contradictions' key, not 'business_rules'
                for conflict in contradictions_data.get('contradictions', []):
                    # Add both G1 and G2 rule IDs involved in the contradiction
                    g1_rule_data = conflict.get('g1_rule', {})
                    g2_rule_data = conflict.get('g2_rule', {})
                    g1_rule = g1_rule_data.get('rule', {})
                    g2_rule = g2_rule_data.get('rule', {})
                    
                    if g1_rule.get('rule_id'):
                        contradiction_rule_ids.add(g1_rule['rule_id'])
                        # Store contradiction details for this rule
                        contradiction_details[g1_rule['rule_id']] = {
                            'g1_rule': g1_rule,
                            'g2_rule': g2_rule,
                            'reasoning': conflict.get('reasoning', '')
                        }
                    if g2_rule.get('rule_id'):
                        contradiction_rule_ids.add(g2_rule['rule_id'])
                        # Store contradiction details for this rule
                        contradiction_details[g2_rule['rule_id']] = {
                            'g1_rule': g1_rule,
                            'g2_rule': g2_rule,
                            'reasoning': conflict.get('reasoning', '')
                        }
        
        # Rule type colours — domain-aware (mortgage vs AML)
        type_colors = get_config().get_rule_type_colors()
        
        # Build nodes - rule type category nodes + individual rule nodes
        nodes = []
        edges = []
        rules_by_type = defaultdict(list)
        
        # First pass: group rules by type
        for rule in rules:
            rule_type = rule.get('rule_type', 'unknown')
            rules_by_type[rule_type].append(rule)
        
        # Add rule type category nodes (large boxes like Agent 6)
        for rule_type, type_rules in rules_by_type.items():
            color = type_colors.get(rule_type, '#64748b')
            node_id = f"type_{rule_type}"
            
            nodes.append({
                'id': node_id,
                'label': f"{rule_type.title()}\n({len(type_rules)} rules)",
                'title': f"<b>{rule_type.title()}</b><br>{len(type_rules)} rules in this category",
                'group': 'rule_type',
                'value': 60 + len(type_rules) * 2,
                'color': {
                    'background': color,
                    'border': color,
                    'highlight': {'background': color, 'border': '#ffffff'}
                },
                'font': {'color': '#ffffff', 'size': 16, 'bold': True},
                'shape': 'box',
                'margin': 15,
                'isCategory': True,
                'ruleType': rule_type
            })
        
        # Add individual rule nodes
        for i, rule in enumerate(rules):
            rule_id = rule.get('rule_id', f'rule_{i}')
            rule_type = rule.get('rule_type', 'unknown')
            provenance = rule.get('provenance', {})
            sources = provenance.get('sources', [])
            
            color = type_colors.get(rule_type, '#64748b')
            
            # Determine source type and shape
            if len(sources) == 2:
                source_type = 'merged'
                shape = 'diamond'
                border_color = '#f59e0b'  # Amber border for merged
                confidence = provenance.get('confidence', 0.8)
            elif g1_name in sources:
                source_type = 'g1'
                shape = 'box'
                border_color = '#3b82f6'  # Blue border for G1
                confidence = 1.0
            else:
                source_type = 'g2'
                shape = 'dot'
                border_color = '#10b981'  # Green border for G2
                confidence = 1.0
            
            # Check if this rule is a contradiction
            is_contradiction = rule_id in contradiction_rule_ids
            if is_contradiction:
                border_color = '#ef4444'  # Red border for contradictions
            
            # Store confidence in rule for table
            if 'confidence' not in provenance or provenance['confidence'] is None:
                provenance['confidence'] = confidence
            
            # Lighten the color for individual rules
            lighter_color = self._lighten_color(color)
            
            # Build rich tooltip
            tooltip = self._build_tooltip(rule, g1_name, g2_name)
            
            nodes.append({
                'id': rule_id,
                'label': rule_id[:20],
                'title': tooltip,
                'group': f'rule_{rule_type}',
                'value': 15,
                'color': {
                    'background': lighter_color,
                    'border': border_color,
                    'highlight': {'background': color, 'border': '#ffffff'}
                },
                'font': {'color': '#1e293b', 'size': 10},
                'shape': shape,
                'borderWidth': 3 if is_contradiction else 2,
                'isCategory': False,
                'ruleType': rule_type,
                'sourceType': source_type,
                'isContradiction': is_contradiction,
                'ruleIndex': i
            })
            
            # Add edge from rule to its type category
            edges.append({
                'from': f"type_{rule_type}",
                'to': rule_id,
                'color': {'color': color + '40', 'highlight': color},
                'width': 1,
                'smooth': {'enabled': True, 'type': 'curvedCW', 'roundness': 0.2}
            })
        
        # Build a set of all node IDs for dependency edge validation
        node_ids = {node['id'] for node in nodes}
        
        # Add dependency edges between rules
        dep_colors = {
            'prerequisite': '#b91c1c',      # Dark red
            'sequential': '#7c2d12',        # Dark brown/orange
            'conditional': '#ca8a04',       # Dark gold
            'complementary': '#059669',     # Dark teal
            'contradictory': '#5b21b6',     # Dark purple
            'override': '#be185d',          # Dark pink/magenta
            'validation': '#0e7490'         # Dark cyan
        }
        
        dependency_count = 0
        for rule in rules:
            rule_id = rule.get('rule_id', '')
            dependencies = rule.get('dependencies', [])
            
            for dep in dependencies:
                dep_rule_id = dep.get('depends_on_rule', '')
                dep_type = dep.get('dependency_type', 'related')
                
                # Only add edge if both nodes exist
                if dep_rule_id in node_ids and rule_id in node_ids:
                    edges.append({
                        'from': dep_rule_id,
                        'to': rule_id,
                        'color': {
                            'color': dep_colors.get(dep_type, '#64748b'),
                            'highlight': dep_colors.get(dep_type, '#64748b')
                        },
                        'width': 3,
                        'label': dep_type,
                        'arrows': {'to': {'enabled': True, 'scaleFactor': 0.8}},
                        'smooth': {'enabled': True, 'type': 'curvedCCW', 'roundness': 0.3},
                        'isDependency': True,
                        'dependencyType': dep_type
                    })
                    dependency_count += 1
        
        nodes_json = json.dumps(nodes)
        edges_json = json.dumps(edges)
        rules_json = json.dumps(rules)
        
        return f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>UNION: {g1_name} ∪ {g2_name}</title>
    {self._get_vis_network_script()}
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: #1e293b;
            line-height: 1.6;
            min-height: 100vh;
        }}
        
        .container {{ max-width: 1600px; margin: 0 auto; padding: 20px; }}
        
        header {{
            background: white;
            border-radius: 16px;
            padding: 30px;
            margin-bottom: 20px;
            box-shadow: 0 10px 30px rgba(0,0,0,0.1);
            text-align: center;
        }}
        
        .logo-container {{
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 1rem;
            margin-bottom: 1rem;
        }}
        
        .logo-container img {{
            height: 60px;
            width: auto;
        }}
        
        h1 {{
            font-size: 2.5em;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            margin-bottom: 10px;
        }}
        
        .subtitle {{ color: #64748b; font-size: 1.1em; }}
        
        .stats {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
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
        
        .stat-value {{ font-size: 2.5em; font-weight: 700; }}
        .stat-label {{ font-size: 0.9em; opacity: 0.9; }}
        
        .graph-container {{
            background: white;
            border-radius: 16px;
            padding: 20px;
            margin-bottom: 20px;
            box-shadow: 0 10px 30px rgba(0,0,0,0.1);
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
        
        .graph-controls {{
            display: flex;
            gap: 10px;
            margin-bottom: 15px;
            flex-wrap: wrap;
            justify-content: center;
        }}
        
        .graph-btn {{
            padding: 10px 20px;
            border: 2px solid #e2e8f0;
            background: white;
            border-radius: 8px;
            cursor: pointer;
            font-weight: 600;
            transition: all 0.3s;
        }}
        
        .graph-btn:hover {{
            transform: translateY(-2px);
            box-shadow: 0 4px 12px rgba(0,0,0,0.1);
        }}
        
        .graph-btn.active {{
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            border-color: transparent;
        }}
        
        .graph-btn.g1-active {{ background: #3b82f6; color: white; border-color: #3b82f6; }}
        .graph-btn.g2-active {{ background: #10b981; color: white; border-color: #10b981; }}
        .graph-btn.merged-active {{ background: #f59e0b; color: white; border-color: #f59e0b; }}
        .graph-btn.contradiction-active {{ background: #ef4444; color: white; border-color: #ef4444; }}
        
        .legend {{
            display: flex;
            flex-wrap: wrap;
            gap: 20px;
            margin-top: 20px;
            padding: 20px;
            background: #f8fafc;
            border-radius: 12px;
        }}
        
        .legend-section {{ width: 100%; font-weight: 600; margin-bottom: 10px; }}
        
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
        
        .table-container {{
            background: white;
            border-radius: 16px;
            padding: 20px;
            box-shadow: 0 10px 30px rgba(0,0,0,0.1);
            margin-top: 20px;
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
        }}
        
        .search-box:focus {{
            outline: none;
            border-color: #667eea;
            box-shadow: 0 0 0 3px rgba(102,126,234,0.1);
        }}
        
        .filter-btn {{
            padding: 12px 24px;
            background: white;
            border: 2px solid #e2e8f0;
            border-radius: 8px;
            cursor: pointer;
            font-weight: 500;
            transition: all 0.3s;
        }}
        
        .filter-btn:hover {{
            border-color: #667eea;
            color: #667eea;
        }}
        
        .filter-btn.active {{
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            border-color: transparent;
        }}
        
        table {{
            width: 100%;
            border-collapse: separate;
            border-spacing: 0;
        }}
        
        thead {{
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
        }}
        
        th {{
            padding: 15px 12px;
            text-align: left;
            font-weight: 600;
        }}
        
        td {{
            padding: 12px;
            border-bottom: 1px solid #e2e8f0;
            vertical-align: top;
        }}
        
        tbody tr:hover {{
            background: #f8fafc;
        }}
        
        tbody tr.highlighted {{
            background: #fef3c7 !important;
            box-shadow: 0 0 0 2px #f59e0b;
        }}
        
        .badge {{
            display: inline-block;
            padding: 4px 10px;
            border-radius: 20px;
            font-size: 0.75em;
            font-weight: 600;
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
        
        .badge-merged {{ background: #fef3c7; color: #92400e; }}
        .badge-g1 {{ background: #dbeafe; color: #1e40af; }}
        .badge-g2 {{ background: #d1fae5; color: #065f46; }}
        .badge-contradiction {{ background: #fee2e2; color: #991b1b; }}
        
        .confidence-bar {{
            width: 100px;
            height: 8px;
            background: #e2e8f0;
            border-radius: 4px;
            overflow: hidden;
        }}
        
        .confidence-fill {{
            height: 100%;
            background: linear-gradient(90deg, #f59e0b, #10b981);
            border-radius: 4px;
        }}
        
        .rule-id {{
            font-family: 'Courier New', monospace;
            font-weight: 600;
            color: #667eea;
        }}
        
        .no-results {{
            text-align: center;
            padding: 40px;
            color: #64748b;
        }}
        
        .selected-rule-info {{
            background: #fef3c7;
            border: 2px solid #f59e0b;
            border-radius: 12px;
            padding: 15px;
            margin-bottom: 15px;
            display: none;
        }}
        
        .selected-rule-info.visible {{ display: block; }}
    </style>
</head>
<body>
    <div class="container">
        <header>
            <div class="logo-container">
                <img src="{self._get_logo_base64()}" alt="Policy to Knowledge" />
            </div>
            <h1>[G1] {g1_name}, [G2] {g2_name} - Join Operation Results</h1>
            
            <div class="stats">
                <div class="stat-card">
                    <div class="stat-value">{stats['total_rules']}</div>
                    <div class="stat-label">{g1_name} ∪ {g2_name}</div>
                </div>
                <div class="stat-card" style="background: linear-gradient(135deg, #f59e0b 0%, #d97706 100%);">
                    <div class="stat-value">{stats['merged_rules']}</div>
                    <div class="stat-label">Intersection ({g1_name} ∩ {g2_name})</div>
                </div>
                <div class="stat-card" style="background: linear-gradient(135deg, #3b82f6 0%, #2563eb 100%);">
                    <div class="stat-value">{stats['g1_only_rules']}</div>
                    <div class="stat-label">[G1] {g1_name} Only</div>
                </div>
                <div class="stat-card" style="background: linear-gradient(135deg, #10b981 0%, #059669 100%);">
                    <div class="stat-value">{stats['g2_only_rules']}</div>
                    <div class="stat-label">[G2] {g2_name} Only</div>
                </div>
                <div class="stat-card" style="background: linear-gradient(135deg, #ef4444 0%, #dc2626 100%);">
                    <div class="stat-value">{total_contradictions}</div>
                    <div class="stat-label">Contradictions</div>
                </div>
                <div class="stat-card" style="background: linear-gradient(135deg, #8b5cf6 0%, #7c3aed 100%);">
                    <div class="stat-value">{dependency_count}</div>
                    <div class="stat-label">Dependencies</div>
                </div>
            </div>
        </header>
        
        <div class="graph-container">
            <h2 class="section-title">📊 Knowledge Graph Network</h2>
            <p style="color: #64748b; margin-bottom: 15px; text-align: center;">
                Large boxes = Rule type categories • Small nodes = Individual rules • Arrows = Dependencies • Click a node to see details below
            </p>
            
            <div class="graph-controls">
                <button class="graph-btn active" data-filter="all">All ({stats['total_rules']})</button>
                <button class="graph-btn" data-filter="g1">[G1] {g1_name} Only ({stats['g1_only_rules']})</button>
                <button class="graph-btn" data-filter="g2">[G2] {g2_name} Only ({stats['g2_only_rules']})</button>
                <button class="graph-btn" data-filter="merged">Intersection ({stats['merged_rules']})</button>
                <button class="graph-btn" data-filter="contradiction">Contradictions ({total_contradictions})</button>
            </div>
            
            <div id="network"></div>
            
            <div class="legend">
                <div class="legend-section">Source Shapes:</div>
                <div class="legend-item">
                    <div class="legend-color" style="background: #f59e0b; width: 20px; height: 20px; transform: rotate(45deg);"></div>
                    <span>Intersection (from both graphs)</span>
                </div>
                <div class="legend-item">
                    <div class="legend-color" style="background: #3b82f6; border-radius: 4px;"></div>
                    <span>[G1] {g1_name} Only</span>
                </div>
                <div class="legend-item">
                    <div class="legend-color" style="background: #10b981; border-radius: 50%;"></div>
                    <span>[G2] {g2_name} Only</span>
                </div>
                <div class="legend-item">
                    <div class="legend-color" style="background: #ef4444; border: 3px solid #7f1d1d; border-radius: 4px;"></div>
                    <span>Contradiction</span>
                </div>
            </div>
            
            <div class="legend" style="margin-top: 10px;">
                <div class="legend-section">Rule Type Colors ({len(type_colors) - 1} Categories):</div>
                {chr(10).join(
                    f'<div class="legend-item"><div class="legend-color" style="background: {color};"></div><span>{rule_type.title()}</span></div>'
                    for rule_type, color in type_colors.items()
                    if rule_type != 'unknown'
                )}
            </div>
            
            <div class="legend" style="margin-top: 10px;">
                <div class="legend-section">Dependency Arrows:</div>
                <div class="legend-item"><div style="width: 30px; height: 3px; background: #b91c1c;"></div><span>Prerequisite</span></div>
                <div class="legend-item"><div style="width: 30px; height: 3px; background: #7c2d12;"></div><span>Sequential</span></div>
                <div class="legend-item"><div style="width: 30px; height: 3px; background: #ca8a04;"></div><span>Conditional</span></div>
                <div class="legend-item"><div style="width: 30px; height: 3px; background: #059669;"></div><span>Complementary</span></div>
                <div class="legend-item"><div style="width: 30px; height: 3px; background: #0e7490;"></div><span>Validation</span></div>
            </div>
        </div>
        
        <div class="table-container">
            <h2 class="section-title">📋 Business Rules Details</h2>
            
            <div id="selectedRuleInfo" class="selected-rule-info">
                <strong>Selected Rule:</strong> <span id="selectedRuleId"></span>
                <button onclick="clearSelection()" style="margin-left: 10px; padding: 5px 10px; cursor: pointer;">Clear Selection</button>
            </div>
            
            <div class="controls">
                <input type="text" id="searchBox" class="search-box" placeholder="🔍 Search rules by ID, description...">
                <button class="filter-btn active" data-filter="all">All</button>
                <button class="filter-btn" data-filter="merged">Intersection</button>
                <button class="filter-btn" data-filter="g1">[G1] {g1_name} Only</button>
                <button class="filter-btn" data-filter="g2">[G2] {g2_name} Only</button>
                <button class="filter-btn" data-filter="contradiction">⚠️ Contradictions</button>
            </div>
            
            <table id="rulesTable">
                <thead>
                    <tr>
                        <th>Rule ID</th>
                        <th>Rule Name</th>
                        <th>Type</th>
                        <th>Source</th>
                        <th>Confidence</th>
                        <th>Reference</th>
                        <th>Risk</th>
                        <th>Jurisdiction</th>
                        <th>Description</th>
                    </tr>
                </thead>
                <tbody id="rulesBody"></tbody>
            </table>
            <div id="noResults" class="no-results" style="display: none;">No rules match your criteria</div>
        </div>
    </div>
    
    <script>
        const rulesData = {rules_json};
        const nodesData = {nodes_json};
        const edgesData = {edges_json};
        const g1Name = "{g1_name}";
        const g2Name = "{g2_name}";
        const contradictionIds = {json.dumps(list(contradiction_rule_ids))};
        const contradictionDetails = {json.dumps(contradiction_details)};
        
        // Merge contradiction details into rules
        rulesData.forEach(rule => {{
            if (contradictionDetails[rule.rule_id]) {{
                const details = contradictionDetails[rule.rule_id];
                rule.provenance = rule.provenance || {{}};
                rule.provenance.g1_rule = details.g1_rule;
                rule.provenance.g2_rule = details.g2_rule;
                rule.provenance.reasoning = details.reasoning;
            }}
        }});
        
        let currentFilter = 'all';
        let searchTerm = '';
        let selectedRuleId = null;
        let network = null;
        let allNodes = null;
        let allEdges = null;
        
        document.addEventListener('DOMContentLoaded', function() {{
            try {{
                // Initialize network
                const container = document.getElementById('network');
                allNodes = new vis.DataSet(nodesData);
                allEdges = new vis.DataSet(edgesData);
                
                const data = {{ nodes: allNodes, edges: allEdges }};
                const options = {{
                    nodes: {{
                        font: {{ size: 14, color: '#1e293b' }},
                        borderWidth: 2,
                        borderWidthSelected: 4,
                        shadow: {{ enabled: true, color: 'rgba(0,0,0,0.2)', size: 10 }}
                    }},
                    edges: {{
                        width: 2,
                        smooth: {{ enabled: true, type: 'curvedCW', roundness: 0.2 }},
                        shadow: {{ enabled: true, color: 'rgba(0,0,0,0.1)', size: 5 }}
                    }},
                    physics: {{
                        enabled: true,
                        stabilization: {{ enabled: true, iterations: 200 }},
                        barnesHut: {{
                            gravitationalConstant: -4000,
                            centralGravity: 0.5,
                            springLength: 200,
                            springConstant: 0.02,
                            damping: 0.5
                        }}
                    }},
                    interaction: {{
                        hover: true,
                        tooltipDelay: 100,
                        navigationButtons: true,
                        keyboard: true
                    }}
                }};
                
                network = new vis.Network(container, data, options);
                
                // Click on node → show in table
                network.on("click", function(params) {{
                    if (params.nodes.length > 0) {{
                        const nodeId = params.nodes[0];
                        const node = allNodes.get(nodeId);
                        
                        if (node && !node.isCategory) {{
                            // Find the rule
                            const rule = rulesData.find(r => r.rule_id === nodeId);
                            if (rule) {{
                                selectedRuleId = nodeId;
                                document.getElementById('selectedRuleInfo').classList.add('visible');
                                document.getElementById('selectedRuleId').textContent = nodeId;
                                
                                // Set search to this rule
                                document.getElementById('searchBox').value = nodeId;
                                filterRules();
                                
                                // Scroll to table
                                document.getElementById('rulesTable').scrollIntoView({{ behavior: 'smooth' }});
                            }}
                        }} else if (node && node.isCategory) {{
                            // Clicked on category - filter by rule type
                            document.getElementById('searchBox').value = node.ruleType;
                            filterRules();
                        }}
                    }}
                }});
                
                // Graph filter buttons
                document.querySelectorAll('.graph-btn').forEach(btn => {{
                    btn.addEventListener('click', function() {{
                        document.querySelectorAll('.graph-btn').forEach(b => {{
                            b.classList.remove('active', 'g1-active', 'g2-active', 'merged-active', 'contradiction-active');
                        }});
                        
                        const filter = this.dataset.filter;
                        this.classList.add('active');
                        if (filter === 'g1') this.classList.add('g1-active');
                        if (filter === 'g2') this.classList.add('g2-active');
                        if (filter === 'merged') this.classList.add('merged-active');
                        if (filter === 'contradiction') this.classList.add('contradiction-active');
                        
                        filterGraph(filter);
                    }});
                }});
                
                // Table filter buttons
                document.querySelectorAll('.filter-btn').forEach(btn => {{
                    btn.addEventListener('click', function() {{
                        document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
                        this.classList.add('active');
                        currentFilter = this.dataset.filter;
                        filterRules();
                    }});
                }});
                
                // Search
                document.getElementById('searchBox').addEventListener('input', function() {{
                    searchTerm = this.value.toLowerCase();
                    filterRules();
                }});
                
                // Initial table
                populateTable(rulesData);
                
            }} catch (error) {{
                console.error('Error:', error);
                document.getElementById('network').innerHTML = '<div style="padding: 20px; color: red;">Error: ' + error.message + '</div>';
            }}
        }});
        
        function filterGraph(filter) {{
            const filteredNodes = nodesData.filter(node => {{
                if (node.isCategory) {{
                    // Keep categories if they have matching rules
                    if (filter === 'all') return true;
                    const typeRules = rulesData.filter(r => r.rule_type === node.ruleType);
                    return typeRules.some(r => matchesFilter(r, filter));
                }}
                
                const rule = rulesData.find(r => r.rule_id === node.id);
                if (!rule) return filter === 'all';
                return matchesFilter(rule, filter);
            }});
            
            const filteredNodeIds = new Set(filteredNodes.map(n => n.id));
            const filteredEdges = edgesData.filter(e => 
                filteredNodeIds.has(e.from) && filteredNodeIds.has(e.to)
            );
            
            allNodes.clear();
            allNodes.add(filteredNodes);
            allEdges.clear();
            allEdges.add(filteredEdges);
            
            network.fit();
        }}
        
        function matchesFilter(rule, filter) {{
            const prov = rule.provenance || {{}};
            const sources = prov.sources || [];
            const isContradiction = contradictionIds.includes(rule.rule_id);
            
            if (filter === 'all') return true;
            if (filter === 'merged') return sources.length === 2;
            if (filter === 'g1') return sources.length === 1 && sources[0] === g1Name;
            if (filter === 'g2') return sources.length === 1 && sources[0] === g2Name;
            if (filter === 'contradiction') return isContradiction;
            return true;
        }}
        
        function filterRules() {{
            searchTerm = document.getElementById('searchBox').value.toLowerCase();
            
            const filtered = rulesData.filter(rule => {{
                // Apply source filter
                if (!matchesFilter(rule, currentFilter)) return false;
                
                // Apply search
                if (searchTerm) {{
                    const searchable = (rule.rule_id || '') + ' ' + (rule.rule_name || '') + ' ' + (rule.description || '');
                    if (!searchable.toLowerCase().includes(searchTerm)) return false;
                }}
                
                return true;
            }});
            
            populateTable(filtered);
        }}
        
        function populateTable(rules) {{
            const tbody = document.getElementById('rulesBody');
            const noResults = document.getElementById('noResults');
            
            if (rules.length === 0) {{
                tbody.innerHTML = '';
                noResults.style.display = 'block';
                return;
            }}
            
            noResults.style.display = 'none';
            
            tbody.innerHTML = rules.slice(0, 200).map(rule => {{
                const prov = rule.provenance || {{}};
                const sources = prov.sources || [];
                const conf = prov.confidence || (sources.length === 1 ? 1.0 : 0.8);
                const isContradiction = contradictionIds.includes(rule.rule_id);
                
                let sourceLabel, sourceBadge;
                if (isContradiction) {{
                    sourceLabel = '⚠️ Contradiction';
                    sourceBadge = 'badge-contradiction';
                }} else if (sources.length === 2) {{
                    sourceLabel = 'Intersection';
                    sourceBadge = 'badge-merged';
                }} else if (sources[0] === g1Name) {{
                    sourceLabel = g1Name;
                    sourceBadge = 'badge-g1';
                }} else {{
                    sourceLabel = g2Name;
                    sourceBadge = 'badge-g2';
                }}
                
                const isHighlighted = selectedRuleId === rule.rule_id;
                
                // For intersection and contradiction rules, show both G1 and G2 details
                const g1Rule = prov.g1_rule || {{}};
                const g2Rule = prov.g2_rule || {{}};
                const isMerged = sources.length === 2 && g1Rule.rule_id && g2Rule.rule_id;
                
                let ruleNameCell, descriptionCell;
                if (isContradiction && g1Rule.rule_id && g2Rule.rule_id) {{
                    // Show contradiction details
                    ruleNameCell = `
                        <div style="margin-bottom: 8px; padding: 8px; background: #eff6ff; border-radius: 6px; border-left: 3px solid #3b82f6;">
                            <small style="color: #3b82f6; font-weight: 600;">[G1] ${{g1Name}}</small><br>
                            <strong>${{g1Rule.rule_name || 'N/A'}}</strong>
                        </div>
                        <div style="padding: 8px; background: #f0fdf4; border-radius: 6px; border-left: 3px solid #10b981;">
                            <small style="color: #10b981; font-weight: 600;">[G2] ${{g2Name}}</small><br>
                            <strong>${{g2Rule.rule_name || 'N/A'}}</strong>
                        </div>
                    `;
                    descriptionCell = `
                        <div style="margin-bottom: 8px; padding: 8px; background: #eff6ff; border-radius: 6px;">
                            <small style="color: #3b82f6; font-weight: 600;">[G1]</small>
                            <div style="font-size: 0.85em;">${{g1Rule.description || 'N/A'}}</div>
                        </div>
                        <div style="margin-bottom: 8px; padding: 8px; background: #f0fdf4; border-radius: 6px;">
                            <small style="color: #10b981; font-weight: 600;">[G2]</small>
                            <div style="font-size: 0.85em;">${{g2Rule.description || 'N/A'}}</div>
                        </div>
                        <div style="padding: 8px; background: #fef2f2; border-radius: 6px; border-left: 3px solid #ef4444;">
                            <small style="color: #991b1b; font-weight: 600;">⚠️ Conflict:</small>
                            <div style="font-size: 0.85em; font-style: italic; color: #7f1d1d;">${{prov.reasoning || 'These rules contradict each other'}}</div>
                        </div>
                    `;
                }} else if (isMerged) {{
                    // Show intersection details
                    ruleNameCell = `
                        <div style="margin-bottom: 8px; padding: 8px; background: #eff6ff; border-radius: 6px; border-left: 3px solid #3b82f6;">
                            <small style="color: #3b82f6; font-weight: 600;">[G1] ${{g1Name}}</small><br>
                            <strong>${{g1Rule.rule_name || 'N/A'}}</strong>
                        </div>
                        <div style="padding: 8px; background: #f0fdf4; border-radius: 6px; border-left: 3px solid #10b981;">
                            <small style="color: #10b981; font-weight: 600;">[G2] ${{g2Name}}</small><br>
                            <strong>${{g2Rule.rule_name || 'N/A'}}</strong>
                        </div>
                    `;
                    descriptionCell = `
                        <div style="margin-bottom: 8px; padding: 8px; background: #eff6ff; border-radius: 6px;">
                            <small style="color: #3b82f6; font-weight: 600;">[G1]</small>
                            <div style="font-size: 0.85em;">${{g1Rule.description || 'N/A'}}</div>
                        </div>
                        <div style="padding: 8px; background: #f0fdf4; border-radius: 6px;">
                            <small style="color: #10b981; font-weight: 600;">[G2]</small>
                            <div style="font-size: 0.85em;">${{g2Rule.description || 'N/A'}}</div>
                        </div>
                        <div style="margin-top: 8px; padding: 8px; background: #fef3c7; border-radius: 6px;">
                            <small style="color: #b45309; font-weight: 600;">Match Reasoning:</small>
                            <div style="font-size: 0.85em; font-style: italic;">${{prov.reasoning || 'N/A'}}</div>
                        </div>
                    `;
                }} else {{
                    ruleNameCell = `<strong>${{rule.rule_name || 'N/A'}}</strong>`;
                    descriptionCell = rule.description || '';
                }}
                
                // Format structured source_reference
                let refDisplay = 'N/A';
                const srcRef = rule.source_reference || rule.legacy_source_reference;
                if (srcRef && typeof srcRef === 'object' && !Array.isArray(srcRef)) {{
                    const cp = srcRef.chunk_path || '';
                    const sec = srcRef.section_id && srcRef.section_id !== 'N/A' ? ` | ${{srcRef.section_id}}` : '';
                    const wp = (typeof srcRef.start_word_position === 'number' && typeof srcRef.end_word_position === 'number')
                        ? ` <span class="badge" style="font-size:0.6em;background:#e2e8f0;color:#475569;">w${{srcRef.start_word_position}}-${{srcRef.end_word_position}}</span>` : '';
                    refDisplay = `${{cp}}${{sec}}${{wp}}`;
                }} else if (Array.isArray(srcRef)) {{
                    refDisplay = srcRef.map(r => typeof r === 'object' ? (r.chunk_path || '') : String(r)).join('<br/>');
                }} else if (typeof srcRef === 'string' && srcRef) {{
                    refDisplay = srcRef;
                }}

                return `
                    <tr data-rule-id="${{rule.rule_id}}" class="${{isHighlighted ? 'highlighted' : ''}}">
                        <td><span class="rule-id">${{rule.rule_id}}</span></td>
                        <td>${{ruleNameCell}}</td>
                        <td><span class="badge badge-${{rule.rule_type || 'unknown'}}">${{(rule.rule_type || 'unknown').toUpperCase()}}</span></td>
                        <td><span class="badge ${{sourceBadge}}">${{sourceLabel}}</span></td>
                        <td>
                            <div class="confidence-bar">
                                <div class="confidence-fill" style="width: ${{conf * 100}}%"></div>
                            </div>
                            <small>${{(conf * 100).toFixed(0)}}%</small>
                        </td>
                        <td><small>${{refDisplay}}</small></td>
                        <td><span class="badge badge-${{(rule.risk_level || 'unknown').toLowerCase()}}">${{(rule.risk_level || 'N/A').toUpperCase()}}</span></td>
                        <td><small>${{rule.jurisdiction || 'N/A'}}</small></td>
                        <td>${{descriptionCell}}</td>
                    </tr>
                `;
            }}).join('');
        }}
        
        function clearSelection() {{
            selectedRuleId = null;
            document.getElementById('selectedRuleInfo').classList.remove('visible');
            document.getElementById('searchBox').value = '';
            filterRules();
        }}
    </script>
</body>
</html>'''
    
    def _lighten_color(self, hex_color: str) -> str:
        """Lighten a hex color."""
        hex_color = hex_color.lstrip('#')
        r = int(hex_color[0:2], 16)
        g = int(hex_color[2:4], 16)
        b = int(hex_color[4:6], 16)
        r = int(r * 0.6 + 255 * 0.4)
        g = int(g * 0.6 + 255 * 0.4)
        b = int(b * 0.6 + 255 * 0.4)
        return f'#{r:02x}{g:02x}{b:02x}'
    
    def generate_intersection_html(self, data: dict) -> str:
        """Generate HTML for INTERSECTION visualization with original descriptions."""
        g1_name = data['metadata']['g1_name']
        g2_name = data['metadata']['g2_name']
        rules = data['business_rules']
        stats = data['stats']
        
        # Load original rules to get descriptions
        g1_rules = self._load_original_rules(g1_name)
        g2_rules = self._load_original_rules(g2_name)
        
        # Enrich rules with original descriptions
        enriched_rules = []
        for rule in rules:
            enriched = rule.copy()
            prov = rule.get('provenance', {})
            original_ids = prov.get('original_ids', {})
            
            g1_id = original_ids.get(g1_name, '')
            g2_id = original_ids.get(g2_name, '')
            
            # Get original descriptions
            g1_orig = g1_rules.get(g1_id, {})
            g2_orig = g2_rules.get(g2_id, {})
            
            enriched['g1_description'] = g1_orig.get('description', '')
            enriched['g2_description'] = g2_orig.get('description', '')
            enriched_rules.append(enriched)
        
        # All rules are matched - use ellipse
        nodes = []
        for i, rule in enumerate(enriched_rules):
            prov = rule.get('provenance', {})
            original_ids = prov.get('original_ids', {})
            confidence = prov.get('confidence', 0)
            
            # Build tooltip
            tooltip = self._build_tooltip(rule, g1_name, g2_name)
            
            nodes.append({
                'id': i,
                'label': f"{original_ids.get(g1_name, '?')[:15]}\n{original_ids.get(g2_name, '?')[:15]}",
                'shape': 'ellipse',
                'color': {
                    'background': f'rgba(16, 185, 129, {0.3 + confidence * 0.7})',
                    'border': '#10b981'
                },
                'title': tooltip,
                'group': rule.get('rule_type', 'unknown')
            })
        
        nodes_json = json.dumps(nodes)
        rules_json = json.dumps(enriched_rules)
        
        return f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>INTERSECTION: {g1_name} ∩ {g2_name}</title>
    {self._get_vis_network_script()}
    <style>{self._get_common_styles()}</style>
</head>
<body>
    <div class="header">
        <div class="logo-container">
            <img src="{self._get_logo_base64()}" alt="Policy to Knowledge" />
        </div>
        <h1>INTERSECTION: {g1_name} ∩ {g2_name}</h1>
        <p class="subtitle">Rules present in BOTH knowledge graphs</p>
    </div>
    
    <div class="stats-grid">
        <div class="stat-card">
            <div class="stat-value">{stats['total_rules']}</div>
            <div class="stat-label">Shared Rules</div>
        </div>
        <div class="stat-card">
            <div class="stat-value">{stats['by_match_type'].get('IDENTICAL', 0)}</div>
            <div class="stat-label">Identical</div>
        </div>
        <div class="stat-card">
            <div class="stat-value">{stats['by_match_type'].get('EQUIVALENT', 0)}</div>
            <div class="stat-label">Equivalent</div>
        </div>
    </div>
    
    <div class="legend">
        <div class="legend-item">
            <div class="legend-shape legend-ellipse"></div>
            <span>Matched Rules (shows both IDs)</span>
        </div>
        <div class="legend-item">
            <span>Ellipse size = Confidence level</span>
        </div>
    </div>
    
    <div id="graph" class="graph-container"></div>
    
    <h2 style="margin: 2rem 0 1rem; color: white; text-shadow: 0 2px 4px rgba(0,0,0,0.3);">Matched Rules</h2>
    
    <table class="rules-table">
        <thead>
            <tr>
                <th>{g1_name} ID</th>
                <th>{g1_name} Ref</th>
                <th>{g1_name} Description</th>
                <th>{g2_name} ID</th>
                <th>{g2_name} Ref</th>
                <th>{g2_name} Description</th>
                <th>Type</th>
                <th>Match</th>
                <th>Confidence</th>
                <th>Reasoning</th>
            </tr>
        </thead>
        <tbody id="rulesBody">
        </tbody>
    </table>
    
    <script>
        const rules = {rules_json};
        const nodes = new vis.DataSet({nodes_json});
        const edges = new vis.DataSet([]);
        const g1Name = "{g1_name}";
        const g2Name = "{g2_name}";
        let selectedNodeId = null;
        
        const container = document.getElementById('graph');
        const network = new vis.Network(container, {{nodes, edges}}, {{
            physics: {{ solver: 'forceAtlas2Based' }}
        }});
        
        // Click handler to filter table
        network.on('click', function(params) {{
            if (params.nodes.length > 0) {{
                selectedNodeId = params.nodes[0];
                renderTable();
            }} else {{
                selectedNodeId = null;
                renderTable();
            }}
        }});
        
        function renderTable() {{
            const tbody = document.getElementById('rulesBody');
            const rulesToShow = selectedNodeId !== null ? [rules[selectedNodeId]] : rules;
            
            tbody.innerHTML = rulesToShow.map((rule, idx) => {{
                const prov = rule.provenance || {{}};
                const ids = prov.original_ids || {{}};
                const conf = prov.confidence || 0;
                const isHighlighted = selectedNodeId !== null;
                
                return `
                    <tr class="${{isHighlighted ? 'highlighted' : ''}}">
                        <td>${{ids[g1Name] || '?'}}</td>
                        <td><small>${{rule.g1_reference || 'N/A'}}</small></td>
                        <td style="max-width: 300px; font-size: 12px;">${{rule.g1_description || ''}}</td>
                        <td>${{ids[g2Name] || '?'}}</td>
                        <td><small>${{rule.g2_reference || 'N/A'}}</small></td>
                        <td style="max-width: 300px; font-size: 12px;">${{rule.g2_description || ''}}</td>
                        <td><span class="badge badge-${{rule.rule_type || 'unknown'}}">${{rule.rule_type || 'unknown'}}</span></td>
                        <td><span class="badge badge-merged">${{prov.match_type || 'EQUIVALENT'}}</span></td>
                        <td>
                            <div class="confidence-bar">
                                <div class="confidence-fill" style="width: ${{conf * 100}}%"></div>
                            </div>
                            ${{(conf * 100).toFixed(0)}}%
                        </td>
                        <td style="max-width: 300px; font-size: 12px;">${{prov.reasoning || ''}}</td>
                    </tr>
                `;
            }}).join('');
        }}
        
        // Initial render
        renderTable();
    </script>
</body>
</html>'''
    
    def generate_difference_html(self, data: dict, is_g1: bool) -> str:
        """Generate HTML for G1-G2 or G2-G1 visualization with dependencies."""
        g1_name = data['metadata']['g1_name']
        g2_name = data['metadata']['g2_name']
        rules = data['business_rules']
        stats = data['stats']
        
        if is_g1:
            title = f"{g1_name} - {g2_name}"
            subtitle = f"Rules in {g1_name} NOT found in {g2_name}"
            shape = 'box'  # Rectangle for G1
            color = '#3b82f6'
        else:
            title = f"{g2_name} - {g1_name}"
            subtitle = f"Rules in {g2_name} NOT found in {g1_name}"
            shape = 'dot'  # Circle for G2
            color = '#10b981'
        
        # Group by type
        rules_by_type = defaultdict(list)
        for rule in rules:
            rules_by_type[rule.get('rule_type', 'unknown')].append(rule)
        
        # Build rule_id to index map for dependency edges
        rule_id_to_idx = {rule.get('rule_id', ''): i for i, rule in enumerate(rules)}
        
        nodes = []
        edges = []
        
        # Dependency type colors (same as Agent 6)
        dep_colors = {
            'prerequisite': '#b91c1c',
            'sequential': '#7c2d12',
            'conditional': '#ca8a04',
            'complementary': '#059669',
            'contradictory': '#5b21b6',
            'override': '#be185d',
            'validation': '#0e7490'
        }
        
        for i, rule in enumerate(rules):
            # Build tooltip
            tooltip = self._build_tooltip(rule, g1_name, g2_name)
            
            nodes.append({
                'id': i,
                'label': rule.get('rule_id', 'Unknown')[:25],
                'shape': shape,
                'color': {'background': color, 'border': color},
                'title': tooltip,
                'group': rule.get('rule_type', 'unknown')
            })
            
            # Add dependency edges
            for dep in rule.get('dependencies', []):
                dep_rule_id = dep.get('depends_on_rule', '')
                if dep_rule_id in rule_id_to_idx:
                    dep_type = dep.get('dependency_type', 'related')
                    edges.append({
                        'from': rule_id_to_idx[dep_rule_id],
                        'to': i,
                        'color': {'color': dep_colors.get(dep_type, '#666666')},
                        'arrows': 'to',
                        'dashes': dep_type == 'conditional',
                        'title': f"{dep_type.upper()}: {dep.get('rationale', '')[:100]}"
                    })
        
        nodes_json = json.dumps(nodes)
        edges_json = json.dumps(edges)
        rules_json = json.dumps(rules)
        type_stats_json = json.dumps({k: len(v) for k, v in rules_by_type.items()})
        
        # Count dependencies
        dep_count = len(edges)
        
        shape_desc = "Rectangle" if is_g1 else "Circle"
        
        return f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title}</title>
    {self._get_vis_network_script()}
    <style>{self._get_common_styles()}</style>
</head>
<body>
    <div class="header">
        <div class="logo-container">
            <img src="{self._get_logo_base64()}" alt="Policy to Knowledge" />
        </div>
        <h1>{title}</h1>
        <p class="subtitle">{subtitle}</p>
    </div>
    
    <div class="stats-grid">
        <div class="stat-card">
            <div class="stat-value">{stats['total_rules']}</div>
            <div class="stat-label">Exclusive Rules</div>
        </div>
        <div class="stat-card">
            <div class="stat-value">{dep_count}</div>
            <div class="stat-label">Dependencies</div>
        </div>
    </div>
    
    <div class="legend">
        <div class="legend-item">
            <div class="legend-shape {'legend-rect' if is_g1 else 'legend-circle'}"></div>
            <span>{shape_desc} = Rules exclusive to this graph</span>
        </div>
    </div>
    
    <div id="graph" class="graph-container"></div>
    
    <h2 style="margin: 2rem 0 1rem; color: white; text-shadow: 0 2px 4px rgba(0,0,0,0.3);">Exclusive Rules</h2>
    
    <table class="rules-table">
        <thead>
            <tr>
                <th>Rule ID</th>
                <th>Type</th>
                <th>Reference</th>
                <th>Risk</th>
                <th>Jurisdiction</th>
                <th>Description</th>
            </tr>
        </thead>
        <tbody id="rulesBody">
        </tbody>
    </table>
    
    <script>
        const rules = {rules_json};
        const nodes = new vis.DataSet({nodes_json});
        const edges = new vis.DataSet({edges_json});
        let selectedNodeId = null;
        
        const container = document.getElementById('graph');
        const network = new vis.Network(container, {{nodes, edges}}, {{
            physics: {{ solver: 'forceAtlas2Based' }},
            edges: {{
                smooth: {{ type: 'curvedCW', roundness: 0.2 }}
            }}
        }});
        
        // Click handler to filter table
        network.on('click', function(params) {{
            if (params.nodes.length > 0) {{
                selectedNodeId = params.nodes[0];
                renderTable();
            }} else {{
                selectedNodeId = null;
                renderTable();
            }}
        }});
        
        function renderTable() {{
            const tbody = document.getElementById('rulesBody');
            const rulesToShow = selectedNodeId !== null ? [rules[selectedNodeId]] : rules;
            
            tbody.innerHTML = rulesToShow.map(rule => {{
                const isHighlighted = selectedNodeId !== null;
                // Format structured source_reference
                let refDisplay = 'N/A';
                const srcRef = rule.source_reference || rule.legacy_source_reference;
                if (srcRef && typeof srcRef === 'object' && !Array.isArray(srcRef)) {{
                    const cp = srcRef.chunk_path || '';
                    const sec = srcRef.section_id && srcRef.section_id !== 'N/A' ? ` | ${{srcRef.section_id}}` : '';
                    const wp = (typeof srcRef.start_word_position === 'number' && typeof srcRef.end_word_position === 'number')
                        ? ` <span class="badge" style="font-size:0.6em;background:#e2e8f0;color:#475569;">w${{srcRef.start_word_position}}-${{srcRef.end_word_position}}</span>` : '';
                    refDisplay = `${{cp}}${{sec}}${{wp}}`;
                }} else if (Array.isArray(srcRef)) {{
                    refDisplay = srcRef.map(r => typeof r === 'object' ? (r.chunk_path || '') : String(r)).join('<br/>');
                }} else if (typeof srcRef === 'string' && srcRef) {{
                    refDisplay = srcRef;
                }}

                return `
                    <tr class="${{isHighlighted ? 'highlighted' : ''}}">
                        <td>${{rule.rule_id || 'Unknown'}}</td>
                        <td><span class="badge badge-${{rule.rule_type || 'unknown'}}">${{rule.rule_type || 'unknown'}}</span></td>
                        <td><small>${{refDisplay}}</small></td>
                        <td><span class="badge badge-${{(rule.risk_level || 'unknown').toLowerCase()}}">${{(rule.risk_level || 'N/A').toUpperCase()}}</span></td>
                        <td><small>${{rule.jurisdiction || 'N/A'}}</small></td>
                        <td>${{rule.description || ''}}</td>
                    </tr>
                `;
            }}).join('');
        }}
        
        // Initial render
        renderTable();
    </script>
</body>
</html>'''
    
    def generate_contradictions_html(self, data: dict) -> str:
        """Generate HTML for CONTRADICTIONS visualization."""
        g1_name = data['metadata']['g1_name']
        g2_name = data['metadata']['g2_name']
        contradictions = data['contradictions']
        stats = data['stats']
        
        # Create nodes for both rules in each contradiction
        nodes = []
        edges = []
        
        for i, conflict in enumerate(contradictions):
            g1_rule = conflict['g1_rule']['rule']
            g2_rule = conflict['g2_rule']['rule']
            
            # G1 rule - rectangle
            nodes.append({
                'id': f'g1_{i}',
                'label': g1_rule.get('rule_id', '?')[:20],
                'shape': 'box',
                'color': {'background': '#3b82f6', 'border': '#3b82f6'},
                'title': f"{g1_rule.get('rule_name', 'N/A')}\nSource: [G1] {g1_name}"
            })
            
            # G2 rule - circle
            nodes.append({
                'id': f'g2_{i}',
                'label': g2_rule.get('rule_id', '?')[:20],
                'shape': 'dot',
                'color': {'background': '#10b981', 'border': '#10b981'},
                'title': f"{g2_rule.get('rule_name', 'N/A')}\nSource: [G2] {g2_name}"
            })
            
            # Conflict edge with simple tooltip
            conflict_tooltip = f"CONFLICT: {conflict.get('conflict_type', 'UNKNOWN')}\n{g1_rule.get('rule_id', '?')} vs {g2_rule.get('rule_id', '?')}"
            
            # Conflict edge
            edges.append({
                'from': f'g1_{i}',
                'to': f'g2_{i}',
                'color': {'color': '#ef4444'},
                'width': 3,
                'dashes': True,
                'title': conflict_tooltip
            })
        
        nodes_json = json.dumps(nodes)
        edges_json = json.dumps(edges)
        contradictions_json = json.dumps(contradictions)
        
        return f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>CONTRADICTIONS: {g1_name} vs {g2_name}</title>
    {self._get_vis_network_script()}
    <style>
        {self._get_common_styles()}
        
        .conflict-card {{
            background: var(--bg-card);
            border: 2px solid var(--danger);
            border-radius: 12px;
            padding: 1.5rem;
            margin-bottom: 1rem;
        }}
        
        .conflict-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 1rem;
        }}
        
        .conflict-rules {{
            display: grid;
            grid-template-columns: 1fr auto 1fr;
            gap: 1rem;
            align-items: start;
        }}
        
        .conflict-rule {{
            background: var(--bg-card-hover);
            padding: 1rem;
            border-radius: 8px;
        }}
        
        .conflict-vs {{
            display: flex;
            align-items: center;
            font-size: 1.5rem;
            color: var(--danger);
            font-weight: bold;
        }}
        
        .g1-label {{ color: #3b82f6; }}
        .g2-label {{ color: #10b981; }}
    </style>
</head>
<body>
    <div class="header">
        <div class="logo-container">
            <img src="{self._get_logo_base64()}" alt="Policy to Knowledge" />
        </div>
        <h1>⚠️ CONTRADICTIONS</h1>
        <p class="subtitle">Conflicting rules between {g1_name} and {g2_name}</p>
    </div>
    
    <div class="stats-grid">
        <div class="stat-card">
            <div class="stat-value">{stats['total_contradictions']}</div>
            <div class="stat-label">Total Conflicts</div>
        </div>
    </div>
    
    <div class="legend">
        <div class="legend-item">
            <div class="legend-shape legend-rect"></div>
            <span class="g1-label">{g1_name} Rule</span>
        </div>
        <div class="legend-item">
            <div class="legend-shape legend-circle"></div>
            <span class="g2-label">{g2_name} Rule</span>
        </div>
        <div class="legend-item">
            <span style="color: #ef4444">━━━ Conflict Link</span>
        </div>
    </div>
    
    <div id="graph" class="graph-container"></div>
    
    <h2 style="margin: 2rem 0 1rem; color: white; text-shadow: 0 2px 4px rgba(0,0,0,0.3);">Conflict Details</h2>
    
    <div id="conflictsList"></div>
    
    <script>
        const contradictions = {contradictions_json};
        const nodes = new vis.DataSet({nodes_json});
        const edges = new vis.DataSet({edges_json});
        const g1Name = "{g1_name}";
        const g2Name = "{g2_name}";
        
        const container = document.getElementById('graph');
        const network = new vis.Network(container, {{nodes, edges}}, {{
            physics: {{ solver: 'forceAtlas2Based' }},
            edges: {{
                smooth: {{ type: 'continuous' }}
            }}
        }});
        
        // Render conflict cards
        const list = document.getElementById('conflictsList');
        contradictions.forEach((conflict, i) => {{
            const g1Rule = conflict.g1_rule.rule;
            const g2Rule = conflict.g2_rule.rule;
            const detail = conflict.conflict_detail || {{}};
            
            const card = document.createElement('div');
            card.className = 'conflict-card';
            card.innerHTML = `
                <div class="conflict-header">
                    <span class="badge badge-conflict">${{conflict.conflict_type || 'CONFLICT'}}</span>
                    <span>Confidence: ${{((conflict.confidence || 0) * 100).toFixed(0)}}%</span>
                </div>
                <div class="conflict-rules">
                    <div class="conflict-rule">
                        <div class="g1-label" style="font-weight: bold; margin-bottom: 0.5rem;">📦 ${{g1Name}}</div>
                        <div style="background: #eff6ff; padding: 0.75rem; border-radius: 6px; border-left: 3px solid #3b82f6;">
                            <div style="font-weight: 600; margin-bottom: 0.25rem;">${{g1Rule.rule_id || '?'}}</div>
                            <div style="font-weight: 500; color: #1e40af; margin-bottom: 0.5rem;">${{g1Rule.rule_name || 'N/A'}}</div>
                            <div style="font-size: 0.875rem; color: #64748b; line-height: 1.5;">${{g1Rule.description || 'No description'}}</div>
                        </div>
                        <div style="margin-top: 0.75rem; padding: 0.5rem; background: #fef3c7; border-radius: 6px;">
                            <strong style="color: #92400e;">Conflicting Value:</strong> 
                            <span style="color: #b45309;">${{detail.g1_value || 'N/A'}}</span>
                        </div>
                    </div>
                    <div class="conflict-vs">⚡</div>
                    <div class="conflict-rule">
                        <div class="g2-label" style="font-weight: bold; margin-bottom: 0.5rem;">⬤ ${{g2Name}}</div>
                        <div style="background: #f0fdf4; padding: 0.75rem; border-radius: 6px; border-left: 3px solid #10b981;">
                            <div style="font-weight: 600; margin-bottom: 0.25rem;">${{g2Rule.rule_id || '?'}}</div>
                            <div style="font-weight: 500; color: #047857; margin-bottom: 0.5rem;">${{g2Rule.rule_name || 'N/A'}}</div>
                            <div style="font-size: 0.875rem; color: #64748b; line-height: 1.5;">${{g2Rule.description || 'No description'}}</div>
                        </div>
                        <div style="margin-top: 0.75rem; padding: 0.5rem; background: #fef3c7; border-radius: 6px;">
                            <strong style="color: #92400e;">Conflicting Value:</strong> 
                            <span style="color: #b45309;">${{detail.g2_value || 'N/A'}}</span>
                        </div>
                    </div>
                </div>
                <div style="margin-top: 1rem; padding: 1rem; border-top: 2px solid var(--border); background: #fef2f2; border-radius: 6px;">
                    <div style="font-weight: 600; color: #991b1b; margin-bottom: 0.5rem;">⚠️ Conflict Rationale:</div>
                    <div style="font-size: 0.875rem; line-height: 1.6; color: #450a0a;">${{conflict.reasoning || 'These rules define conflicting requirements or values for the same business scenario.'}}</div>
                </div>
                <div style="margin-top: 1rem; padding: 1rem; background: #eff6ff; border-radius: 6px; border-left: 3px solid #2563eb;">
                    <div style="font-weight: 600; color: #1e40af; margin-bottom: 0.5rem;">💡 Resolution Hint:</div>
                    <div style="font-size: 0.875rem; line-height: 1.6; color: #1e3a8a;">${{detail.resolution_hint || 'Manual review required to determine which rule should take precedence based on business requirements and regulatory compliance.'}}</div>
                </div>
            `;
            list.appendChild(card);
        }});
    </script>
</body>
</html>'''
    
    def generate_summary_html(self, all_results: dict) -> str:
        """Generate a summary page with Venn diagram."""
        union = all_results['union']
        intersection = all_results['intersection']
        g1_minus_g2 = all_results['g1_minus_g2']
        g2_minus_g1 = all_results['g2_minus_g1']
        contradictions = all_results['contradictions']
        
        g1_name = union['metadata']['g1_name']
        g2_name = union['metadata']['g2_name']
        
        # Calculate values for Venn diagram
        g1_only = g1_minus_g2['stats']['total_rules']
        g2_only = g2_minus_g1['stats']['total_rules']
        both = intersection['stats']['total_rules']
        conflicts = contradictions['stats']['total_contradictions']
        
        return f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Merge Summary: {g1_name} vs {g2_name}</title>
    <style>
        {self._get_common_styles()}
        
        .nav-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
            gap: 15px;
            margin-top: 20px;
        }}
        
        .nav-card {{
            background: white;
            border-radius: 12px;
            padding: 20px;
            text-decoration: none;
            color: #1e293b;
            border: 2px solid #e2e8f0;
            transition: all 0.3s;
            box-shadow: 0 4px 15px rgba(0,0,0,0.05);
        }}
        
        .nav-card:hover {{
            border-color: #667eea;
            transform: translateY(-3px);
            box-shadow: 0 10px 30px rgba(0,0,0,0.1);
        }}
        
        .nav-card h3 {{
            font-size: 1.25em;
            margin-bottom: 8px;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
        }}
        
        .nav-card p {{
            color: #64748b;
            font-size: 0.9em;
        }}
        
        .venn-container {{
            display: flex;
            justify-content: center;
            padding: 20px;
        }}
    </style>
</head>
<body>
    <div class="header">
        <div class="logo-container">
            <img src="{self._get_logo_base64()}" alt="Policy to Knowledge" />
        </div>
        <h1>Knowledge Graph Merge Summary</h1>
        <p class="subtitle">{g1_name} vs {g2_name}</p>
    </div>
    
    <div class="stats-grid">
        <div class="stat-card">
            <div class="stat-value">{union['stats']['total_rules']}</div>
            <div class="stat-label">Union (All Unique)</div>
        </div>
        <div class="stat-card">
            <div class="stat-value">{both}</div>
            <div class="stat-label">Intersection (Shared)</div>
        </div>
        <div class="stat-card">
            <div class="stat-value">{g1_only}</div>
            <div class="stat-label">{g1_name} Only</div>
        </div>
        <div class="stat-card">
            <div class="stat-value">{g2_only}</div>
            <div class="stat-label">{g2_name} Only</div>
        </div>
        <div class="stat-card">
            <div class="stat-value">{conflicts}</div>
            <div class="stat-label">Contradictions</div>
        </div>
    </div>
    
    <div class="venn-container">
        <svg width="500" height="350" viewBox="0 0 500 350">
            <!-- G1 Circle (left) -->
            <ellipse cx="180" cy="175" rx="140" ry="120" fill="rgba(59, 130, 246, 0.3)" stroke="#3b82f6" stroke-width="3"/>
            <!-- G2 Circle (right) -->
            <ellipse cx="320" cy="175" rx="140" ry="120" fill="rgba(16, 185, 129, 0.3)" stroke="#10b981" stroke-width="3"/>
            
            <!-- Labels -->
            <text x="100" y="175" fill="#3b82f6" font-size="24" font-weight="bold">{g1_only}</text>
            <text x="100" y="200" fill="#94a3b8" font-size="12">{g1_name} only</text>
            
            <text x="240" y="160" fill="#10b981" font-size="28" font-weight="bold" text-anchor="middle">{both}</text>
            <text x="240" y="185" fill="#94a3b8" font-size="12" text-anchor="middle">Shared</text>
            
            <text x="380" y="175" fill="#10b981" font-size="24" font-weight="bold">{g2_only}</text>
            <text x="380" y="200" fill="#94a3b8" font-size="12">{g2_name} only</text>
            
            <!-- Graph labels -->
            <text x="100" y="50" fill="#3b82f6" font-size="16" font-weight="bold">📦 {g1_name}</text>
            <text x="350" y="50" fill="#10b981" font-size="16" font-weight="bold">⬤ {g2_name}</text>
            
            <!-- Conflict indicator -->
            <text x="250" y="320" fill="#ef4444" font-size="14" text-anchor="middle">⚠️ {conflicts} Contradictions</text>
        </svg>
    </div>
    
    <div class="legend">
        <div class="legend-item">
            <div class="legend-shape legend-ellipse"></div>
            <span>Matched rules (Ellipse with both IDs)</span>
        </div>
        <div class="legend-item">
            <div class="legend-shape legend-rect"></div>
            <span>{g1_name} only (Rectangle)</span>
        </div>
        <div class="legend-item">
            <div class="legend-shape legend-circle"></div>
            <span>{g2_name} only (Circle)</span>
        </div>
    </div>
    
    <h2 style="margin: 2rem 0 1rem; color: white; text-shadow: 0 2px 4px rgba(0,0,0,0.3);">Explore Results</h2>
    
    <div class="nav-grid">
        <a href="union.html" class="nav-card">
            <h3>∪ Union</h3>
            <p>All {union['stats']['total_rules']} unique rules from both graphs</p>
        </a>
        <a href="intersection.html" class="nav-card">
            <h3>∩ Intersection</h3>
            <p>{both} rules present in both graphs</p>
        </a>
        <a href="g1_minus_g2.html" class="nav-card">
            <h3>{g1_name} - {g2_name}</h3>
            <p>{g1_only} rules exclusive to {g1_name}</p>
        </a>
        <a href="g2_minus_g1.html" class="nav-card">
            <h3>{g2_name} - {g1_name}</h3>
            <p>{g2_only} rules exclusive to {g2_name}</p>
        </a>
        <a href="contradictions.html" class="nav-card" style="border-color: #ef4444;">
            <h3>⚠️ Contradictions</h3>
            <p>{conflicts} conflicting rule pairs</p>
        </a>
    </div>
</body>
</html>'''
    
    def run(self) -> None:
        """Generate all visualizations for each set operation."""
        print(f"""
╔══════════════════════════════════════════════════════════════════════╗
║   Set Operations Visualization Generator (Agent 10)                   ║
║   Creating HTML for: ∩, G1-G2, G2-G1, ∪, Contradictions             ║
╚══════════════════════════════════════════════════════════════════════╝
""")
        
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        # Load all 5 operation results
        all_results = {}
        operations = ['intersection', 'g1_minus_g2', 'g2_minus_g1', 'union', 'contradictions']
        
        for op in operations:
            print(f"   Loading {op}...")
            try:
                all_results[op] = self.load_operation_result(op)
            except FileNotFoundError:
                print(f"   ⚠️  {op}.json not found, skipping...")
                continue
        
        # Get graph names for reporting
        g1_name = all_results.get('union', all_results.get('intersection', {})).get('metadata', {}).get('g1_name', 'G1')
        g2_name = all_results.get('union', all_results.get('intersection', {})).get('metadata', {}).get('g2_name', 'G2')
        
        # Generate visualizations
        print(f"\n📊 Generating visualizations for {g1_name} vs {g2_name}...")
        
        # 1. Intersection HTML
        if 'intersection' in all_results:
            print("   1️⃣  intersection.html (G1 ∩ G2 - shared rules)")
            html = self.generate_intersection_html(all_results['intersection'])
            (self.output_dir / "intersection.html").write_text(html)
        
        # 2. G1-G2 HTML (Left Difference)
        if 'g1_minus_g2' in all_results:
            print(f"   2️⃣  g1_minus_g2.html ({g1_name} - {g2_name})")
            html = self.generate_difference_html(all_results['g1_minus_g2'], is_g1=True)
            (self.output_dir / "g1_minus_g2.html").write_text(html)
        
        # 3. G2-G1 HTML (Right Difference)
        if 'g2_minus_g1' in all_results:
            print(f"   3️⃣  g2_minus_g1.html ({g2_name} - {g1_name})")
            html = self.generate_difference_html(all_results['g2_minus_g1'], is_g1=False)
            (self.output_dir / "g2_minus_g1.html").write_text(html)
        
        # 4. Union HTML (main dashboard with filters)
        if 'union' in all_results:
            print("   4️⃣  union.html (G1 ∪ G2 - all unique rules)")
            html = self.generate_union_html(all_results['union'])
            (self.output_dir / "union.html").write_text(html)
        
        # 5. Contradictions HTML
        if 'contradictions' in all_results:
            print("   5️⃣  contradictions.html (conflicting pairs)")
            html = self.generate_contradictions_html(all_results['contradictions'])
            (self.output_dir / "contradictions.html").write_text(html)
        
        # 6. Index page (summary dashboard)
        print("   6️⃣  index.html (summary dashboard)")
        html = self.generate_summary_html(all_results)
        (self.output_dir / "index.html").write_text(html)
        
        # Print summary
        print(f"""
╔══════════════════════════════════════════════════════════════════════╗
║              VISUALIZATIONS COMPLETE                                  ║
╠══════════════════════════════════════════════════════════════════════╣
║                                                                       ║
║   📄 Generated HTML Reports:                                          ║
║      ├─ index.html          (Summary Dashboard)                      ║
║      ├─ intersection.html   (G1 ∩ G2)                                ║
║      ├─ g1_minus_g2.html    ({g1_name} - {g2_name})                          ║
║      ├─ g2_minus_g1.html    ({g2_name} - {g1_name})                          ║
║      ├─ union.html          (G1 ∪ G2)                                ║
║      └─ contradictions.html (Conflicts)                              ║
║                                                                       ║
╚══════════════════════════════════════════════════════════════════════╝

✅ Saved to: {self.output_dir}

🌐 Open in browser: file://{(self.output_dir / 'index.html').absolute()}
""")


def main():
    """CLI entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(description='Generate set operations visualizations')
    parser.add_argument('--provider', type=str, default='openai', choices=['openai'])
    
    args = parser.parse_args()
    
    visualizer = SetOperationsVisualizer(provider=args.provider)
    visualizer.run()


if __name__ == "__main__":
    main()
