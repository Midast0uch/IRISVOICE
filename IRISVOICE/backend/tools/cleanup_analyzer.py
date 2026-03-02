#!/usr/bin/env python3
"""
CleanupAnalyzer - Scan and identify unused files and dependencies

This module provides cleanup analysis capabilities for the IRISVOICE system:
- Scan for downloaded model files not referenced in active code
- Scan for Python dependencies in requirements.txt not imported in any module
- Scan for wake word files not selectable through the UI
- Scan for configuration files not loaded by any component
- Generate cleanup reports with dry-run support
- Execute cleanup with optional backup

Requirements: 21.1, 21.2, 21.3, 21.4, 21.6, 21.7
"""

import ast
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import List, Set, Dict, Optional
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


@dataclass
class UnusedFile:
    """Represents an unused file in the system"""
    path: str
    size_bytes: int
    last_accessed: datetime
    reason: str  # Why it's considered unused


@dataclass
class UnusedDependency:
    """Represents an unused Python dependency"""
    name: str
    version: str
    install_size_bytes: int
    reason: str


@dataclass
class CleanupReport:
    """Report of cleanup analysis"""
    unused_models: List[UnusedFile]
    unused_dependencies: List[UnusedDependency]
    unused_wake_words: List[UnusedFile]
    unused_configs: List[UnusedFile]
    total_size_bytes: int
    total_count: int
    warnings: List[str]
    timestamp: datetime


@dataclass
class CleanupResult:
    """Result of cleanup execution"""
    success: bool
    removed_files: List[str]
    removed_dependencies: List[str]
    freed_bytes: int
    errors: List[str]
    backup_path: Optional[str]


