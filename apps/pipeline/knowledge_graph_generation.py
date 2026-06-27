#!/usr/bin/env python3
"""
Agentic Knowledge Extraction Flow

Orchestrates the complete pipeline from raw PDF documents to structured knowledge graph:
1. Knowledge Organization: Split and organize documents by TOC/AI reasoning
2. Entity-Relationship Extraction: Extract domain model using meta-agent
3. Business Rules Extraction: Extract detailed rules with GPT-5 reasoning
3.5. Rule Validation: Validate extracted rules for quality and consistency
4. Rules+Entities Merger: Merge business rules with entity definitions
5. Knowledge Graph Optimization: Deduplicate rules and analyze dependencies
6. Visualization and Reports: Generate interactive HTML visualization

Author: Reza Rahimi
Date: December 8, 2025
"""

import os
import sys
import json
import shutil
import webbrowser
from pathlib import Path
from datetime import datetime
from typing import Dict, List
import subprocess

# Add project root to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from utils.config import get_config, reload_config


def sync_knowledge_graph_to_fama_code(provider: str = "openai", source_file_name: str = None):
    """
    Sync optimized knowledge graph files to fama-to-code catalog.
    
    Copies all files from:
      policy-to-knowledge/pipeline-output/{source_file_name}/agent-5-optimized
    To:
      fama-to-code/data/catalogs/knowledge-graph/{source_file_name}/
    
    Args:
        provider: The provider used (openai)
        source_file_name: The name of the source file (without extension)
    """
    print("\n" + "=" * 80)
    print("📦 SYNCING KNOWLEDGE GRAPH TO FAMA-TO-CODE")
    print("=" * 80)
    
    try:
        # Define source and destination paths
        project_root = Path(__file__).parent.parent
        if source_file_name:
            source_dir = Path(__file__).parent / "pipeline-output" / source_file_name / "agent-5-optimized"
            dest_dir = project_root / "fama-to-code" / "data" / "catalogs" / "knowledge-graph" / source_file_name
        else:
            source_dir = Path(__file__).parent / "pipeline-output" / "agent-5-optimized"
            dest_dir = project_root / "fama-to-code" / "data" / "catalogs" / "knowledge-graph"
        
        # Validate source directory exists
        if not source_dir.exists():
            print(f"⚠️  Source directory not found: {source_dir}")
            print("   Skipping knowledge graph sync")
            return False
        
        # Create destination directory
        dest_dir.mkdir(parents=True, exist_ok=True)
        print(f"\n📂 Source: {source_dir}")
        print(f"📂 Destination: {dest_dir}")
        
        # Get list of files to copy
        files_to_copy = list(source_dir.glob('*'))
        if not files_to_copy:
            print("\n⚠️  No files found in source directory")
            return False
        
        print(f"\n🔄 Copying {len(files_to_copy)} files...")
        
        # Copy each file
        copied_count = 0
        for file_path in files_to_copy:
            if file_path.is_file():
                dest_file = dest_dir / file_path.name
                shutil.copy2(file_path, dest_file)
                print(f"   ✓ {file_path.name}")
                copied_count += 1
        
        print(f"\n✅ Successfully copied {copied_count} files to fama-to-code catalog")
        print("=" * 80 + "\n")
        return True
        
    except Exception as e:
        print(f"\n❌ Error syncing knowledge graph: {e}")
        import traceback
        traceback.print_exc()
        print("=" * 80 + "\n")
        return False


