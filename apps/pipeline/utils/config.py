"""
Configuration Management Module

Loads and manages configuration from config.json with environment variable overrides.
"""

import os
import json
from pathlib import Path
from typing import Any, Dict, Optional
import re
from dotenv import load_dotenv

# Load environment variables from .env file at module level (runs once on import)
# Use explicit path relative to project root
_project_root = Path(__file__).parent.parent
_env_path = _project_root / '.env'
load_dotenv(dotenv_path=_env_path)

# Rule-type colour palettes keyed by domain.
# Mortgage uses the original 10-category set.
# AML replaces prohibition/definition/exception with reporting/monitoring/screening.
_RULE_TYPE_COLORS_BY_DOMAIN = {
    'mortgage': {
        'eligibility':   '#3b82f6',  # Blue       – who/what qualifies
        'constraint':    '#ef4444',  # Red        – numeric limits & thresholds
        'calculation':   '#06b6d4',  # Cyan       – formulas & computations
        'validation':    '#f59e0b',  # Amber      – data accuracy checks
        'process':       '#ec4899',  # Pink       – workflow sequences
        'compliance':    '#10b981',  # Green      – regulatory adherence
        'documentation': '#8b5cf6',  # Purple     – required records
        'prohibition':   '#dc2626',  # Dark Red   – explicit forbiddances
        'definition':    '#6366f1',  # Indigo     – term definitions
        'exception':     '#f97316',  # Orange     – special-case waivers
    },
}

# Quick-filter priority types shown as shortcut buttons per domain
_DOMAIN_PRIORITY_FILTER_TYPES = {
    'mortgage':           ['eligibility',     'validation',   'compliance'],
}