class CleanupAnalyzer:
    """
    Analyzes the codebase to identify unused files and dependencies.
    
    Uses AST parsing to find model references and imports in Python code.
    Scans for wake word files not selectable through the UI.
    Identifies configuration files not loaded by any component.
    """
    
    def __init__(self, project_root: Optional[Path] = None):
        """
        Initialize cleanup analyzer.
        
        Args:
            project_root: Optional project root path (defaults to auto-detect)
        """
        self._project_root = project_root or Path(__file__).parent.parent.parent
        logger.info(f"CleanupAnalyzer initialized with project root: {self._project_root}")
    
    def scan_unused_models(self) -> List[UnusedFile]:
        """
        Scan for downloaded model files not referenced in code.
        
        Returns:
            List of UnusedFile objects representing unused model files
        """
        unused_models = []
        
        # Define potential model directories
        model_dirs = [
            self._project_root / "models",
            self._project_root / "backend" / "models",
            self._project_root / ".cache" / "models",
        ]
        
        # Find all model files
        model_files = []
        for model_dir in model_dirs:
            if model_dir.exists():
                for ext in [".bin", ".gguf", ".safetensors", ".pt", ".pth", ".onnx"]:
                    model_files.extend(model_dir.rglob(f"*{ext}"))
        
        # Find all model references in code
        model_references = self._find_model_references()
        
        # Check each model file
        for model_file in model_files:
            model_name = model_file.name
            is_referenced = any(ref in model_name or model_name in ref for ref in model_references)
            
            if not is_referenced:
                try:
                    stat = model_file.stat()
                    unused_models.append(UnusedFile(
                        path=str(model_file.relative_to(self._project_root)),
                        size_bytes=stat.st_size,
                        last_accessed=datetime.fromtimestamp(stat.st_atime),
                        reason="Model file not referenced in any Python code"
                    ))
                except Exception as e:
                    logger.warning(f"Error accessing model file {model_file}: {e}")
        
        logger.info(f"Found {len(unused_models)} unused model files")
        return unused_models
    
    def scan_unused_dependencies(self) -> List[UnusedDependency]:
        """
        Scan for Python dependencies in requirements.txt not imported.
        
        Returns:
            List of UnusedDependency objects representing unused dependencies
        """
        unused_deps = []
        
        # Find requirements.txt
        requirements_file = self._project_root / "requirements.txt"
        if not requirements_file.exists():
            logger.warning("requirements.txt not found")
            return unused_deps
        
        # Parse requirements.txt
        dependencies = self._parse_requirements(requirements_file)
        
        # Find all imports in code
        imports = self._find_imports()
        
        # Check each dependency
        for dep_name, dep_version in dependencies.items():
            # Normalize dependency name for comparison
            normalized_name = dep_name.lower().replace("-", "_").replace(".", "_")
            
            # Check if dependency is imported
            is_imported = any(
                normalized_name in imp.lower() or imp.lower() in normalized_name
                for imp in imports
            )
            
            if not is_imported:
                unused_deps.append(UnusedDependency(
                    name=dep_name,
                    version=dep_version,
                    install_size_bytes=0,  # Would need pip show to get actual size
                    reason=f"Dependency '{dep_name}' not imported in any Python module"
                ))
        
        logger.info(f"Found {len(unused_deps)} unused dependencies")
        return unused_deps
    
    def scan_unused_wake_words(self) -> List[UnusedFile]:
        """
        Scan for wake word files not selectable through the UI.
        
        Returns:
            List of UnusedFile objects representing unused wake word files
        """
        unused_wake_words = []
        
        # Find wake_words directory
        wake_words_dir = self._project_root / "wake_words"
        if not wake_words_dir.exists():
            logger.warning("wake_words directory not found")
            return unused_wake_words
        
        # Find all .ppn files
        ppn_files = list(wake_words_dir.glob("*.ppn"))
        
        # Find wake word references in code
        wake_word_refs = self._find_wake_word_references()
        
        # Check each wake word file
        for ppn_file in ppn_files:
            file_name = ppn_file.name
            is_referenced = any(ref in file_name or file_name in ref for ref in wake_word_refs)
            
            if not is_referenced:
                try:
                    stat = ppn_file.stat()
                    unused_wake_words.append(UnusedFile(
                        path=str(ppn_file.relative_to(self._project_root)),
                        size_bytes=stat.st_size,
                        last_accessed=datetime.fromtimestamp(stat.st_atime),
                        reason="Wake word file not referenced in code or configuration"
                    ))
                except Exception as e:
                    logger.warning(f"Error accessing wake word file {ppn_file}: {e}")
        
        logger.info(f"Found {len(unused_wake_words)} unused wake word files")
        return unused_wake_words
    
    def scan_unused_configs(self) -> List[UnusedFile]:
        """
        Scan for configuration files not loaded by any component.
        
        Returns:
            List of UnusedFile objects representing unused config files
        """
        unused_configs = []
        
        # Find config directories
        config_dirs = [
            self._project_root / "backend" / "config",
            self._project_root / "backend" / "settings",
            self._project_root / "config",
        ]
        
        # Find all config files
        config_files = []
        for config_dir in config_dirs:
            if config_dir.exists():
                for ext in [".json", ".yaml", ".yml", ".toml", ".ini"]:
                    config_files.extend(config_dir.rglob(f"*{ext}"))
        
        # Find config file references in code
        config_refs = self._find_config_references()
        
        # Check each config file
        for config_file in config_files:
            file_name = config_file.name
            is_referenced = any(ref in file_name or file_name in ref for ref in config_refs)
            
            if not is_referenced:
                try:
                    stat = config_file.stat()
                    unused_configs.append(UnusedFile(
                        path=str(config_file.relative_to(self._project_root)),
                        size_bytes=stat.st_size,
                        last_accessed=datetime.fromtimestamp(stat.st_atime),
                        reason="Configuration file not loaded by any component"
                    ))
                except Exception as e:
                    logger.warning(f"Error accessing config file {config_file}: {e}")
        
        logger.info(f"Found {len(unused_configs)} unused config files")
        return unused_configs
    
    def generate_report(self, dry_run: bool = True) -> CleanupReport:
        """
        Generate cleanup report.
        
        Args:
            dry_run: If True, only report without removing files (default: True)
            
        Returns:
            CleanupReport with analysis results
            
        Requirements: 21.3, 21.4, 21.8, 21.10
        """
        logger.info(f"Generating cleanup report (dry_run={dry_run})")
        
        # Scan for unused items with detailed logging
        logger.info("Scanning for unused model files...")
        unused_models = self.scan_unused_models()
        logger.info(f"Scan complete: {len(unused_models)} unused model files found")
        
        logger.info("Scanning for unused dependencies...")
        unused_dependencies = self.scan_unused_dependencies()
        logger.info(f"Scan complete: {len(unused_dependencies)} unused dependencies found")
        
        logger.info("Scanning for unused wake word files...")
        unused_wake_words = self.scan_unused_wake_words()
        logger.info(f"Scan complete: {len(unused_wake_words)} unused wake word files found")
        
        logger.info("Scanning for unused configuration files...")
        unused_configs = self.scan_unused_configs()
        logger.info(f"Scan complete: {len(unused_configs)} unused config files found")
        
        # Calculate totals
        total_size = (
            sum(f.size_bytes for f in unused_models) +
            sum(f.size_bytes for f in unused_wake_words) +
            sum(f.size_bytes for f in unused_configs)
        )
        total_count = (
            len(unused_models) +
            len(unused_dependencies) +
            len(unused_wake_words) +
            len(unused_configs)
        )
        
        # Generate warnings
        warnings = []
        
        # Warning for total size exceeding 100MB (Requirement 21.8)
        if total_size > 100 * 1024 * 1024:  # 100MB
            warnings.append(f"Unused files exceed 100MB total size ({total_size / (1024*1024):.2f} MB)")
            logger.warning(f"Unused files exceed 100MB total size: {total_size / (1024*1024):.2f} MB")
        
        # Warnings for individual large unused items (>100MB)
        large_item_threshold = 100 * 1024 * 1024  # 100MB
        
        for model in unused_models:
            if model.size_bytes > large_item_threshold:
                warning_msg = f"Large unused model file: {model.path} ({model.size_bytes / (1024*1024):.2f} MB)"
                warnings.append(warning_msg)
                logger.warning(warning_msg)
        
        for wake_word in unused_wake_words:
            if wake_word.size_bytes > large_item_threshold:
                warning_msg = f"Large unused wake word file: {wake_word.path} ({wake_word.size_bytes / (1024*1024):.2f} MB)"
                warnings.append(warning_msg)
                logger.warning(warning_msg)
        
        for config in unused_configs:
            if config.size_bytes > large_item_threshold:
                warning_msg = f"Large unused config file: {config.path} ({config.size_bytes / (1024*1024):.2f} MB)"
                warnings.append(warning_msg)
                logger.warning(warning_msg)
        
        # Log dry-run mode status
        if dry_run:
            logger.info("Report generated in DRY-RUN mode - no files will be removed")
        else:
            logger.warning("Report generated in EXECUTION mode - files may be removed if cleanup is executed")
        
        report = CleanupReport(
            unused_models=unused_models,
            unused_dependencies=unused_dependencies,
            unused_wake_words=unused_wake_words,
            unused_configs=unused_configs,
            total_size_bytes=total_size,
            total_count=total_count,
            warnings=warnings,
            timestamp=datetime.now()
        )
        
        logger.info(f"Cleanup report generated: {total_count} items, {total_size / (1024*1024):.2f} MB")
        return report
    
    def execute_cleanup(
        self,
        items: List[str],
        backup: bool = True
    ) -> CleanupResult:
        """
        Execute cleanup with optional backup.
        
        Args:
            items: List of file paths to remove
            backup: If True, create backup before removing
            
        Returns:
            CleanupResult with execution results
        """
        logger.info(f"Executing cleanup for {len(items)} items (backup={backup})")
        
        removed_files = []
        errors = []
        freed_bytes = 0
        backup_path = None
        
        # Create backup if requested
        if backup:
            backup_path = self._create_backup(items)
            if not backup_path:
                return CleanupResult(
                    success=False,
                    removed_files=[],
                    removed_dependencies=[],
                    freed_bytes=0,
                    errors=["Failed to create backup"],
                    backup_path=None
                )
        
        # Remove files
        for item_path in items:
            try:
                full_path = self._project_root / item_path
                if full_path.exists() and full_path.is_file():
                    size = full_path.stat().st_size
                    full_path.unlink()
                    removed_files.append(item_path)
                    freed_bytes += size
                    logger.info(f"Removed file: {item_path} ({size} bytes)")
                else:
                    errors.append(f"File not found or not a file: {item_path}")
            except Exception as e:
                error_msg = f"Error removing {item_path}: {e}"
                errors.append(error_msg)
                logger.error(error_msg)
        
        success = len(errors) == 0
        logger.info(f"Cleanup completed: {len(removed_files)} files removed, {freed_bytes / (1024*1024):.2f} MB freed")
        
        return CleanupResult(
            success=success,
            removed_files=removed_files,
            removed_dependencies=[],  # Dependencies would need pip uninstall
            freed_bytes=freed_bytes,
            errors=errors,
            backup_path=backup_path
        )
    
    def _find_model_references(self) -> Set[str]:
        """
        Find model references in Python code using AST parsing.
        
        Returns:
            Set of model reference strings found in code
        """
        references = set()
        
        # Find all Python files
        python_files = list(self._project_root.rglob("*.py"))
        
        for py_file in python_files:
            try:
                with open(py_file, 'r', encoding='utf-8') as f:
                    content = f.read()
                    tree = ast.parse(content, filename=str(py_file))
                    
                    # Look for string literals that might be model references
                    for node in ast.walk(tree):
                        if isinstance(node, ast.Constant) and isinstance(node.value, str):
                            value = node.value
                            # Check if it looks like a model reference
                            if any(ext in value.lower() for ext in ['.bin', '.gguf', '.safetensors', '.pt', '.pth', '.onnx', 'model']):
                                references.add(value)
            except Exception as e:
                logger.debug(f"Error parsing {py_file}: {e}")
        
        return references
    
    def _find_imports(self) -> Set[str]:
        """
        Find all imports in Python code using AST parsing.
        
        Returns:
            Set of imported module names
        """
        imports = set()
        
        # Find all Python files
        python_files = list(self._project_root.rglob("*.py"))
        
        for py_file in python_files:
            try:
                with open(py_file, 'r', encoding='utf-8') as f:
                    content = f.read()
                    tree = ast.parse(content, filename=str(py_file))
                    
                    # Extract imports
                    for node in ast.walk(tree):
                        if isinstance(node, ast.Import):
                            for alias in node.names:
                                imports.add(alias.name.split('.')[0])
                        elif isinstance(node, ast.ImportFrom):
                            if node.module:
                                imports.add(node.module.split('.')[0])
            except Exception as e:
                logger.debug(f"Error parsing {py_file}: {e}")
        
        return imports
    
    def _find_wake_word_references(self) -> Set[str]:
        """
        Find wake word file references in code.
        
        Returns:
            Set of wake word file references
        """
        references = set()
        
        # Find all Python files
        python_files = list(self._project_root.rglob("*.py"))
        
        for py_file in python_files:
            try:
                with open(py_file, 'r', encoding='utf-8') as f:
                    content = f.read()
                    tree = ast.parse(content, filename=str(py_file))
                    
                    # Look for string literals that might be wake word references
                    for node in ast.walk(tree):
                        if isinstance(node, ast.Constant) and isinstance(node.value, str):
                            value = node.value
                            if '.ppn' in value.lower() or 'wake' in value.lower():
                                references.add(value)
            except Exception as e:
                logger.debug(f"Error parsing {py_file}: {e}")
        
        return references
    
    def _find_config_references(self) -> Set[str]:
        """
        Find configuration file references in code.
        
        Returns:
            Set of config file references
        """
        references = set()
        
        # Find all Python files
        python_files = list(self._project_root.rglob("*.py"))
        
        for py_file in python_files:
            try:
                with open(py_file, 'r', encoding='utf-8') as f:
                    content = f.read()
                    tree = ast.parse(content, filename=str(py_file))
                    
                    # Look for string literals that might be config references
                    for node in ast.walk(tree):
                        if isinstance(node, ast.Constant) and isinstance(node.value, str):
                            value = node.value
                            if any(ext in value.lower() for ext in ['.json', '.yaml', '.yml', '.toml', '.ini', 'config', 'settings']):
                                references.add(value)
            except Exception as e:
                logger.debug(f"Error parsing {py_file}: {e}")
        
        return references
    
    def _parse_requirements(self, requirements_file: Path) -> Dict[str, str]:
        """
        Parse requirements.txt file.
        
        Args:
            requirements_file: Path to requirements.txt
            
        Returns:
            Dictionary mapping package name to version
        """
        dependencies = {}
        
        try:
            with open(requirements_file, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    # Skip comments and empty lines
                    if not line or line.startswith('#'):
                        continue
                    
                    # Parse package name and version
                    if '==' in line:
                        name, version = line.split('==', 1)
                        dependencies[name.strip()] = version.strip()
                    elif '>=' in line:
                        name, version = line.split('>=', 1)
                        dependencies[name.strip()] = f">={version.strip()}"
                    else:
                        dependencies[line.strip()] = "any"
        except Exception as e:
            logger.error(f"Error parsing requirements.txt: {e}")
        
        return dependencies
    
    def _create_backup(self, items: List[str]) -> Optional[str]:
        """
        Create backup of files before cleanup.
        
        Args:
            items: List of file paths to backup
            
        Returns:
            Path to backup directory or None if failed
        """
        import shutil
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_dir = self._project_root / "backups" / f"cleanup_backup_{timestamp}"
        
        try:
            backup_dir.mkdir(parents=True, exist_ok=True)
            
            for item_path in items:
                source = self._project_root / item_path
                if source.exists() and source.is_file():
                    # Preserve directory structure in backup
                    dest = backup_dir / item_path
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, dest)
            
            logger.info(f"Backup created at: {backup_dir}")
            return str(backup_dir.relative_to(self._project_root))
        except Exception as e:
            logger.error(f"Error creating backup: {e}")
            return None