class KnowledgeExtractionPipeline:
    """Orchestrates the complete knowledge extraction pipeline."""
    
    def __init__(
        self,
        source_dir: str = None,
        source_file: str = None,
        source_files: List[str] = None,  # NEW: List of files for batch processing
        batch_name: str = None,  # NEW: Name for batch output folder
        organized_dir: str = None,
        output_dir: str = None,
        target_rules: int = None,
        provider: str = None,
        skip_optimize: bool = False,
        max_workers: int = None,
        domain: str = None
    ):
        """
        Initialize the agentic flow.
        
        Args:
            source_dir: Directory containing source PDF files
            source_file: Single source file to process (if specified, only this file is processed)
            source_files: List of source files to process together as a batch
            batch_name: Name for the batch output folder (used when processing multiple files together)
            organized_dir: Directory for organized/chunked documents
            output_dir: Directory for final knowledge graph outputs
            target_rules: Target number of business rules to extract
            provider: AI provider to use ('openai')
            max_workers: Maximum number of parallel workers for LLM calls (default: 20)
            domain: Compliance domain to use for prompts (e.g., 'mortgage', 'aml')
        """
        self.max_workers = max_workers
        self.domain = domain
        
        # Determine processing mode: batch, single file, or directory
        self.source_file = Path(source_file) if source_file else None
        self.source_files = [Path(f) for f in source_files] if source_files else None
        self.source_file_name = None
        self.batch_name = batch_name
        
        # Batch mode: multiple files processed together
        if self.source_files and batch_name:
            # Use batch name for output organization
            self.config = get_config(provider=provider, batch_name=batch_name, domain=domain)
            # Source directory is the common parent of all files (or first file's parent)
            self.source_dir = self.source_files[0].parent if self.source_files else None
        # Single file mode
        elif self.source_file:
            self.source_file_name = self.source_file.stem  # filename without extension
            # Initialize config with source file name for per-file output paths
            self.config = get_config(provider=provider, source_file_name=self.source_file_name, domain=domain)
            self.source_dir = self.source_file.parent
        # Directory mode
        else:
            self.config = get_config(provider=provider, domain=domain)
            self.source_dir = Path(source_dir) if source_dir else self.config.get_source_dir()
        
        self.organized_dir = Path(organized_dir) if organized_dir else self.config.get_organized_dir()
        self.output_dir = Path(output_dir) if output_dir else self.config.get_output_dir()
        self.target_rules = target_rules if target_rules is not None else self.config.get_target_rules()
        
        # Detect model provider
        self.model_provider = self.config.get_model_provider()
        self.skip_optimize = skip_optimize
        
        # Flow state tracking
        self.flow_state = {
            "started_at": datetime.now().isoformat(),
            "steps_completed": [],
            "steps_failed": [],
            "current_step": None,
            "source_file": str(self.source_file) if self.source_file else None,
            "source_files": [str(f) for f in self.source_files] if self.source_files else None,
            "source_file_name": self.source_file_name,
            "batch_name": self.batch_name
        }
        
        print("=" * 80)
        print("🤖 AGENTIC KNOWLEDGE EXTRACTION FLOW")
        print("=" * 80)
        print(f"🤖 Model Provider: {self.model_provider.upper()}")
        print(f"🏷️  Domain: {self.config.get_domain().upper()}")
        print(f"📝 Reasoning Model: {self.config.get_reasoning_model()}")
        print(f"🧠 Reasoning Effort: {self.config.get_reasoning_effort()}")
        if self.batch_name and self.source_files:
            print(f"📦 Batch Mode: {self.batch_name}")
            print(f"📄 Source Files ({len(self.source_files)}):")
            for f in self.source_files:
                print(f"   • {f.name}")
        elif self.source_file:
            print(f"📄 Source File: {self.source_file}")
        else:
            print(f"📁 Source Directory: {self.source_dir}")
        print(f"📂 Organized Directory: {self.organized_dir}")
        print(f"💾 Output Directory: {self.output_dir}")
        print(f"🎯 Target Business Rules: {self.target_rules}")
        if self.max_workers:
            print(f"👷 Max Workers: {self.max_workers}")
        print("=" * 80)
        print()
    
    def _print_progress_summary(self, completed_steps: list, current_step: str = None, total_steps: int = 7):
        """Print a quick progress summary showing completed and remaining steps."""
        all_steps = [
            ("1", "Document Organizer"),
            ("2", "Entity Extractor"),
            ("3", "Rules Extractor"),
            ("3.5", "Rule Validator"),
            ("4", "Rules+Entities Merger"),
            ("5", "KG Optimizer"),
            ("6", "Visualizer"),
        ]
        
        print(f"\n{'─' * 80}")
        print(f"📊 PIPELINE PROGRESS: {len(completed_steps)}/{total_steps} steps completed")
        print(f"{'─' * 80}")
        for step_num, step_name in all_steps:
            if step_num in completed_steps:
                print(f"   ✅ Step {step_num}: {step_name}")
            elif step_num == current_step:
                print(f"   🔄 Step {step_num}: {step_name} (IN PROGRESS)")
            else:
                print(f"   ⬚  Step {step_num}: {step_name}")
        print(f"{'─' * 80}\n")
        sys.stdout.flush()
    
    def _run_agent(self, agent_name: str, command: List[str], description: str, step_number: str = None) -> bool:
        """
        Run an agent and track its execution with real-time output streaming.
        
        Args:
            agent_name: Name of the agent for tracking
            command: Command to execute
            description: Human-readable description
            step_number: Optional step number for display (e.g., "1", "3.5")
            
        Returns:
            True if successful, False otherwise
        """
        self.flow_state["current_step"] = agent_name
        
        # Get name for display (batch_name takes precedence)
        source_name = self.batch_name or self.source_file_name or "all documents"
        
        # Extract script name from command
        script_name = Path(command[1]).name if len(command) > 1 else "unknown"
        step_display = f"Step {step_number}" if step_number else ""
        
        start_time = datetime.now()
        print(f"\n{'=' * 80}")
        print(f"🚀 EXECUTING [{source_name}]: {agent_name}")
        print(f"📋 {description}")
        print(f"{'=' * 80}")
        print(f"📜 Script:     {script_name}")
        print(f"⏰ Started at: {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"🔧 Command: {' '.join(command)}")
        print(f"{'=' * 80}")
        print(f"📡 Streaming real-time output below...")
        print(f"{'=' * 80}\n")
        sys.stdout.flush()
        
        try:
            # Set environment variables for subprocess
            env = os.environ.copy()
            if self.model_provider:
                env['KG_PROVIDER'] = self.model_provider
            # Pass max_workers to subprocess so agents use the correct parallelism
            if self.max_workers:
                env['MAX_WORKERS'] = str(self.max_workers)
            # Pass batch name to subprocess so it uses the correct batch paths
            batch_name = self.config.get_batch_name()
            if batch_name:
                env['KG_BATCH_NAME'] = batch_name
            # Pass source file name to subprocess so it uses the correct per-file paths
            source_file_name = self.config.get_source_file_name()
            if source_file_name:
                env['KG_SOURCE_FILE_NAME'] = source_file_name
            # Pass domain to subprocesses
            domain = self.config.get_domain()
            if domain:
                env['KG_DOMAIN'] = domain
            
            # Use Popen for real-time output streaming
            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                env=env,
                universal_newlines=True,
                bufsize=1
            )
            
            # Stream output in real-time
            output_lines = []
            for line in process.stdout:
                print(line, end='', flush=True)
                output_lines.append(line)
            
            # Wait for process to complete
            return_code = process.wait()
            
            if return_code != 0:
                raise subprocess.CalledProcessError(return_code, command)
            
            # Mark as completed
            completion_time = datetime.now()
            duration = completion_time - start_time
            
            self.flow_state["steps_completed"].append({
                "agent": agent_name,
                "timestamp": completion_time.isoformat(),
                "description": description,
                "duration_seconds": duration.total_seconds()
            })
            
            print(f"\n{'=' * 80}")
            print(f"✅ [{source_name}] {agent_name} COMPLETED SUCCESSFULLY")
            print(f"⏰ Started:  {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
            print(f"⏰ Finished: {completion_time.strftime('%Y-%m-%d %H:%M:%S')}")
            print(f"⏱️  Duration: {duration}")
            print(f"{'=' * 80}\n")
            return True
            
        except subprocess.CalledProcessError as e:
            failure_time = datetime.now()
            duration = failure_time - start_time
            
            print(f"\n{'=' * 80}")
            print(f"❌ [{source_name}] {agent_name} FAILED")
            print(f"⚠️  Exit code: {e.returncode}")
            print(f"⏰ Started:  {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
            print(f"⏰ Failed:   {failure_time.strftime('%Y-%m-%d %H:%M:%S')}")
            print(f"⏱️  Duration: {duration}")
            print(f"{'=' * 80}\n")
            
            self.flow_state["steps_failed"].append({
                "agent": agent_name,
                "timestamp": failure_time.isoformat(),
                "error": str(e),
                "exit_code": e.returncode,
                "duration_seconds": duration.total_seconds()
            })
            return False
        except Exception as e:
            failure_time = datetime.now()
            duration = failure_time - start_time
            
            print(f"\n{'=' * 80}")
            print(f"❌ [{source_name}] {agent_name} FAILED WITH EXCEPTION")
            print(f"⚠️  Error: {str(e)}")
            print(f"⏰ Started:  {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
            print(f"⏰ Failed:   {failure_time.strftime('%Y-%m-%d %H:%M:%S')}")
            print(f"⏱️  Duration: {duration}")
            print(f"{'=' * 80}\n")
            
            self.flow_state["steps_failed"].append({
                "agent": agent_name,
                "timestamp": failure_time.isoformat(),
                "error": str(e),
                "duration_seconds": duration.total_seconds()
            })
            return False
    
    def step1_organize_knowledge(self) -> bool:
        """
        Step 1: Knowledge Organization Agent
        
        Processes PDFs from knowledge-files and creates organized chunks
        in knowledge-files-organized with hierarchical folder structure.
        Supports three modes:
        - Batch mode: Multiple files processed together (self.source_files)
        - Single file mode: Only the specified file is processed (self.source_file)
        - Directory mode: All files in source_dir are processed
        """
        print("\n" + "=" * 80)
        print("📌 STEP 1 PRE-CHECK: Document Organization")
        print("=" * 80)
        
        # Determine input path based on mode
        if self.source_files and self.batch_name:
            # Batch mode: process multiple files together
            print(f"📦 Batch Mode: {self.batch_name}")
            print(f"📄 Processing {len(self.source_files)} files together:")
            valid_files = []
            for f in self.source_files:
                if f.exists():
                    print(f"   ✅ {f.name}")
                    valid_files.append(f)
                else:
                    print(f"   ❌ {f.name} (not found)")
            
            if not valid_files:
                print(f"❌ No valid source files found")
                return False
            
            # Use the parent directory of the files as input
            input_path = str(self.source_files[0].parent)
        elif self.source_file:
            print(f"📄 Processing single file: {self.source_file}")
            if not self.source_file.exists():
                print(f"❌ Source file does not exist: {self.source_file}")
                return False
            print(f"✅ Source file exists: {self.source_file.name}")
            input_path = str(self.source_file)
        else:
            print(f"📁 Checking source directory: {self.source_dir}")
            if not self.source_dir.exists():
                print(f"❌ Source directory does not exist: {self.source_dir}")
                return False
            
            # Count supported files
            supported_extensions = set(get_config().get_supported_extensions())
            all_files = [f for f in self.source_dir.glob('*') 
                        if f.is_file() and f.suffix.lower() in supported_extensions]
            print(f"✅ Source directory exists with {len(all_files)} supported files")
            for f in all_files[:5]:  # Show first 5
                print(f"   📄 {f.name}")
            if len(all_files) > 5:
                print(f"   ... and {len(all_files) - 5} more")
            input_path = str(self.source_dir)
        
        print(f"\n📂 Output will be organized in: {self.organized_dir}")
        print(f"{'=' * 80}\n")
        
        script_dir = Path(__file__).parent / "agents"
        print(f"\n🤖 LAUNCHING AGENT: agent_1_document_organizer.py")
        agent_cmd = [
            sys.executable,
            str(script_dir / "agent_1_document_organizer.py"),
            input_path,
            str(self.organized_dir)
        ]
        # Pass specific file names when user selected individual files
        if self.source_files:
            agent_cmd.append("--files")
            agent_cmd.extend(f.name for f in self.source_files)
        result = self._run_agent(
            agent_name="Document Organizer",
            command=agent_cmd,
            description=f"Organizing and chunking documents from {input_path}",
            step_number="1"
        )
        
        if result:
            print("\n" + "=" * 80)
            print("✅ STEP 1 POST-CHECK: Document Organization")
            print("=" * 80)
            if self.organized_dir.exists():
                # Count organized files (agent creates .txt files)
                organized_files = list(self.organized_dir.rglob('*.txt'))
                metadata_files = list(self.organized_dir.rglob('_metadata.json'))
                processing_results = self.organized_dir / "_processing_results.json"
                
                print(f"✅ Created {len(organized_files)} organized document chunks (.txt files)")
                print(f"📊 Metadata files: {len(metadata_files)}")
                if processing_results.exists():
                    print(f"📄 Processing results: {processing_results.name}")
                    try:
                        with open(processing_results, 'r') as f:
                            proc_data = json.load(f)
                        stats = proc_data.get('chunk_size_stats', {})
                        if stats:
                            print(f"📐 Chunk Size Stats:")
                            print(f"   Word range: {stats.get('min_words', '?')}–{stats.get('max_words', '?')}")
                            print(f"   Average: {stats.get('avg_words', '?')} words | Median: {stats.get('median_words', '?')} words")
                            if stats.get('sub_chunks_created', 0) > 0:
                                print(f"   Sub-chunks created: {stats['sub_chunks_created']}")
                            if stats.get('merges_performed', 0) > 0:
                                print(f"   Merges performed: {stats['merges_performed']}")
                    except Exception:
                        pass
                print(f"📂 Output directory: {self.organized_dir}")
            else:
                print(f"⚠️  Warning: Output directory not found: {self.organized_dir}")
            print(f"{'=' * 80}\n")
        
        return result
    
    def step2_extract_entity_relationships(self) -> bool:
        """
        Step 2: Entity-Relationship Extraction Agent
        
        Uses meta-agent to extract domain model (entities and relationships)
        from organized knowledge files.
        """
        print("\n" + "=" * 80)
        print("📌 STEP 2 PRE-CHECK: Entity-Relationship Extraction")
        print("=" * 80)
        print(f"📂 Checking input from Step 1: {self.organized_dir}")
        if not self.organized_dir.exists():
            print(f"❌ Organized directory does not exist: {self.organized_dir}")
            print("   Please run Step 1 first!")
            return False
        
        # Agent 1 creates .txt files, not .md files
        organized_files = list(self.organized_dir.rglob('*.txt'))
        print(f"✅ Found {len(organized_files)} organized documents (.txt files) to process")
        if len(organized_files) == 0:
            print(f"⚠️  Warning: No .txt files found in {self.organized_dir}")
        print(f"📤 Output will be saved to: {self.config.get_entity_relationship_dir()}")
        print(f"{'=' * 80}\n")
        
        script_dir = Path(__file__).parent / "agents"
        print(f"\n🤖 LAUNCHING AGENT: agent_2_entity_extractor.py")
        result = self._run_agent(
            agent_name="Entity-Relationship Extractor",
            command=[
                sys.executable,
                str(script_dir / "agent_2_entity_extractor.py")
            ],
            description="Extracting entity-relationship definitions using meta-agent",
            step_number="2"
        )
        
        if result:
            print("\n" + "=" * 80)
            print("✅ STEP 2 POST-CHECK: Entity-Relationship Extraction")
            print("=" * 80)
            entity_file = self.config.get_entity_relationship_dir() / "entity_types_and_relationships.json"
            prompt_history = self.config.get_entity_relationship_dir() / "prompt_optimization_history.json"
            
            if entity_file.exists():
                with open(entity_file, 'r') as f:
                    data = json.load(f)
                    entity_count = len(data.get('entity_types', {}))
                    rel_count = len(data.get('relationships', []))
                    print(f"✅ Extracted {entity_count} entities and {rel_count} relationships")
                    print(f"📄 Entity definitions: {entity_file.name}")
                    if prompt_history.exists():
                        print(f"📄 Prompt history: {prompt_history.name}")
                    print(f"📂 Output directory: {self.config.get_entity_relationship_dir()}")
            else:
                print(f"⚠️  Warning: Entity file not found: {entity_file}")
            print(f"{'=' * 80}\n")
        
        return result
    
    def step3_extract_business_rules(self) -> bool:
        """
        Step 3: Enhanced Business Rules Extraction
        
        Uses entity definitions + GPT-5 reasoning to extract detailed business rules
        with specific numbers, conditions, and document section references.
        """
        print("\n" + "=" * 80)
        print("📌 STEP 3 PRE-CHECK: Business Rules Extraction")
        print("=" * 80)
        
        # Check Step 1 outputs
        print(f"📂 Checking documents from Step 1: {self.organized_dir}")
        if not self.organized_dir.exists():
            print(f"❌ Organized directory not found. Run Step 1 first!")
            return False
        organized_files = list(self.organized_dir.rglob('*.txt'))
        print(f"✅ Found {len(organized_files)} document chunks (.txt files)")
        
        # Check Step 2 outputs
        print(f"\n📂 Checking entities from Step 2: {self.config.get_entity_relationship_dir()}")
        entity_file = self.config.get_entity_relationship_dir() / "entity_types_and_relationships.json"
        if not entity_file.exists():
            print(f"❌ Entity file not found. Run Step 2 first!")
            return False
        with open(entity_file, 'r') as f:
            data = json.load(f)
            entity_count = len(data.get('entity_types', {}))
            print(f"✅ Found {entity_count} entities to process")
        
        print(f"\n🎯 Target: Extract {self.target_rules} business rules")
        print(f"📤 Output will be saved to: {self.config.get_rules_extracted_dir()}")
        print(f"{'=' * 80}\n")
        
        script_dir = Path(__file__).parent / "agents"
        print(f"\n🤖 LAUNCHING AGENT: agent_3_rules_extractor.py")
        result = self._run_agent(
            agent_name="Business Rules Extractor",
            command=[
                sys.executable,
                str(script_dir / "agent_3_rules_extractor.py")
            ],
            description=f"Extracting {self.target_rules} detailed business rules with {self.config.get_reasoning_model()} reasoning",
            step_number="3"
        )
        
        if result:
            print("\n" + "=" * 80)
            print("✅ STEP 3 POST-CHECK: Business Rules Extraction")
            print("=" * 80)
            rules_file = self.config.get_rules_extracted_dir() / "compliance_rules_with_entities.json"
            csv_file = self.config.get_rules_extracted_dir() / "compliance_rules_with_entities_rules.csv"
            
            if rules_file.exists():
                with open(rules_file, 'r') as f:
                    rules_data = json.load(f)
                    total_rules = sum(len(entity_data.get('business_rules', [])) 
                                    for entity_data in rules_data.get('entity_types', {}).values())
                    num_entities = len([k for k, v in rules_data.get('entity_types', {}).items() 
                                      if len(v.get('business_rules', [])) > 0])
                    print(f"✅ Extracted {total_rules} business rules across {num_entities} entities/relationships")
                    print(f"📄 JSON output: {rules_file.name}")
                    if csv_file.exists():
                        print(f"📄 CSV output: {csv_file.name}")
                    print(f"📂 Output directory: {self.config.get_rules_extracted_dir()}")
            else:
                print(f"⚠️  Warning: Rules file not found: {rules_file}")
            print(f"{'=' * 80}\n")
        
        return result
    
    def step3_5_validate_rules(self) -> bool:
        """
        Step 3.5: Rule Validation (NEW)
        
        Validates extracted business rules for accuracy, consistency, and completeness.
        Checks confidence scores, numeric consistency, and cross-rule contradictions.
        """
        print("\n" + "=" * 80)
        print("📌 STEP 3.5 PRE-CHECK: Rule Validation")
        print("=" * 80)
        
        script_dir = Path(__file__).parent / "agents"
        rules_file = self.config.get_rules_extracted_dir() / "compliance_rules_with_entities.json"
        validation_dir = self.config.get_rules_extracted_dir() / ".." / "agent-3-5-validation"
        
        print(f"📂 Checking rules file: {rules_file}")
        if not rules_file.exists():
            print(f"❌ Rules file not found. Ensure Step 3 completed successfully!")
            return False
        
        with open(rules_file, 'r') as f:
            rules_data = json.load(f)
            total_rules = sum(len(entity_data.get('business_rules', [])) 
                            for entity_data in rules_data.get('entity_types', {}).values())
            print(f"✅ Found {total_rules} rules to validate")
        
        print(f"📤 Validation report will be saved to: {validation_dir}")
        print(f"{'=' * 80}\n")
        
        print(f"\n🤖 LAUNCHING AGENT: agent_3_5_rule_validator.py")
        result = self._run_agent(
            agent_name="Rule Validation Agent",
            command=[
                sys.executable,
                str(script_dir / "agent_3_5_rule_validator.py"),
                "--rules-file", str(rules_file),
                "--source-dir", str(self.organized_dir),
                "--output-dir", str(validation_dir)
            ],
            description="Validating rules for accuracy, consistency, and confidence",
            step_number="3.5"
        )
        
        if result:
            print("\n" + "=" * 80)
            print("✅ STEP 3.5 POST-CHECK: Rule Validation")
            print("=" * 80)
            summary_file = Path(validation_dir) / "validation_summary.txt"
            if summary_file.exists():
                print(f"✅ Validation complete")
                print(f"📄 Summary report: {summary_file}")
            print(f"{'=' * 80}\n")
        
        return result
    
    def step4_merge_rules_with_entities(self) -> bool:
        """
        Step 4: Merge Rules with Entities
        
        Merges Agent 2 (entity definitions) with Agent 3 (business rules)
        to create enriched business rules with entity information.
        """
        print("\n" + "=" * 80)
        print("📌 STEP 4 PRE-CHECK: Merge Rules with Entities")
        print("=" * 80)
        
        # Check entity file from Step 2
        entity_file = self.config.get_entity_relationship_dir() / "entity_types_and_relationships.json"
        print(f"📂 Checking entities: {entity_file}")
        if not entity_file.exists():
            print(f"❌ Entity file not found. Run Step 2 first!")
            return False
        print(f"✅ Entity file exists")
        
        # Check rules file from Step 3
        rules_file = self.config.get_rules_extracted_dir() / "compliance_rules_with_entities.json"
        print(f"📂 Checking rules: {rules_file}")
        if not rules_file.exists():
            print(f"❌ Rules file not found. Run Step 3 first!")
            return False
        print(f"✅ Rules file exists")
        
        print(f"\n📤 Merged output will be saved to: {self.config.get_rules_with_entities_dir()}")
        print(f"{'=' * 80}\n")
        
        script_dir = Path(__file__).parent / "agents"
        print(f"\n🤖 LAUNCHING AGENT: agent_4_rules_with_entities_merger.py")
        result = self._run_agent(
            agent_name="Rules with Entities Merger",
            command=[
                sys.executable,
                str(script_dir / "agent_4_rules_with_entities_merger.py")
            ],
            description="Merging entity definitions with extracted business rules",
            step_number="4"
        )
        
        if result:
            print("\n" + "=" * 80)
            print("✅ STEP 4 POST-CHECK: Merge Rules with Entities")
            print("=" * 80)
            merged_file = self.config.get_rules_with_entities_dir() / "compliance_knowledge_graph.json"
            csv_file = self.config.get_rules_with_entities_dir() / "business_rules_complete.csv"
            
            if merged_file.exists():
                with open(merged_file, 'r') as f:
                    merged_data = json.load(f)
                    total_rules = sum(len(entity_data.get('business_rules', [])) 
                                    for entity_data in merged_data.get('entity_types', {}).values())
                    num_entities = len(merged_data.get('entity_types', {}))
                    print(f"✅ Successfully merged: {num_entities} entities with {total_rules} business rules")
                    print(f"📄 Knowledge graph: {merged_file.name}")
                    if csv_file.exists():
                        print(f"📄 CSV export: {csv_file.name}")
                    print(f"📂 Output directory: {self.config.get_rules_with_entities_dir()}")
            else:
                print(f"⚠️  Warning: Merged file not found: {merged_file}")
            print(f"{'=' * 80}\n")
        
        return result
    
    def step5_optimize_knowledge_graph(self) -> bool:
        """
        Step 5: Optimize Knowledge Graph
        
        Uses ComplianceKnowledgeGraphOptimizer to:
        - Deduplicate business rules (conservative, preserves meaningful variations)
        - Analyze rule dependencies (6 relationship types)
        - Generate optimized outputs with rationale
        
        Returns:
            True if successful, False otherwise
        """
        print("\n" + "=" * 80)
        print("📌 STEP 5 PRE-CHECK: Knowledge Graph Optimization")
        print("=" * 80)
        
        # Check merged rules from Step 4
        merged_file = self.config.get_rules_with_entities_dir() / "compliance_knowledge_graph.json"
        print(f"📂 Checking merged rules: {merged_file}")
        if not merged_file.exists():
            print(f"❌ Merged rules file not found. Run Step 4 first!")
            return False
        
        with open(merged_file, 'r') as f:
            merged_data = json.load(f)
            total_rules = sum(len(entity_data.get('business_rules', [])) 
                            for entity_data in merged_data.get('entity_types', {}).values())
            print(f"✅ Found {total_rules} rules to optimize")
        
        print(f"\n📤 Optimized output will be saved to: {self.config.get_optimized_dir()}")
        print("=" * 80)
        print()
        print("🎯 Agent: ComplianceKnowledgeGraphOptimizer")
        print(f"🤖 Model: {self.config.get_reasoning_model()} (reasoning effort: {self.config.get_reasoning_effort()})")
        print("📋 Tasks:")
        print("   • Deduplicate business rules (conservative)")
        print("   • Analyze rule dependencies")
        print("   • Generate optimized outputs with rationale")
        print()
        print("⏳ Starting optimization...")
        print()
        
        try:
            # Get paths
            knowledge_graph_optimizer = Path(__file__).parent / "agents" / "agent_5_knowledge_graph_optimizer.py"
            
            if not knowledge_graph_optimizer.exists():
                raise FileNotFoundError(f"Optimizer script not found: {knowledge_graph_optimizer}")
            
            # Run optimizer
            cmd = [sys.executable, str(knowledge_graph_optimizer)]
            
            print(f"\n🤖 LAUNCHING AGENT: agent_5_knowledge_graph_optimizer.py")
            print(f"📜 Script:     {knowledge_graph_optimizer.name}")
            print(f"📌 Step:       5")
            print(f"📌 Executing: {' '.join(cmd)}")
            print()
            
            # Set environment variables for subprocess
            env = os.environ.copy()
            if self.model_provider:
                env['KG_PROVIDER'] = self.model_provider
            # Pass max_workers to subprocess so agents use the correct parallelism
            if self.max_workers:
                env['MAX_WORKERS'] = str(self.max_workers)
            # Pass batch name to subprocess so it uses the correct batch paths
            batch_name = self.config.get_batch_name()
            if batch_name:
                env['KG_BATCH_NAME'] = batch_name
            # Pass source file name to subprocess so it uses the correct per-file paths
            source_file_name = self.config.get_source_file_name()
            if source_file_name:
                env['KG_SOURCE_FILE_NAME'] = source_file_name
            # Pass domain to subprocesses
            domain_val = self.config.get_domain()
            if domain_val:
                env['KG_DOMAIN'] = domain_val
            
            result = subprocess.run(
                cmd,
                cwd=Path(__file__).parent,
                capture_output=True,
                text=True,
                env=env
            )
            
            # Print output
            if result.stdout:
                print(result.stdout)
            
            if result.stderr:
                print("⚠️ Warnings/Errors:", file=sys.stderr)
                print(result.stderr, file=sys.stderr)
            
            if result.returncode != 0:
                raise RuntimeError(f"Optimizer failed with exit code {result.returncode}")
            
            # Verify outputs
            optimized_dir = self.config.get_optimized_dir()
            optimized_json = optimized_dir / "optimized_compliance_knowledge_graph.json"
            optimized_csv = optimized_dir / "optimized-business_rules_export.csv"
            optimized_report = optimized_dir / "optimized-optimization_report.txt"
            
            if not optimized_json.exists():
                raise FileNotFoundError(f"Expected output not found: {optimized_json}")
            
            print("✓ Verified optimized outputs:")
            print(f"  • {optimized_json.name}")
            print(f"  • {optimized_csv.name}")
            print(f"  • {optimized_report.name}")
            print()
            
            # Show optimization results
            print("\n" + "=" * 80)
            print("✅ STEP 5 POST-CHECK: Knowledge Graph Optimization")
            print("=" * 80)
            
            with open(optimized_json, 'r') as f:
                optimized_data = json.load(f)
                # Count rules from entity_types AND root-level business_rules array
                optimized_rules_in_entities = sum(len(entity_data.get('business_rules', [])) 
                                    for entity_data in optimized_data.get('entity_types', {}).values())
                optimized_rules_in_root = len(optimized_data.get('business_rules', []))
                optimized_rules = optimized_rules_in_entities + optimized_rules_in_root
                num_entities = len(optimized_data.get('entity_types', {}))
                
                # Calculate original rules for comparison.  In step 5 the
                # merged_file (agent-4 output) was present at PRE-CHECK and
                # while agent_5 was running.  If it has vanished by the time
                # the POST-CHECK reaches here it almost always means another
                # extraction run targeting the same batch has clobbered the
                # output tree.  Skip the comparison gracefully instead of
                # failing the whole pipeline.
                if merged_file.exists():
                    with open(merged_file, 'r') as orig_f:
                        orig_data = json.load(orig_f)
                        original_rules_in_entities = sum(len(entity_data.get('business_rules', [])) 
                                           for entity_data in orig_data.get('entity_types', {}).values())
                        original_rules_in_root = len(orig_data.get('business_rules', []))
                        original_rules = original_rules_in_entities + original_rules_in_root
                else:
                    original_rules = optimized_rules
                    print(
                        f"⚠️  Skipping original-vs-optimized comparison: merged file "
                        f"vanished after agent-5 ran ({merged_file.resolve()}). "
                        "Likely cause: a parallel extraction run targeting the same "
                        "batch overwrote the output tree.",
                        flush=True,
                    )
                removed_rules = original_rules - optimized_rules
                
                print(f"✅ Optimization complete:")
                print(f"   • Original rules: {original_rules}")
                print(f"   • Optimized rules: {optimized_rules}")
                if original_rules > 0:
                    print(f"   • Removed duplicates: {removed_rules} ({removed_rules/original_rules*100:.1f}%)")
                else:
                    print(f"   • Removed duplicates: {removed_rules} (N/A - no original rules)")
                print(f"   • Entities: {num_entities}")
                print(f"📄 Optimized knowledge graph: {optimized_json.name} ({optimized_json.stat().st_size / 1024:.1f} KB)")
                if optimized_csv.exists():
                    print(f"📄 CSV export: {optimized_csv.name}")
                if optimized_report.exists():
                    print(f"📄 Optimization report: {optimized_report.name}")
                print(f"📂 Output directory: {optimized_dir}")
            print(f"{'=' * 80}\n")
            
            self.flow_state["steps_completed"].append({
                "agent": "Knowledge Graph Optimization",
                "timestamp": datetime.now().isoformat(),
                "description": "Deduplicated rules and analyzed dependencies"
            })
            
            print("✅ Knowledge Graph Optimization completed successfully")
            print()
            return True
            
        except Exception as e:
            print(f"❌ Knowledge Graph Optimization failed: {str(e)}")
            self.flow_state["steps_failed"].append({
                "agent": "Knowledge Graph Optimization",
                "timestamp": datetime.now().isoformat(),
                "error": str(e)
            })
            return False
    
    def step6_visualize_knowledge_graph(self) -> bool:
        """
        Step 6: Visualization and Reports - Generate interactive HTML and reports.
        
        Creates an interactive visualization with network graph and rules table.
        
        Returns:
            True if visualization succeeded, False otherwise
        """
        print("\n" + "=" * 80)
        print("📌 STEP 6 PRE-CHECK: Visualization and Reports")
        print("=" * 80)
        
        # Check for input data: prefer optimized (Step 5), fall back to merged (Step 4)
        optimized_json = self.config.get_optimized_dir() / "optimized_compliance_knowledge_graph.json"
        merged_json = self.config.get_rules_with_entities_dir() / "compliance_knowledge_graph.json"
        
        if optimized_json.exists():
            print(f"📂 Using optimized data: {optimized_json}")
            print(f"✅ Optimized knowledge graph exists")
        elif merged_json.exists():
            print(f"📂 Using merged data (Step 5 skipped): {merged_json}")
            print(f"✅ Merged knowledge graph exists")
        else:
            print(f"❌ No knowledge graph found. Run Step 4 (or Step 5) first!")
            print(f"   Looked for:")
            print(f"     - {optimized_json}")
            print(f"     - {merged_json}")
            return False
        
        print(f"\n📤 Visualization will be saved to: {self.output_dir}")
        
        # Create output directory now (only when Agent 6 actually runs)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        print("=" * 80)
        print()
        print("🎯 Agent: KnowledgeGraphVisualizer")
        print("📋 Tasks:")
        print("   • Generate interactive network graph")
        print("   • Create searchable rules table")
        print("   • Export as standalone HTML file")
        print()
        print("⏳ Creating visualization...")
        print()
        
        try:
            # Get paths
            visualizer_script = Path(__file__).parent / "agents" / "agent_6_visualization_and_report.py"
            
            if not visualizer_script.exists():
                raise FileNotFoundError(f"Visualizer script not found: {visualizer_script}")
            
            # Run visualizer
            cmd = [sys.executable, str(visualizer_script)]
            
            print(f"\n🤖 LAUNCHING AGENT: agent_6_visualization_and_report.py")
            print(f"📜 Script:     {visualizer_script.name}")
            print(f"📌 Step:       6")
            print(f"📌 Executing: {' '.join(cmd)}")
            print()
            
            # Set environment variables for subprocess
            env = os.environ.copy()
            if self.model_provider:
                env['KG_PROVIDER'] = self.model_provider
            # Pass max_workers to subprocess so agents use the correct parallelism
            if self.max_workers:
                env['MAX_WORKERS'] = str(self.max_workers)
            # Pass batch name to subprocess so it uses the correct batch paths
            batch_name = self.config.get_batch_name()
            if batch_name:
                env['KG_BATCH_NAME'] = batch_name
            # Pass source file name to subprocess so it uses the correct per-file paths
            source_file_name = self.config.get_source_file_name()
            if source_file_name:
                env['KG_SOURCE_FILE_NAME'] = source_file_name
            # Pass domain to subprocesses
            domain_val = self.config.get_domain()
            if domain_val:
                env['KG_DOMAIN'] = domain_val
            
            result = subprocess.run(
                cmd,
                cwd=Path(__file__).parent,
                capture_output=True,
                text=True,
                env=env
            )
            
            # Print output
            if result.stdout:
                print(result.stdout)
            
            if result.stderr:
                print("⚠️ Warnings/Errors:", file=sys.stderr)
                print(result.stderr, file=sys.stderr)
            
            if result.returncode != 0:
                raise RuntimeError(f"Visualizer failed with exit code {result.returncode}")
            
            # Verify output - check for source-named file first, then fallback
            source_name = self.config.get_batch_name() or self.config.get_source_file_name()
            if source_name:
                viz_file = self.output_dir / f"{source_name}_knowledge_graph.html"
            else:
                viz_file = self.output_dir / "knowledge_graph_visualization.html"
            
            if not viz_file.exists():
                raise FileNotFoundError(f"Expected output not found: {viz_file}")
            
            print("✓ Verified visualization output:")
            print(f"  • {viz_file.name}")
            print()
            
            print("\n" + "=" * 80)
            print("✅ STEP 6 POST-CHECK: Visualization and Reports")
            print("=" * 80)
            print(f"✅ Visualization created successfully")
            print(f"📄 HTML file: {viz_file.name}")
            print(f"🌐 File size: {viz_file.stat().st_size / 1024:.1f} KB")
            print(f"📂 Output directory: {self.output_dir}")
            print(f"🔗 File path: file://{viz_file.resolve()}")
            print(f"{'=' * 80}\n")
            print(f"📂 Output directory: {self.output_dir}")
            print(f"🔗 File path: file://{viz_file.resolve()}")
            print(f"{'=' * 80}\n")
            
            self.flow_state["steps_completed"].append({
                "agent": "Visualization and Reports",
                "timestamp": datetime.now().isoformat(),
                "description": "Created interactive HTML visualization and reports"
            })
            
            print("✅ Visualization and Reports completed successfully")
            print()
            
            # Open the HTML visualization in the default browser
            print("🌐 Opening visualization in browser...")
            try:
                webbrowser.open(f'file://{viz_file.resolve()}')
                print(f"✓ Browser opened: {viz_file.resolve()}")
            except Exception as e:
                print(f"⚠️ Could not open browser automatically: {e}")
                print(f"   Please open manually: {viz_file.resolve()}")
            print()
            
            return True
            
        except Exception as e:
            print(f"❌ Visualization and Reports failed: {str(e)}")
            self.flow_state["steps_failed"].append({
                "agent": "Visualization and Reports",
                "timestamp": datetime.now().isoformat(),
                "error": str(e)
            })
            return False
    
    def run_complete_flow(self) -> bool:
        """
        Execute the complete agentic flow from start to finish (with validation).
        
        Returns:
            True if all steps completed successfully, False otherwise
        """
        start_time = datetime.now()
        total_steps = 7  # 6 main steps + validation (step 3.5)
        
        # Define agent scripts for reference
        script_dir = Path(__file__).parent / "agents"
        agent_scripts = {
            1: ("agent_1_document_organizer.py", "Document Organizer", "Chunks docs with size normalization"),
            2: ("agent_2_entity_extractor.py", "Entity Extractor", "Extracts entities & relationships"),
            3: ("agent_3_rules_extractor.py", "Rules Extractor", "Extracts rules (word-balanced batches)"),
            "3.5": ("agent_3_5_rule_validator.py", "Rule Validator", "Validates rule quality & consistency"),
            4: ("agent_4_rules_with_entities_merger.py", "Rules+Entities Merger", "Merges rules with entity definitions"),
            5: ("agent_5_knowledge_graph_optimizer.py", "KG Optimizer", "Deduplicates & analyzes dependencies"),
            6: ("agent_6_visualization_and_report.py", "Visualizer", "Generates interactive HTML reports"),
        }
        
        print("\n" + "=" * 80)
        print("🎬 STARTING COMPLETE AGENTIC KNOWLEDGE EXTRACTION FLOW")
        print("=" * 80)
        print()
        print("📋 Pipeline Configuration:")
        print(f"   🤖 Model Provider: {self.model_provider.upper()}")
        print(f"   🏷️  Domain:          {self.config.get_domain().upper()}")
        print(f"   📁 Source:         {self.source_dir}")
        print(f"   🎯 Target Rules:   {self.target_rules}")
        print(f"   📊 Total Steps:    {total_steps} (6 main + validation)")
        print()
        print("🤖 AGENTS TO BE EXECUTED:")
        print("─" * 80)
        print(f"   {'Step':<6} {'Script':<40} {'Description'}")
        print("─" * 80)
        for step, (script, name, desc) in agent_scripts.items():
            status = "⏳" if step == 1 else "⬚"
            print(f"   {status} {str(step):<4} {script:<40} {desc}")
        print("─" * 80)
        print()
        print("📍 Pipeline Steps:")
        print("   1️⃣  Knowledge Organization (Document Chunking + Size Normalization)")
        print("   2️⃣  Entity-Relationship Extraction (Meta-Agent)")
        print("   3️⃣  Business Rules Extraction (Word-Balanced Batches)")
        print("   3️⃣.5️⃣ Rule Validation (Quality Check)")
        print("   4️⃣  Merge Rules with Entities")
        if self.skip_optimize:
            print("   5️⃣  Optimize Knowledge Graph (SKIPPED - --skip-optimize)")
        else:
            print("   5️⃣  Optimize Knowledge Graph (Deduplication)")
        print("   6️⃣  Visualization and Reports (HTML)")
        print()
        print("=" * 80)
        print()
        
        # Get source file name for progress messages
        source_name = self.source_file_name or "all documents"
        
        # Track completed steps
        completed_steps = []
        
        # Step 1: Organize Knowledge
        print("\n" + "=" * 80)
        print(f"📍 PIPELINE PROGRESS [{source_name}]: Step 1/6 - Knowledge Organization")
        print("=" * 80 + "\n")
        self._print_progress_summary(completed_steps, current_step="1")
        if not self.step1_organize_knowledge():
            print(f"\n❌ PIPELINE STOPPED [{source_name}]: Knowledge Organization failed")
            self._print_failure_summary(start_time)
            return False
        completed_steps.append("1")
        print(f"✅ [{source_name}] Step 1/6 completed - proceeding to Step 2...")
        self._print_progress_summary(completed_steps, current_step="2")
        
        # Step 2: Extract Entity-Relationships
        print("\n" + "=" * 80)
        print(f"📍 PIPELINE PROGRESS [{source_name}]: Step 2/6 - Entity-Relationship Extraction")
        print("=" * 80 + "\n")
        if not self.step2_extract_entity_relationships():
            print(f"\n❌ PIPELINE STOPPED [{source_name}]: Entity-Relationship Extraction failed")
            self._print_failure_summary(start_time)
            return False
        completed_steps.append("2")
        print(f"✅ [{source_name}] Step 2/6 completed - proceeding to Step 3...")
        self._print_progress_summary(completed_steps, current_step="3")
        
        # Step 3: Extract Business Rules
        print("\n" + "=" * 80)
        print(f"📍 PIPELINE PROGRESS [{source_name}]: Step 3/6 - Business Rules Extraction (Parallel)")
        print("=" * 80 + "\n")
        if not self.step3_extract_business_rules():
            print(f"\n❌ PIPELINE STOPPED [{source_name}]: Business Rules Extraction failed")
            self._print_failure_summary(start_time)
            return False
        completed_steps.append("3")
        print(f"✅ [{source_name}] Step 3/6 completed - proceeding to Step 3.5 (Validation)...")
        self._print_progress_summary(completed_steps, current_step="3.5")
        
        # Step 3.5: Validate Rules (NEW)
        print("\n" + "=" * 80)
        print(f"📍 PIPELINE PROGRESS [{source_name}]: Step 3.5 - Rule Validation (Quality Check)")
        print("=" * 80 + "\n")
        if not self.step3_5_validate_rules():
            print(f"\n⚠️  WARNING [{source_name}]: Rule Validation failed - continuing anyway (non-blocking)")
        else:
            completed_steps.append("3.5")
            print(f"✅ [{source_name}] Step 3.5 completed - proceeding to Step 4...")
        self._print_progress_summary(completed_steps, current_step="4")
        
        # Step 4: Merge Rules with Entities
        print("\n" + "=" * 80)
        print(f"📍 PIPELINE PROGRESS [{source_name}]: Step 4/6 - Merge Rules with Entities")
        print("=" * 80 + "\n")
        if not self.step4_merge_rules_with_entities():
            print(f"\n❌ PIPELINE STOPPED [{source_name}]: Rules+Entities Merge failed")
            self._print_failure_summary(start_time)
            return False
        completed_steps.append("4")
        print(f"✅ [{source_name}] Step 4/6 completed - proceeding to Step 5...")
        self._print_progress_summary(completed_steps, current_step="5")
        
        # Step 5: Optimize Knowledge Graph
        if self.skip_optimize:
            print("\n" + "=" * 80)
            print(f"⏭️  PIPELINE PROGRESS [{source_name}]: Step 5/6 - SKIPPED (--skip-optimize)")
            print("=" * 80 + "\n")
            completed_steps.append("5-skipped")
        else:
            print("\n" + "=" * 80)
            print(f"📍 PIPELINE PROGRESS [{source_name}]: Step 5/6 - Optimize Knowledge Graph (Parallel)")
            print("=" * 80 + "\n")
            if not self.step5_optimize_knowledge_graph():
                print(f"\n❌ PIPELINE STOPPED [{source_name}]: Knowledge Graph Optimization failed")
                self._print_failure_summary(start_time)
                return False
            completed_steps.append("5")
            print(f"✅ [{source_name}] Step 5/6 completed - proceeding to Step 6...")
        self._print_progress_summary(completed_steps, current_step="6")
        
        # Step 6: Visualization and Reports
        print("\n" + "=" * 80)
        print(f"📍 PIPELINE PROGRESS [{source_name}]: Step 6/6 - Visualization and Reports")
        print("=" * 80 + "\n")
        if not self.step6_visualize_knowledge_graph():
            print(f"\n❌ PIPELINE STOPPED [{source_name}]: Visualization and Reports failed")
            self._print_failure_summary(start_time)
            return False
        completed_steps.append("6")
        print(f"✅ [{source_name}] Step 6/6 completed - all steps finished!")
        self._print_progress_summary(completed_steps)
        
        # Final success summary
        self._print_success_summary(start_time)
        return True
    
    def _print_failure_summary(self, start_time: datetime):
        """Print failure summary with timing information."""
        end_time = datetime.now()
        duration = end_time - start_time
        
        print("\n" + "=" * 80)
        print("❌ PIPELINE FAILED")
        print("=" * 80)
        print()
        print("📊 Summary:")
        print(f"   • Steps Completed: {len(self.flow_state['steps_completed'])}")
        print(f"   • Steps Failed:    {len(self.flow_state['steps_failed'])}")
        print(f"   • Total Duration:  {duration}")
        print()
        if self.flow_state['steps_failed']:
            print("❌ Failed Step:")
            for failed in self.flow_state['steps_failed']:
                print(f"   • {failed['agent']}")
                print(f"     Error: {failed.get('error', 'Unknown')}")
        print("=" * 80)
    
    def _print_success_summary(self, start_time: datetime):
        """Print success summary with all output locations."""
        # Calculate duration
        end_time = datetime.now()
        duration = end_time - start_time
        
        # Final summary
        print("\n" + "=" * 80)
        print("🎉 AGENTIC FLOW COMPLETED SUCCESSFULLY")
        print("=" * 80)
        print()
        print("📊 Execution Summary:")
        print(f"   • Total Steps:     7 (6 main + validation)")
        print(f"   • Steps Completed: {len(self.flow_state['steps_completed'])}")
        print(f"   • Steps Failed:    {len(self.flow_state['steps_failed'])}")
        print(f"   • Total Duration:  {duration}")
        print()
        print("📁 Output Locations:")
        print(f"   1️⃣  Organized Docs:      {self.organized_dir}")
        print(f"   2️⃣  Entities:            {self.config.get_entity_relationship_dir()}")
        print(f"   3️⃣  Rules:               {self.config.get_rules_extracted_dir()}")
        print(f"   3️⃣.5️⃣ Validation:         {self.config.get_rules_extracted_dir()}/../agent-3-5-validation")
        print(f"   4️⃣  Complete KG:         {self.config.get_rules_with_entities_dir()}")
        print(f"   5️⃣  Optimized KG:        {self.config.get_optimized_dir()}")
        print(f"   6️⃣  Visualization:       {self.output_dir.absolute()}")
        print()
        print("🔍 Next Steps:")
        print("   1️⃣  Review validation report:")
        print(f"      cat {self.config.get_rules_extracted_dir()}/../agent-3-5-validation/validation_summary.txt")
        print()
        print("   2️⃣  View interactive visualization:")
        source_name = self.config.get_batch_name() or self.config.get_source_file_name()
        if source_name:
            viz_name = f"{source_name}_knowledge_graph.html"
        else:
            viz_name = "knowledge_graph_visualization.html"
        print(f"      open {self.output_dir}/{viz_name}")
        print()
        print("   3️⃣  Review optimized business rules:")
        print(f"      python agents/rules_viewer.py {self.output_dir}/optimized_compliance_knowledge_graph.json")
        print()
        print("   4️⃣  Analyze in spreadsheet:")
        print(f"      open {self.output_dir}/optimized-business_rules_export.csv")
        print()
        print("   5️⃣  Check optimization report:")
        print(f"      cat {self.output_dir}/optimized-business_rules_report.txt")
        print()
        print("   6️⃣  Check extraction metadata:")
        print(f"      cat {self.output_dir}/extraction_metadata.json | python -m json.tool")
        print()
        print("=" * 80)
    
    def run_single_step(self, step_number: int) -> bool:
        """
        Run a single step of the pipeline.
        
        Args:
            step_number: Step to execute (1-6)
            
        Returns:
            True if successful, False otherwise
        """
        steps = {
            1: self.step1_organize_knowledge,
            2: self.step2_extract_entity_relationships,
            3: self.step3_extract_business_rules,
            4: self.step4_merge_rules_with_entities,
            5: self.step5_optimize_knowledge_graph,
            6: self.step6_visualize_knowledge_graph
        }
        
        if step_number not in steps:
            print(f"❌ Invalid step number: {step_number}. Valid steps: 1-6")
            return False
        
        print(f"🎬 Running Step {step_number} only")
        print()
        
        return steps[step_number]()


def discover_batch_directories(source_dir: Path) -> Dict[str, List[Path]]:
    """
    Discover subdirectories in source_dir and find all supported files in each.
    
    Args:
        source_dir: Root directory to scan (e.g., compliance-files/)
        
    Returns:
        Dictionary mapping subdirectory name to list of files
        Example: {"healthcare": [Path("healthcare/doc1.pdf"), Path("healthcare/doc2.pdf")]}
    """
    supported_extensions = set(get_config().get_supported_extensions())
    batches = {}
    
    # Check if source_dir itself has files (flat structure)
    top_level_files = [f for f in source_dir.iterdir() 
                       if f.is_file() and f.suffix.lower() in supported_extensions]
    
    # Find subdirectories with files
    for subdir in source_dir.iterdir():
        if subdir.is_dir() and not subdir.name.startswith('.'):
            # Find all supported files in this subdirectory (recursively)
            files = []
            for ext in supported_extensions:
                files.extend(subdir.rglob(f'*{ext}'))
            
            if files:
                batches[subdir.name] = sorted(files)
    
    return batches


def run_batch_mode(args, provider: str, pipeline_start_time: datetime, domain: str = None):
    """
    Run batch mode: process all files in subdirectories together.
    
    Each subdirectory in compliance-files becomes a batch:
    - All files in the subdirectory are processed together
    - Output is stored under pipeline-output/{batch_name}/
    
    Args:
        args: Parsed command line arguments
        provider: AI provider (openai)
        pipeline_start_time: Start time for total duration tracking
        domain: Compliance domain (e.g. 'aml', 'mortgage')
    """
    print("\n" + "=" * 80)
    print("📦 BATCH PROCESSING MODE")
    print("=" * 80)
    print()
    
    # Get source directory
    temp_config = get_config(provider=provider)
    source_dir = Path(args.source) if args.source else temp_config.get_source_dir()
    
    if not source_dir.exists():
        print(f"❌ Error: Source directory not found: {source_dir}")
        sys.exit(1)
    
    # Discover batches (subdirectories with files)
    if args.batch_dir:
        # Check if explicit file list was provided (selected specific files)
        if args.files:
            files = [Path(f) for f in args.files]
            missing = [f for f in files if not f.exists()]
            if missing:
                print(f"❌ Error: Files not found: {', '.join(str(f) for f in missing)}")
                sys.exit(1)
            batches = {args.batch_dir: sorted(files)}
        else:
            # Process specific subdirectory — discover all files in it
            batch_dir = source_dir / args.batch_dir
            if not batch_dir.exists():
                print(f"❌ Error: Batch directory not found: {batch_dir}")
                sys.exit(1)
            
            supported_extensions = set(get_config().get_supported_extensions())
            files = []
            for ext in supported_extensions:
                files.extend(batch_dir.rglob(f'*{ext}'))
            
            if not files:
                print(f"❌ Error: No supported files found in {batch_dir}")
                sys.exit(1)
            
            batches = {args.batch_dir: sorted(files)}
    else:
        # Discover all subdirectories
        batches = discover_batch_directories(source_dir)
    
    if not batches:
        print(f"❌ Error: No subdirectories with files found in {source_dir}")
        print(f"\n💡 Tip: Create subdirectories in {source_dir} to organize files by project/domain")
        print(f"   Example structure:")
        print(f"   {source_dir}/")
        print(f"   ├── healthcare/")
        print(f"   │   ├── hipaa.pdf")
        print(f"   │   └── regulations.pdf")
        print(f"   └── finance/")
        print(f"       ├── sec-rules.pdf")
        print(f"       └── compliance.pdf")
        sys.exit(1)
    
    # Print discovered batches
    print(f"📁 Source Directory: {source_dir}")
    print(f"📦 Discovered {len(batches)} batch(es):")
    print()
    total_files = 0
    for batch_name, files in sorted(batches.items()):
        print(f"   📂 {batch_name}/ ({len(files)} files)")
        for f in files[:3]:
            print(f"      • {f.name}")
        if len(files) > 3:
            print(f"      ... and {len(files) - 3} more")
        total_files += len(files)
    print()
    print(f"   Total: {total_files} files across {len(batches)} batches")
    print("=" * 80 + "\n")
    
    # Track results
    all_results = []
    successful_batches = []
    failed_batches = []
    
    # Process each batch
    for batch_idx, (batch_name, batch_files) in enumerate(sorted(batches.items()), 1):
        batch_start_time = datetime.now()
        
        print("\n" + "=" * 80)
        print(f"📦 PROCESSING BATCH {batch_idx}/{len(batches)}: {batch_name}")
        print(f"   Files: {len(batch_files)}")
        print("=" * 80 + "\n")
        
        # Reload config for this batch
        reload_config(batch_name=batch_name, domain=domain)
        
        # Initialize pipeline for this batch
        flow = KnowledgeExtractionPipeline(
            source_files=[str(f) for f in batch_files],
            batch_name=batch_name,
            organized_dir=args.organized,
            output_dir=args.output,
            target_rules=args.target_rules,
            provider=provider,
            skip_optimize=args.skip_optimize,
            max_workers=args.workers,
            domain=domain
        )
        
        # Run flow
        try:
            if args.step:
                success = flow.run_single_step(args.step)
            else:
                success = flow.run_complete_flow()
        except Exception as e:
            print(f"❌ Error processing batch {batch_name}: {e}")
            import traceback
            traceback.print_exc()
            success = False
        
        batch_end_time = datetime.now()
        batch_duration = batch_end_time - batch_start_time
        
        # Track results
        result = {
            "batch_name": batch_name,
            "file_count": len(batch_files),
            "files": [f.name for f in batch_files],
            "success": success,
            "duration": str(batch_duration),
            "output_dir": str(flow.output_dir)
        }
        all_results.append(result)
        
        if success:
            successful_batches.append(batch_name)
        else:
            failed_batches.append(batch_name)
        
        print(f"\n{'=' * 80}")
        print(f"{'✅' if success else '❌'} BATCH {batch_idx}/{len(batches)}: {batch_name}")
        print(f"   Duration: {batch_duration}")
        print(f"{'=' * 80}\n")
    
    # Calculate and report total execution time
    pipeline_end_time = datetime.now()
    total_duration = pipeline_end_time - pipeline_start_time
    
    hours, remainder = divmod(total_duration.total_seconds(), 3600)
    minutes, seconds = divmod(remainder, 60)
    
    print("\n" + "=" * 80)
    print("🎉 BATCH PROCESSING COMPLETE")
    print("=" * 80)
    print()
    print("📊 Summary:")
    print(f"   • Total Batches:     {len(batches)}")
    print(f"   • Total Files:       {total_files}")
    print(f"   • Successful:        {len(successful_batches)}")
    print(f"   • Failed:            {len(failed_batches)}")
    print()
    if hours > 0:
        print(f"   • Total Duration:    {int(hours)}h {int(minutes)}m {int(seconds)}s")
    elif minutes > 0:
        print(f"   • Total Duration:    {int(minutes)}m {int(seconds)}s")
    else:
        print(f"   • Total Duration:    {seconds:.2f}s")
    print()
    
    if successful_batches:
        print("✅ Successfully processed batches:")
        for b in successful_batches:
            print(f"   • {b}")
    
    if failed_batches:
        print()
        print("❌ Failed batches:")
        for b in failed_batches:
            print(f"   • {b}")
    
    print()
    print("📁 Output Structure:")
    print("   pipeline-output/")
    for result in all_results:
        status = "✅" if result["success"] else "❌"
        print(f"   {status} {result['batch_name']}/")
        print(f"      ├── agent-1-organized-documents/")
        print(f"      ├── agent-2-entities/")
        print(f"      ├── agent-3-rules/")
        print(f"      ├── agent-3-5-validation/")
        print(f"      ├── agent-4-rules-with-entities/")
        print(f"      ├── agent-5-optimized/")
        print(f"      └── agent-6-visualization-and-report/")
    print()
    print("=" * 80)
    
    # Run merge phase if requested and we have multiple successful batches
    if (args.merge or args.merge_only) and len(successful_batches) >= 2:
        print("\n" + "=" * 80)
        print("🔀 MERGE PHASE: Combining Knowledge Graphs")
        print("=" * 80)
        merge_success = run_merge_phase(provider, args.merge_strategy)
        if merge_success:
            print("\n✅ Merge phase completed successfully!")
            print(f"   📁 Merged output: pipeline-output/_merged/")
        else:
            print("\n⚠️  Merge phase failed")
    elif args.merge and len(successful_batches) < 2:
        print("\n⚠️  Skipping merge phase: Need at least 2 successful batches to merge")
        print(f"   Successful batches: {len(successful_batches)}")
    
    # Exit with appropriate code (success only if all batches succeeded)
    sys.exit(0 if len(failed_batches) == 0 else 1)


def run_merge_phase(provider: str, strategy: str = "provenance") -> bool:
    """
    Run the rule-type-centric merge pipeline to compare knowledge graphs.
    
    This executes:
    - Agent 7: Rule Type Clusterer (group rules by type)
    - Agent 8: Semantic Rule Matcher (LLM-powered parallel comparison)
    - Agent 9: Set Operations Calculator (union, intersection, differences)
    - Agent 10: Set Visualization (HTML reports)
    
    Args:
        provider: AI provider (openai)
        strategy: Merge strategy (not used in new pipeline, kept for compatibility)
        
    Returns:
        True if merge pipeline completed successfully
    """
    from datetime import datetime
    
    print(f"\n{'='*70}")
    print(f"🔀 JOINS PHASE: Set Operations on Knowledge Graphs")
    print(f"{'='*70}")
    print()
    print(f"ℹ️  The joins phase computes set operations using the joins pipeline.")
    print(f"   Operations: ∩ Intersection, G1-G2, G2-G1, ∪ Union, Contradictions")
    print()
    print(f"   Use join_graphs.py directly for more control:")
    print(f"     python join_graphs.py --list            # List available graphs")
    print(f"     python join_graphs.py --g1 X --g2 Y     # Compare two graphs")
    print(f"     python join_graphs.py --workers 15      # Set parallel workers")
    print()
    
    # Check if join_graphs.py exists
    joins_script = Path(__file__).parent / "join_graphs.py"
    if not joins_script.exists():
        print(f"❌ join_graphs.py not found: {joins_script}")
        return False
    
    # List available graphs first
    env = os.environ.copy()
    env['KG_PROVIDER'] = provider
    
    try:
        result = subprocess.run(
            [sys.executable, str(joins_script), "--list"],
            cwd=Path(__file__).parent,
            capture_output=True,
            text=True,
            env=env
        )
        print(result.stdout)
        if result.returncode != 0:
            print(f"❌ Failed to list available graphs")
            print(result.stderr)
            return False
    except Exception as e:
        print(f"❌ Error listing graphs: {e}")
        return False
    
    # Prompt user to select graphs
    print()
    print("To run set operations, use join_graphs.py with your chosen graphs:")
    print("  python join_graphs.py --g1 GRAPH1 --g2 GRAPH2 --workers 15")
    print()
    print("Example:")
    print("  python join_graphs.py --g1 graphA --g2 FM --workers 15")
    print()
    
    return True


def main():
    """Main entry point for the agentic flow."""
    
    import argparse
    from datetime import datetime
    
    # Track overall execution time
    pipeline_start_time = datetime.now()
    
    parser = argparse.ArgumentParser(
        description="Agentic Knowledge Extraction Flow - Complete Pipeline Orchestration",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Run complete flow for all files in compliance-files folder
  python knowledge_graph_generation.py
  
  # Run for a single specific file
  python knowledge_graph_generation.py --file compliance-files/my-document.pdf
  
  # Run with explicit provider validation
  python knowledge_graph_generation.py --provider openai
  
  # Run with custom directories and target rules
  python knowledge_graph_generation.py --source knowledge-files --output my-kg --target-rules 150
  
  # Run single step only
  python knowledge_graph_generation.py --step 1  # Knowledge organization only
  python knowledge_graph_generation.py --step 3  # Business rules extraction only
  
  # Run with provider validation and specific step
  
  # Custom configuration
  python knowledge_graph_generation.py \
    --provider openai \
    --source my-documents \
    --organized my-documents-organized \
    --output my-knowledge-graph \
    --target-rules 200
    
  # Batch mode: process all files in subdirectories together
  python knowledge_graph_generation.py --batch
  python knowledge_graph_generation.py --batch --provider openai
  python knowledge_graph_generation.py --batch --provider openai --workers 40
        """
    )
    
    parser.add_argument(
        "--source",
        default=None,
        help="Source directory containing PDF files (default: from config.json)"
    )
    
    parser.add_argument(
        "--file",
        default=None,
        help="Process a single specific file instead of all files in source directory"
    )
    
    parser.add_argument(
        "--files",
        nargs="+",
        default=None,
        help="Process specific files (space-separated paths relative to compliance-files/)"
    )
    
    parser.add_argument(
        "--batch",
        action="store_true",
        help="Batch mode: scan compliance-files for subdirectories and process all files in each subdirectory together"
    )
    
    parser.add_argument(
        "--batch-dir",
        default=None,
        help="Process a specific subdirectory as a batch (e.g., --batch-dir healthcare)"
    )
    
    parser.add_argument(
        "--organized",
        default=None,
        help="Directory for organized/chunked documents (default: from config.json)"
    )
    
    parser.add_argument(
        "--output",
        default=None,
        help="Output directory for final visualization (default: from config.json)"
    )
    
    parser.add_argument(
        "--target-rules",
        type=int,
        default=None,
        help="Target number of business rules to extract (default: from config.json)"
    )
    
    parser.add_argument(
        "--step",
        type=int,
        choices=[1, 2, 3, 4, 5, 6],
        help="Run single step only (1: organize, 2: entities, 3: rules, 4: merge, 5: optimize, 6: visualize)"
    )
    
    parser.add_argument(
        "--skip-optimize",
        action="store_true",
        help="Skip Step 5 (knowledge graph optimization/deduplication). Saves time; Step 6 uses Step 4 output directly."
    )
    
    parser.add_argument(
        "--merge",
        action="store_true",
        help="Run merge phase (Agent 7-9) after per-document processing to combine all KGs"
    )
    
    parser.add_argument(
        "--merge-only",
        action="store_true",
        help="Only run merge phase (skip per-document processing). Requires existing per-document KGs."
    )
    
    parser.add_argument(
        "--merge-strategy",
        type=str,
        choices=["union", "intersection", "provenance"],
        default="provenance",
        help="Merge strategy: union (all rules), intersection (common rules), provenance (all with tracking)"
    )
    
    parser.add_argument(
        "--provider",
        type=str,
        default="openai",
        choices=["openai"],
        help="AI provider. This build is OpenAI-only."
    )
    
    parser.add_argument(
        "--workers",
        type=int,
        default=None,
        help="Maximum number of parallel workers for LLM calls (default: 20). Higher values increase throughput but use more API quota."
    )

    parser.add_argument(
        "--domain",
        type=str,
        default=None,
        help="Compliance domain to use for knowledge extraction (e.g., 'mortgage', 'aml'). Defaults to value in config.json 'domain.active'."
    )
    
    args = parser.parse_args()

    # Determine domain: args > env var > config.json
    domain = getattr(args, 'domain', None) or os.getenv('KG_DOMAIN') or None

    # This build is OpenAI-only.
    provider = args.provider or "openai"

    # Handle --merge-only flag (skip per-document processing)
    if args.merge_only:
        print("\n" + "=" * 80)
        print("🔀 MERGE-ONLY MODE: Skipping per-document processing")
        print("=" * 80)
        print(f"Provider: {provider}")
        print(f"Strategy: {args.merge_strategy}")
        print()
        
        merge_success = run_merge_phase(provider, args.merge_strategy)
        
        if merge_success:
            print("\n✅ Merge-only mode completed successfully!")
            sys.exit(0)
        else:
            print("\n❌ Merge-only mode failed")
            sys.exit(1)
    
    # ==========================================================================
    # BATCH MODE: Process all files in subdirectories together
    # ==========================================================================
    if args.batch or args.batch_dir:
        run_batch_mode(args, provider, pipeline_start_time, domain=domain)
        return
    
    # ==========================================================================
    # STANDARD MODE: Process individual files separately
    # ==========================================================================
    # Steps 5+ don't need source files — they operate on pipeline-output
    if args.step and args.step >= 5:
        # Late steps: skip source file discovery, run directly
        temp_config = get_config(provider=provider, domain=domain)
        flow = KnowledgeExtractionPipeline(
            organized_dir=args.organized,
            output_dir=args.output,
            target_rules=args.target_rules,
            provider=provider,
            skip_optimize=args.skip_optimize,
            max_workers=args.workers,
            domain=domain
        )
        try:
            success = flow.run_single_step(args.step)
        except Exception as e:
            print(f"❌ Error running step {args.step}: {e}")
            import traceback
            traceback.print_exc()
            success = False
        sys.exit(0 if success else 1)
    
    # Determine which files to process
    if args.files:
        # Process specific files (multiple)
        source_files = [Path(f) for f in args.files]
        missing = [f for f in source_files if not f.exists()]
        if missing:
            print(f"❌ Error: Files not found: {', '.join(str(f) for f in missing)}")
            sys.exit(1)
    elif args.file:
        # Process a single specific file
        source_files = [Path(args.file)]
        if not source_files[0].exists():
            print(f"❌ Error: File not found: {args.file}")
            sys.exit(1)
    else:
        # Get source directory
        temp_config = get_config(provider=provider, domain=domain)
        source_dir = Path(args.source) if args.source else temp_config.get_source_dir()
        
        if not source_dir.exists():
            print(f"❌ Error: Source directory not found: {source_dir}")
            sys.exit(1)
        
        # Find all supported files in source directory (top level only, not subdirs)
        supported_extensions = set(get_config().get_supported_extensions())
        source_files = [f for f in source_dir.iterdir() 
                       if f.is_file() and f.suffix.lower() in supported_extensions]
        
        if not source_files:
            print(f"❌ Error: No supported files found in {source_dir}")
            print(f"   Supported formats: {', '.join(supported_extensions)}")
            print(f"\n💡 Tip: Use --batch to process subdirectories")
            sys.exit(1)
        
        # Sort files alphabetically for consistent ordering
        source_files = sorted(source_files)
    
    # Print summary of files to process
    print("\n" + "=" * 80)
    print("📁 FILES TO PROCESS")
    print("=" * 80)
    print(f"Total files: {len(source_files)}")
    for i, f in enumerate(source_files, 1):
        print(f"  {i}. {f.name}")
    print("=" * 80 + "\n")
    
    # Track results for all files
    all_results = []
    successful_files = []
    failed_files = []
    
    # Process each file
    for file_idx, source_file in enumerate(source_files, 1):
        file_start_time = datetime.now()
        
        print("\n" + "=" * 80)
        print(f"📄 PROCESSING FILE {file_idx}/{len(source_files)}: {source_file.name}")
        print("=" * 80 + "\n")
        
        # Reload config for each file to reset the source_file_name
        reload_config(source_file_name=source_file.stem, domain=domain)
        
        # Initialize flow with the specific file
        flow = KnowledgeExtractionPipeline(
            source_file=str(source_file),
            organized_dir=args.organized,
            output_dir=args.output,
            target_rules=args.target_rules,
            provider=provider,
            skip_optimize=args.skip_optimize,
            max_workers=args.workers,
            domain=domain
        )
        
        # Run flow
        try:
            if args.step:
                success = flow.run_single_step(args.step)
            else:
                success = flow.run_complete_flow()
        except Exception as e:
            print(f"❌ Error processing {source_file.name}: {e}")
            import traceback
            traceback.print_exc()
            success = False
        
        file_end_time = datetime.now()
        file_duration = file_end_time - file_start_time
        
        # Track results
        result = {
            "file": source_file.name,
            "file_stem": source_file.stem,
            "success": success,
            "duration": str(file_duration),
            "output_dir": str(flow.output_dir)
        }
        all_results.append(result)
        
        if success:
            successful_files.append(source_file.name)
        else:
            failed_files.append(source_file.name)
        
        print(f"\n{'=' * 80}")
        print(f"{'✅' if success else '❌'} FILE {file_idx}/{len(source_files)}: {source_file.name}")
        print(f"   Duration: {file_duration}")
        print(f"{'=' * 80}\n")
    
    # Calculate and report total execution time
    pipeline_end_time = datetime.now()
    total_duration = pipeline_end_time - pipeline_start_time
    
    hours, remainder = divmod(total_duration.total_seconds(), 3600)
    minutes, seconds = divmod(remainder, 60)
    
    print("\n" + "=" * 80)
    print("🎉 MULTI-FILE PIPELINE COMPLETE")
    print("=" * 80)
    print()
    print("📊 Summary:")
    print(f"   • Total Files:       {len(source_files)}")
    print(f"   • Successful:        {len(successful_files)}")
    print(f"   • Failed:            {len(failed_files)}")
    print()
    if hours > 0:
        print(f"   • Total Duration:    {int(hours)}h {int(minutes)}m {int(seconds)}s")
    elif minutes > 0:
        print(f"   • Total Duration:    {int(minutes)}m {int(seconds)}s")
    else:
        print(f"   • Total Duration:    {seconds:.2f}s")
    print()
    
    if successful_files:
        print("✅ Successfully processed files:")
        for f in successful_files:
            print(f"   • {f}")
    
    if failed_files:
        print()
        print("❌ Failed files:")
        for f in failed_files:
            print(f"   • {f}")
    
    print()
    print("📁 Output Structure:")
    print("   pipeline-output/")
    for result in all_results:
        status = "✅" if result["success"] else "❌"
        print(f"   {status} {result['file_stem']}/")
        print(f"      ├── agent-1-organized-documents/")
        print(f"      ├── agent-2-entities/")
        print(f"      ├── agent-3-rules/")
        print(f"      ├── agent-3-5-validation/")
        print(f"      ├── agent-4-rules-with-entities/")
        print(f"      ├── agent-5-optimized/")
        print(f"      └── agent-6-visualization-and-report/")
    print()
    print("=" * 80)
    
    # Run merge phase if requested and we have multiple successful files
    if (args.merge or args.merge_only) and len(successful_files) >= 2:
        print("\n" + "=" * 80)
        print("🔀 MERGE PHASE: Combining Knowledge Graphs")
        print("=" * 80)
        merge_success = run_merge_phase(provider, args.merge_strategy)
        if merge_success:
            print("\n✅ Merge phase completed successfully!")
            print(f"   📁 Merged output: pipeline-output/_merged/")
        else:
            print("\n⚠️  Merge phase failed")
    elif args.merge and len(successful_files) < 2:
        print("\n⚠️  Skipping merge phase: Need at least 2 successful files to merge")
        print(f"   Successful files: {len(successful_files)}")
    
    # Convert optimization reports to HTML for all successful files
    if successful_files:
        print("\n" + "=" * 80)
        print("📄 CONVERTING OPTIMIZATION REPORTS TO HTML")
        print("=" * 80)
        try:
            from utils.text_to_html_converter import convert_all_optimization_reports
            
            for result in all_results:
                if result["success"]:
                    # Get the pipeline output directory for this file
                    config = get_config(provider=provider, source_file_name=result["file_stem"])
                    pipeline_output_dir = config.get_output_dir().parent
                    
                    # Convert all optimization reports
                    convert_all_optimization_reports(pipeline_output_dir)
                
            print("\n✓ Optimization reports converted and ready for viewing")
        except Exception as e:
            print(f"⚠️  Warning: Could not convert optimization reports to HTML: {e}")
        print("=" * 80 + "\n")
    
    # Exit with appropriate code (success only if all files succeeded)
    sys.exit(0 if len(failed_files) == 0 else 1)


if __name__ == "__main__":
    main()