class Config:
    """Configuration manager that loads settings from config.json and environment variables."""
    
    _instance = None
    _config = None
    _provider = None
    _source_file_name = None  # Name of the source file being processed (without extension)
    _batch_name = None  # Name of the batch/subdirectory being processed
    _domain = None  # Active compliance domain (e.g., 'mortgage', 'aml')
    
    def __new__(cls, *args, **kwargs):
        """Singleton pattern to ensure only one config instance."""
        if cls._instance is None:
            cls._instance = super(Config, cls).__new__(cls)
        return cls._instance
    
    def __init__(self, config_path: Optional[str] = None, provider: Optional[str] = None, source_file_name: Optional[str] = None, batch_name: Optional[str] = None, domain: Optional[str] = None):
        """
        Initialize configuration.
        
        Args:
            config_path: Path to config.json file. Defaults to config.json in project root.
            provider: Explicitly set provider ('openai'). If None, auto-detects.
            source_file_name: Name of the source file being processed (without extension).
                            When set, outputs are organized by this name.
            batch_name: Name of the batch/subdirectory being processed.
                       When set, outputs are organized under this batch name.
                       Takes precedence over source_file_name for output paths.
            domain: Active compliance domain (e.g., 'mortgage', 'aml'). If None, reads from
                   config.json 'domain.active' or KG_DOMAIN environment variable.
        """
        if self._config is not None:
            # Update provider if specified
            if provider is not None:
                self._provider = provider
            # Update source file name if specified
            if source_file_name is not None:
                self._source_file_name = source_file_name
            # Update batch name if specified
            if batch_name is not None:
                self._batch_name = batch_name
            # Update domain if specified
            if domain is not None:
                self._domain = domain
            return
        
        # Set provider if specified
        if provider is not None:
            self._provider = provider
        
        # Set batch name if specified, or read from environment
        if batch_name is not None:
            self._batch_name = batch_name
        elif os.getenv('KG_BATCH_NAME'):
            self._batch_name = os.getenv('KG_BATCH_NAME')
        
        # Set source file name if specified, or read from environment
        if source_file_name is not None:
            self._source_file_name = source_file_name
        elif os.getenv('KG_SOURCE_FILE_NAME'):
            self._source_file_name = os.getenv('KG_SOURCE_FILE_NAME')

        # Set domain if specified, or read from environment
        if domain is not None:
            self._domain = domain
        elif os.getenv('KG_DOMAIN'):
            self._domain = os.getenv('KG_DOMAIN')
            
        if config_path is None:
            # Allow an explicit override (used by tests/CI to pin the canonical
            # config.example.json), otherwise default to config.json in the root.
            env_path = os.getenv("P2K_CONFIG_PATH")
            if env_path:
                config_path = env_path
            else:
                current_dir = Path(__file__).parent
                config_path = current_dir.parent / "config.json"

        self.config_path = Path(config_path)
        self._load_config()
    
    def _load_config(self):
        """Load configuration from JSON file.

        Falls back to ``config.example.json`` when ``config.json`` is absent so a
        fresh clone, CI, or the test suite work without a manual copy step.
        """
        path = self.config_path
        if not path.exists():
            example = path.with_name("config.example.json")
            if example.exists():
                path = example
            else:
                raise FileNotFoundError(
                    f"Configuration file not found: {self.config_path} "
                    f"(and no {example.name} fallback). "
                    "Copy config.example.json to config.json to get started."
                )

        with open(path, 'r') as f:
            self._config = json.load(f)
        
        # Process environment variable substitutions (assign the result!)
        self._config = self._process_env_vars(self._config)
    
    def _process_env_vars(self, config: Any) -> Any:
        """
        Recursively process configuration, replacing ${VAR_NAME} with environment variables.
        
        Args:
            config: Configuration dictionary or value to process
            
        Returns:
            Processed configuration with environment variables substituted
        """
        if isinstance(config, dict):
            return {key: self._process_env_vars(value) for key, value in config.items()}
        elif isinstance(config, list):
            return [self._process_env_vars(item) for item in config]
        elif isinstance(config, str):
            # Replace ${VAR_NAME} with environment variable value
            pattern = r'\$\{([^}]+)\}'
            matches = re.findall(pattern, config)
            for var_name in matches:
                env_value = os.getenv(var_name, '')
                config = config.replace(f'${{{var_name}}}', env_value)
            return config
        else:
            return config
    
    def get(self, key_path: str, default: Any = None) -> Any:
        """
        Get configuration value using dot notation.
        
        Args:
            key_path: Dot-separated path to configuration value (e.g., 'openai.api_key')
            default: Default value if key not found
            
        Returns:
            Configuration value or default
            
        Examples:
            >>> config = Config()
            >>> config.get('openai.api_key')
            'sk-...'
            >>> config.get('directories.source')
            'data/input/knowledge-files'
        """
        keys = key_path.split('.')
        value = self._config
        
        for key in keys:
            if isinstance(value, dict) and key in value:
                value = value[key]
            else:
                return default
        
        return value
    
    def get_openai_api_key(self) -> str:
        """Get OpenAI API key from config or environment."""
        api_key = self.get('openai.api_key', '')
        if not api_key:
            api_key = os.getenv('OPENAI_API_KEY', '')
        if not api_key:
            raise ValueError(
                "OpenAI API key not found. Set OPENAI_API_KEY environment variable "
                "or update config.json"
            )
        return api_key

    def get_reasoning_model(self) -> str:
        """Get reasoning model name."""
        return self.get('openai.models.reasoning', 'gpt-5.2')

    def get_reasoning_effort(self) -> str:
        """Get reasoning effort level (low, medium, high)."""
        return self.get('openai.models.reasoning_effort', 'medium')

    def get_model_provider(self) -> str:
        """Return the model provider. This build is OpenAI-only."""
        return 'openai'

    def get_pipeline_base_path(self) -> Path:
        """Get base path for pipeline outputs based on batch/source file name.

        Priority order:
        1. batch_name (if set): pipeline-output/{batch_name}/
        2. source_file_name (if set): pipeline-output/{source_file_name}/
        3. Neither: pipeline-output/
        """
        base = Path('pipeline-output')
        # Batch name takes precedence over source file name
        if self._batch_name:
            base = base / self._batch_name
        elif self._source_file_name:
            base = base / self._source_file_name
        return base
    
    def set_source_file_name(self, name: str):
        """Set the source file name for per-file output organization.
        
        Args:
            name: The source file name (without extension)
        """
        self._source_file_name = name
    
    def get_source_file_name(self) -> Optional[str]:
        """Get the current source file name."""
        return self._source_file_name
    
    def set_batch_name(self, name: str):
        """Set the batch name for batch output organization.
        
        Args:
            name: The batch/subdirectory name
        """
        self._batch_name = name
    
    def get_batch_name(self) -> Optional[str]:
        """Get the current batch name."""
        return self._batch_name
    
    def get_optimizer_model(self) -> str:
        """Get optimizer model name."""
        return self.get('openai.models.optimizer', 'gpt-5.2')
    
    def get_source_dir(self) -> Path:
        """Get source directory path."""
        return Path(self.get('directories.source', 'compliance-files'))
    
    def get_organized_dir(self) -> Path:
        """Get organized directory path."""
        base = self.get_pipeline_base_path()
        return base / 'agent-1-organized-documents'
    
    def get_entity_relationship_dir(self) -> Path:
        """Get entity-relationship directory path."""
        base = self.get_pipeline_base_path()
        return base / 'agent-2-entities'
    
    def get_rules_extracted_dir(self) -> Path:
        """Get rules extracted directory path (Agent 3 output)."""
        base = self.get_pipeline_base_path()
        return base / 'agent-3-rules'
    
    def get_rules_with_entities_dir(self) -> Path:
        """Get rules with entities directory path (Agent 4 output)."""
        base = self.get_pipeline_base_path()
        return base / 'agent-4-rules-with-entities'
    
    def get_optimized_dir(self) -> Path:
        """Get optimized directory path (Agent 5 output)."""
        base = self.get_pipeline_base_path()
        return base / 'agent-5-optimized'
    
    def get_visualization_dir(self) -> Path:
        """Get visualization and reports directory path (Agent 6 output)."""
        base = self.get_pipeline_base_path()
        return base / 'agent-6-visualization-and-report'
    
    def get_output_dir(self) -> Path:
        """Get output directory path (same as visualization and reports for backwards compatibility)."""
        return self.get_visualization_dir()
    
    def get_target_rules(self) -> int:
        """Get target number of rules to extract."""
        # Check environment variable first
        env_target = os.getenv('TARGET_RULES')
        if env_target:
            return int(env_target)
        return self.get('rules_extractor.target_rules', 300)
    
    def get_n_iterations(self) -> int:
        """Get number of iterations for entity extraction."""
        # Check environment variable first
        env_iterations = os.getenv('N_ITERATIONS')
        if env_iterations:
            return int(env_iterations)
        return self.get('entity_extractor.n_iterations', 3)
    
    def get_chunk_size_target(self) -> int:
        """Get target chunk size for document organization."""
        return self.get('document_organizer.chunk_size_target', 2000)
    
    def get_max_chunk_size(self) -> int:
        """Get maximum chunk size for document organization."""
        return self.get('document_organizer.max_chunk_size', 3000)
    
    def get_min_chunk_size(self) -> int:
        """Get minimum chunk size for document organization."""
        return self.get('document_organizer.min_chunk_size', 500)
    
    def get_rules_per_batch(self) -> int:
        """Get number of rules to extract per batch.
        
        Configurable via rules_extractor.rules_per_batch_openai (default 10).
        """
        return self.get('rules_extractor.rules_per_batch_openai',
                        self.get('rules_extractor.rules_per_batch', 10))

    def get_max_retries(self) -> int:
        """Get maximum number of API retries."""
        return self.get('openai.rate_limiting.max_retries', 3)

    def get_timeout(self) -> int:
        """Get API timeout in seconds."""
        return self.get('openai.rate_limiting.timeout', 300)

    # ── LLM defaults ──

    def get_default_temperature(self) -> float:
        """Get default LLM temperature."""
        return self.get('llm.default_temperature', 0.7)

    def get_default_max_tokens(self) -> int:
        """Get default LLM max tokens."""
        return self.get('llm.default_max_tokens', 8192)

    def get_default_model(self) -> str:
        """Get default LLM model for the factory function."""
        return self.get('llm.default_model', 'gpt-4o')

    # ── Domain ──

    def get_domain(self) -> str:
        """Get the active compliance domain (e.g., 'mortgage', 'aml')."""
        if self._domain is not None:
            return self._domain
        return self.get('domain.active', 'mortgage')

    def set_domain(self, domain: str):
        """Set the active compliance domain."""
        self._domain = domain

    def get_domain_prompts_dir(self) -> Path:
        """Get the path to the active domain's prompts directory.

        Returns e.g. Path('domain-prompts/mortgage') or Path('domain-prompts/aml').
        The path is relative to the project root.
        """
        base = self.get('domain.prompts_base_dir', 'domain-prompts')
        return Path(base) / self.get_domain()

    def get_rule_type_colors(self) -> dict:
        """Return rule-type → hex-colour mapping for the active domain.

        Falls back to the mortgage palette for unrecognised domains.
        Always includes 'unknown' as a grey catch-all.
        """
        domain = self.get_domain()
        palette = _RULE_TYPE_COLORS_BY_DOMAIN.get(domain, _RULE_TYPE_COLORS_BY_DOMAIN['mortgage']).copy()
        palette.setdefault('unknown', '#64748b')
        return palette

    def get_domain_priority_filter_types(self) -> list:
        """Return the 3 most prominent rule-type filter buttons for the active domain."""
        domain = self.get_domain()
        return _DOMAIN_PRIORITY_FILTER_TYPES.get(domain, _DOMAIN_PRIORITY_FILTER_TYPES['mortgage'])


    def get_max_workers(self) -> int:
        """Get maximum number of parallel workers for pipeline operations."""
        env_val = os.getenv('MAX_WORKERS')
        if env_val:
            return int(env_val)
        return self.get('pipeline.max_workers', 30)

    def get_supported_extensions(self) -> list:
        """Get list of supported file extensions for the pipeline."""
        return self.get('pipeline.supported_extensions', ['.pdf', '.txt', '.md', '.docx'])

    # ── Document organizer ──

    def get_chunk_overlap(self) -> int:
        """Get chunk overlap size for document splitting."""
        return self.get('document_organizer.chunk_overlap', 200)

    def get_csv_rows_per_chunk(self) -> int:
        """Get number of CSV/Excel rows per chunk."""
        return self.get('document_organizer.csv_rows_per_chunk', 50)

    def get_max_content_for_analysis(self) -> int:
        """Get maximum content length for LLM document structure analysis."""
        return self.get('document_organizer.max_content_for_analysis', 12000)

    def get_simple_chunk_size(self) -> int:
        """Get fallback simple chunk size."""
        return self.get('document_organizer.simple_chunk_size', 3000)

    def get_docx_fallback_chunk_size(self) -> int:
        """Get DOCX fallback chunk target size."""
        return self.get('document_organizer.docx_fallback_chunk_size', 2000)

    # ── Entity extractor ──

    def get_entity_extractor_temperature(self) -> float:
        """Get temperature for entity extraction LLM calls."""
        return self.get('entity_extractor.temperature', 0.7)

    def get_entity_extractor_max_tokens(self) -> int:
        """Get max tokens for entity extraction LLM calls."""
        return self.get('entity_extractor.max_tokens', 8192)

    # ── Rules extractor ──

    def get_rules_batch_size(self) -> int:
        """Get batch size for rules extraction (files per batch)."""
        return self.get('rules_extractor.batch_size', 8)

    def get_rules_max_content_length(self) -> int:
        """Get max content length per document for rules extraction."""
        return self.get('rules_extractor.max_content_length', 8000)

    def get_rules_target_words_per_batch(self) -> int:
        """Get target words per batch for rules extraction."""
        return self.get('rules_extractor.target_words_per_batch', 8000)

    def get_rules_temperature(self) -> float:
        """Get temperature for rules extraction LLM calls."""
        return self.get('rules_extractor.temperature', 0.7)

    def get_rules_max_tokens(self) -> int:
        """Get max tokens for rules extraction LLM calls."""
        return self.get('rules_extractor.max_tokens', 8192)

    def get_rules_low_confidence_threshold(self) -> int:
        """Get low confidence threshold for rules flagging."""
        return self.get('rules_extractor.low_confidence_threshold', 70)

    def get_rules_default_confidence_score(self) -> int:
        """Get default confidence score when breakdown is missing."""
        return self.get('rules_extractor.default_confidence_score', 75)

    def get_rules_confidence_weights(self) -> dict:
        """Get confidence score weights for rules extraction."""
        return self.get('rules_extractor.confidence_weights', {
            'extraction_clarity': 0.30,
            'numeric_precision': 0.25,
            'context_completeness': 0.20,
            'source_authority': 0.15,
            'logical_consistency': 0.10
        })

    # ── Optimizer (Agent 5) ──

    def get_optimizer_model_name(self) -> str:
        """Get the model to use for the optimizer agent."""
        return self.get('optimizer.model', 'gpt-5-mini')

    def get_optimizer_dedup_temperature(self) -> float:
        """Get temperature for deduplication analysis."""
        return self.get('optimizer.dedup_temperature', 0.2)

    def get_optimizer_dedup_max_tokens(self) -> int:
        """Get max tokens for deduplication analysis."""
        return self.get('optimizer.dedup_max_tokens', 8192)

    def get_optimizer_dependency_temperature(self) -> float:
        """Get temperature for dependency analysis."""
        return self.get('optimizer.dependency_temperature', 0.7)

    def get_optimizer_dependency_max_tokens(self) -> int:
        """Get max tokens for dependency analysis."""
        return self.get('optimizer.dependency_max_tokens', 16384)

    def get_optimizer_batch_size(self) -> int:
        """Get batch size for optimizer."""
        return self.get('optimizer.batch_size', 50)

    def get_optimizer_description_truncation_length(self) -> int:
        """Get description truncation length for optimizer."""
        return self.get('optimizer.description_truncation_length', 500)

    def get_optimizer_batched_temperature(self) -> float:
        """Get temperature for batched dependency analysis."""
        return self.get('optimizer.batched_temperature', 0.2)

    def get_optimizer_batched_max_tokens(self) -> int:
        """Get max tokens for batched dependency analysis."""
        return self.get('optimizer.batched_max_tokens', 16384)

    def get_optimizer_cross_batch_temperature(self) -> float:
        """Get temperature for cross-batch dependency analysis."""
        return self.get('optimizer.cross_batch_temperature', 0.2)

    def get_optimizer_cross_batch_max_tokens(self) -> int:
        """Get max tokens for cross-batch dependency analysis."""
        return self.get('optimizer.cross_batch_max_tokens', 8192)

    # ── Semantic matcher (Agent 8) ──

    def get_matcher_max_workers(self) -> int:
        """Get max workers for semantic rule matcher."""
        return self.get('semantic_matcher.max_workers', 30)

    def get_matcher_batch_size(self) -> int:
        """Get batch size for semantic rule matcher."""
        return self.get('semantic_matcher.batch_size', 10)

    def get_matcher_max_tokens(self) -> int:
        """Get max tokens for semantic rule matcher."""
        return self.get('semantic_matcher.max_tokens', 8000)

    # ── Join graphs ──

    def get_join_max_workers(self) -> int:
        """Get max workers for join graphs pipeline."""
        return self.get('join_graphs.max_workers', 31)

    def get_join_batch_size(self) -> int:
        """Get batch size for join graphs pipeline."""
        return self.get('join_graphs.batch_size', 10)
    
    def __repr__(self) -> str:
        """String representation of config."""
        return f"Config(config_path={self.config_path})"


