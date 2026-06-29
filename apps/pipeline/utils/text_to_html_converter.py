"""
Text to HTML Converter for Optimization Reports

This utility converts plain text optimization reports into beautiful, styled HTML pages
without adding or removing any content from the original reports.
"""

import json
import re
from pathlib import Path
from datetime import datetime


def safe_json_for_html(obj) -> str:
    """Serialize ``obj`` to JSON safe for embedding inside an inline <script> tag.

    A naive ``json.dumps`` can emit a literal ``</script>`` (or ``<!--``) sequence
    when a string value contains it, which prematurely terminates the surrounding
    <script> block and breaks the generated HTML. Escaping ``<`` and ``/`` with a
    backslash keeps the output valid JSON/JS while preventing the parser from ever
    seeing a closing tag.
    """
    # Escaping every '<' as the JSON unicode escape < guarantees no '</script>'
    # (or '<!--') token can appear, while still parsing back to the identical value.
    return json.dumps(obj).replace("<", "\\u003c")


def convert_text_to_html(text_content: str, title: str = "Optimization Report", source_document: str = None) -> str:
    """
    Convert plain text optimization report to styled HTML.
    
    Args:
        text_content: The plain text content to convert
        title: The title for the HTML page
        source_document: Optional source document name (extracted from content if not provided)
        
    Returns:
        Complete HTML document as string
    """
    
    # Extract source document from content if not provided
    if source_document is None:
        source_match = re.search(r'^Source Document:\s*(.+)$', text_content, re.MULTILINE)
        if source_match:
            source_document = source_match.group(1).strip()
    
    # Update title to include source document
    if source_document:
        title = f"{source_document} - {title}"
    
    # Escape HTML special characters in content
    def escape_html(text):
        return (text
                .replace('&', '&amp;')
                .replace('<', '&lt;')
                .replace('>', '&gt;')
                .replace('"', '&quot;')
                .replace("'", '&#39;'))
    
    # Normalize whitespace in text (remove extra spaces, normalize line breaks)
    def normalize_text(text):
        # Replace multiple spaces with single space
        import re
        text = re.sub(r' +', ' ', text)
        # Remove leading/trailing whitespace from each line
        text = '\n'.join(line.strip() for line in text.split('\n'))
        
        # Break long paragraphs into sentences for better readability
        # Add line break after sentence-ending punctuation followed by space and capital letter
        text = re.sub(r'(\. )([A-Z])', r'.\n\n\2', text)
        # Also handle cases with multiple sentences
        text = re.sub(r'(\; )([A-Z])', r';\n\n\2', text)
        
        return text.strip()
    
    # Parse the text into sections
    lines = text_content.split('\n')
    html_body = []
    current_section = None
    in_duplicate_group = False
    
    for line in lines:
        # Main title (equals signs above and below)
        if '=' * 40 in line:
            continue
            
        # Section headers (with dashes)
        if '-' * 40 in line:
            if current_section:
                html_body.append('</div>')
            continue
            
        # Check for section titles
        if line.strip() and line.strip().isupper() and not line.startswith(' '):
            if current_section:
                html_body.append('</div>')
            current_section = line.strip()
            section_id = current_section.lower().replace(' ', '-').replace('_', '-')
            html_body.append(f'<div class="section" id="{section_id}">')
            html_body.append(f'<h2 class="section-title">{escape_html(current_section)}</h2>')
            continue
        
        # Main document title
        if 'COMPLIANCE KNOWLEDGE GRAPH OPTIMIZATION REPORT' in line:
            main_title = line.strip()
            if source_document:
                main_title = f"{source_document} - {main_title}"
            html_body.append(f'<h1 class="main-title">{escape_html(main_title)}</h1>')
            continue
        
        # Source Document metadata
        if line.startswith('Source Document:'):
            key, value = line.split(':', 1)
            html_body.append(f'<div class="metadata source-document"><span class="key">{escape_html(key)}:</span><span class="value highlight">{escape_html(value.strip())}</span></div>')
            continue
        
        # Metadata (Generated, Model, etc.)
        if line.startswith('Generated:') or line.startswith('Model:'):
            key, value = line.split(':', 1)
            html_body.append(f'<div class="metadata"><span class="key">{escape_html(key)}:</span><span class="value">{escape_html(value.strip())}</span></div>')
            continue
        
        # Optimization Summary section
        if 'Optimization Summary:' in line:
            html_body.append('<div class="summary-box">')
            html_body.append('<h3>Optimization Summary</h3>')
            continue
        
        # Summary items with indentation
        if line.strip() and ':' in line and line.startswith('  ') and not line.strip().startswith('-'):
            parts = line.strip().split(':', 1)
            if len(parts) == 2:
                key, value = parts
                html_body.append(f'<div class="summary-item"><span class="label">{escape_html(key)}:</span><span class="stat">{escape_html(value.strip())}</span></div>')
                continue
        
        # Close summary box when we hit the first section divider
        if current_section and 'summary-box' in ''.join(html_body[-5:]):
            if line.strip() == '':
                html_body.append('</div>')
        
        # Subsection headers (Strategy, Rationale, Results, etc.)
        if line.strip() and line.strip().endswith(':') and not line.startswith('  '):
            label = line.strip()[:-1]
            html_body.append(f'<h3 class="subsection-title">{escape_html(label)}</h3>')
            continue
        
        # Duplicate Group headers
        if line.strip().startswith('Duplicate Group'):
            if in_duplicate_group:
                html_body.append('</div>')
            html_body.append('<div class="duplicate-group">')
            html_body.append(f'<h4 class="group-title">{escape_html(line.strip())}</h4>')
            in_duplicate_group = True
            continue
        
        # Key-value pairs within duplicate groups
        if in_duplicate_group and line.startswith('  ') and ':' in line and not line.strip().startswith('-'):
            parts = line.strip().split(':', 1)
            if len(parts) == 2:
                key, value = parts
                # Special handling for multi-line values like Rationale and Enhanced Description
                if key.strip() in ['Rationale', 'Enhanced Description']:
                    # Normalize the text to remove extra whitespace
                    normalized_value = normalize_text(value)
                    html_body.append(f'<div class="detail-item"><span class="detail-label">{escape_html(key)}:</span></div>')
                    html_body.append(f'<div class="detail-content">{escape_html(normalized_value)}</div>')
                else:
                    html_body.append(f'<div class="detail-item"><span class="detail-label">{escape_html(key)}:</span> <span class="detail-value">{escape_html(value.strip())}</span></div>')
                continue
        
        # Bullet points or list items
        if line.strip().startswith('-'):
            html_body.append(f'<div class="list-item">{escape_html(line.strip())}</div>')
            continue
        
        # Regular paragraphs
        if line.strip():
            html_body.append(f'<p class="content">{escape_html(line.strip())}</p>')
        else:
            # Empty lines for spacing
            html_body.append('<br>')
    
    # Close any open sections
    if current_section:
        html_body.append('</div>')
    if in_duplicate_group:
        html_body.append('</div>')
    
    # Generate complete HTML document
    html_template = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{escape_html(title)}</title>
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
            padding: 2rem;
            min-height: 100vh;
        }}
        
        .container {{
            max-width: 1200px;
            margin: 0 auto;
            background: white;
            border-radius: 16px;
            padding: 3rem;
            box-shadow: 0 20px 60px rgba(0, 0, 0, 0.3);
        }}
        
        .main-title {{
            font-size: 2.5em;
            font-weight: 700;
            text-align: center;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            margin-bottom: 2rem;
            padding-bottom: 1rem;
            border-bottom: 3px solid #e2e8f0;
        }}
        
        .metadata {{
            display: flex;
            justify-content: center;
            gap: 2rem;
            margin-bottom: 1rem;
            padding: 0.75rem;
            background: #f8fafc;
            border-radius: 8px;
        }}
        
        .metadata .key {{
            font-weight: 600;
            color: #475569;
        }}
        
        .metadata .value {{
            color: #64748b;
        }}
        
        .summary-box {{
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 2rem;
            border-radius: 12px;
            margin: 2rem 0;
        }}
        
        .summary-box h3 {{
            font-size: 1.5em;
            margin-bottom: 1rem;
            opacity: 0.95;
        }}
        
        .summary-item {{
            display: flex;
            justify-content: space-between;
            padding: 0.5rem 0;
            border-bottom: 1px solid rgba(255, 255, 255, 0.2);
        }}
        
        .summary-item:last-child {{
            border-bottom: none;
        }}
        
        .summary-item .label {{
            font-weight: 500;
            opacity: 0.9;
        }}
        
        .summary-item .stat {{
            font-weight: 700;
            font-size: 1.1em;
        }}
        
        .section {{
            margin: 3rem 0;
        }}
        
        .section-title {{
            font-size: 1.8em;
            font-weight: 600;
            color: #1e293b;
            margin-bottom: 1.5rem;
            padding-bottom: 0.5rem;
            border-bottom: 2px solid #e2e8f0;
        }}
        
        .subsection-title {{
            font-size: 1.3em;
            font-weight: 600;
            color: #475569;
            margin-top: 1.5rem;
            margin-bottom: 0.75rem;
        }}
        
        .duplicate-group {{
            background: #f8fafc;
            border-left: 4px solid #667eea;
            padding: 1.5rem;
            margin: 1.5rem 0;
            border-radius: 8px;
        }}
        
        .group-title {{
            font-size: 1.2em;
            font-weight: 600;
            color: #667eea;
            margin-bottom: 1rem;
        }}
        
        .detail-item {{
            margin: 0.75rem 0;
        }}
        
        .detail-label {{
            font-weight: 600;
            color: #475569;
        }}
        
        .detail-value {{
            color: #64748b;
        }}
        
        .detail-content {{
            margin-top: 0.5rem;
            margin-left: 1rem;
            padding: 1rem;
            background: white;
            border-radius: 6px;
            color: #475569;
            line-height: 1.8;
            font-weight: 400;
            white-space: pre-wrap;
            word-wrap: break-word;
        }}
        
        .list-item {{
            padding: 0.5rem 0 0.5rem 2rem;
            color: #475569;
        }}
        
        .content {{
            margin: 0.75rem 0;
            color: #475569;
            line-height: 1.7;
        }}
        
        .back-link {{
            display: inline-block;
            margin-bottom: 2rem;
            padding: 0.75rem 1.5rem;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            text-decoration: none;
            border-radius: 8px;
            font-weight: 500;
            transition: transform 0.2s, box-shadow 0.2s;
        }}
        
        .back-link:hover {{
            transform: translateY(-2px);
            box-shadow: 0 5px 15px rgba(102, 126, 234, 0.4);
        }}
        
        @media (max-width: 768px) {{
            body {{
                padding: 1rem;
            }}
            
            .container {{
                padding: 1.5rem;
            }}
            
            .main-title {{
                font-size: 1.8em;
            }}
            
            .metadata {{
                flex-direction: column;
                gap: 0.5rem;
            }}
        }}
    </style>
</head>
<body>
    <div class="container">
        {''.join(html_body)}
    </div>
</body>
</html>"""
    
    return html_template


def convert_report_file(input_path: Path, output_path: Path = None) -> Path:
    """
    Convert a text optimization report file to HTML.
    
    Args:
        input_path: Path to the input text file
        output_path: Path for the output HTML file (defaults to same location with .html extension)
        
    Returns:
        Path to the generated HTML file
    """
    input_path = Path(input_path)
    
    if not input_path.exists():
        raise FileNotFoundError(f"Input file not found: {input_path}")
    
    # Read the text content
    with open(input_path, 'r', encoding='utf-8') as f:
        text_content = f.read()
    
    # Determine output path
    if output_path is None:
        output_path = input_path.with_suffix('.html')
    else:
        output_path = Path(output_path)
    
    # Extract source document name from path (e.g., pipeline-output/FM/agent-5-optimized/)
    # The source document name is the folder directly under pipeline-output/.
    source_document = None
    path_parts = input_path.parts
    for i, part in enumerate(path_parts):
        if part == 'pipeline-output' and i + 1 < len(path_parts):
            next_part = path_parts[i + 1]
            if not next_part.startswith('agent-') and not next_part.startswith('_'):
                source_document = next_part
            break
    
    # Generate title from filename
    title = input_path.stem.replace('_', ' ').replace('-', ' ').title()
    
    # Convert to HTML (source_document will be extracted from content if not found in path)
    html_content = convert_text_to_html(text_content, title, source_document=source_document)
    
    # Write HTML file
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(html_content)
    
    print(f"✓ Converted: {input_path.name} → {output_path.name}")
    return output_path


def convert_all_optimization_reports(pipeline_output_dir: Path) -> list[Path]:
    """
    Convert all optimization report text files to HTML.
    
    Args:
        pipeline_output_dir: Path to the pipeline-output directory
        
    Returns:
        List of paths to generated HTML files
    """
    pipeline_output_dir = Path(pipeline_output_dir)
    html_files = []
    
    # Find all optimization report text files
    patterns = [
        '**/agent-5-optimized/*optimization_report.txt',
        '**/agent-5-optimized/*optimization-report.txt',
    ]
    
    text_files = []
    for pattern in patterns:
        text_files.extend(pipeline_output_dir.glob(pattern))
    
    if not text_files:
        print("No optimization report text files found.")
        return html_files
    
    print(f"\nFound {len(text_files)} optimization report(s) to convert:\n")
    
    # Convert each file
    for text_file in text_files:
        try:
            html_file = convert_report_file(text_file)
            html_files.append(html_file)
        except Exception as e:
            print(f"✗ Error converting {text_file.name}: {e}")
    
    print(f"\n✓ Successfully converted {len(html_files)} report(s)")
    return html_files


if __name__ == "__main__":
    # When run directly, convert all reports in the pipeline-output directory
    import sys
    
    # Get the project root directory (assuming this script is in utils/)
    script_dir = Path(__file__).parent
    project_root = script_dir.parent
    pipeline_output_dir = project_root / "pipeline-output"
    
    if pipeline_output_dir.exists():
        convert_all_optimization_reports(pipeline_output_dir)
    else:
        print(f"Error: Pipeline output directory not found: {pipeline_output_dir}")
        sys.exit(1)