# Global config instance
_config = None


def get_config(provider: Optional[str] = None, source_file_name: Optional[str] = None, batch_name: Optional[str] = None, domain: Optional[str] = None) -> Config:
    """
    Get global configuration instance.
    
    Args:
        provider: AI provider to use ('openai')
        source_file_name: Name of the source file being processed (without extension)
        batch_name: Name of the batch/subdirectory being processed
        domain: Active compliance domain (e.g., 'mortgage', 'aml')
    
    Returns:
        Config instance
    """
    global _config
    
    # Check environment variable first if provider not explicitly set
    if provider is None:
        provider = os.getenv('KG_PROVIDER')
    
    if batch_name is None:
        batch_name = os.getenv('KG_BATCH_NAME')

    if domain is None:
        domain = os.getenv('KG_DOMAIN')
    
    if _config is None:
        _config = Config(provider=provider, source_file_name=source_file_name, batch_name=batch_name, domain=domain)
    else:
        # Update provider if specified
        if provider is not None:
            _config._provider = provider
        # Update source file name if specified
        if source_file_name is not None:
            _config._source_file_name = source_file_name
        # Update batch name if specified
        if batch_name is not None:
            _config._batch_name = batch_name
        # Update domain if specified
        if domain is not None:
            _config._domain = domain
    return _config


def reload_config(config_path: Optional[str] = None, source_file_name: Optional[str] = None, batch_name: Optional[str] = None, domain: Optional[str] = None, provider: Optional[str] = None):
    """
    Reload configuration from file.

    Args:
        config_path: Optional path to config file
        source_file_name: Name of the source file being processed (without extension)
        batch_name: Name of the batch/subdirectory being processed
        domain: Active compliance domain (e.g., 'mortgage', 'aml')
        provider: LLM provider override ('openai'); if omitted the
                  previously-active provider is preserved via KG_PROVIDER env var.
    """
    global _config
    # Preserve the active provider across reloads so the pipeline does not
    # silently revert to the config.json default on each per-file reload.
    current_provider = provider or os.getenv('KG_PROVIDER')
    if current_provider:
        os.environ['KG_PROVIDER'] = current_provider
    _config = None
    Config._instance = None
    Config._config = None
    Config._source_file_name = None
    Config._batch_name = None
    Config._domain = None
    _config = Config(config_path, source_file_name=source_file_name, batch_name=batch_name, domain=domain)
    return _config
