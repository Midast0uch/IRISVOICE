#!/usr/bin/env python3
"""
Wake Word Discovery Service

This module provides wake word file discovery functionality for the IRIS voice system.
Scans the wake_words directory for .ppn files and provides metadata extraction.
"""

import os
import logging
import re
import subprocess
from pathlib import Path
from typing import List, Optional
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class WakeWordFile(BaseModel):
    """Represents a discovered wake word file."""
    filename: str = Field(description="Original filename with extension")
    path: str = Field(description="Absolute path to the file")
    display_name: str = Field(description="User-friendly display name")
    platform: str = Field(description="Platform identifier (windows, linux, mac, raspberry-pi)")
    version: str = Field(description="Version string (e.g., v4_0_0)")
    language: str = Field(default="en", description="Language code")


class WakeWordDiscovery:
    """
    Wake word file discovery service.
    
    Scans the wake_words directory for .ppn files and extracts metadata
    from filenames to provide user-friendly display names.
    """
    
    # Expected filename pattern: {name}_{lang}_{platform}_{version}.ppn
    # Example: hey-iris_en_windows_v4_0_0.ppn
    FILENAME_PATTERN = re.compile(
        r'^(?P<name>[a-zA-Z0-9\-]+)_(?P<lang>[a-z]{2})_(?P<platform>[a-z\-]+)_(?P<version>v\d+_\d+_\d+)\.ppn$'
    )
    
    # Expected hey-iris filename
    HEY_IRIS_FILENAME = "hey-iris_en_windows_v4_0_0.ppn"
    
    def __init__(self, wake_words_dir: Optional[str] = None):
        """
        Initialize wake word discovery service.

        Args:
            wake_words_dir: Path to wake words directory. Defaults to models/wake_words
                          relative to project root.
        """
        if wake_words_dir is None:
            # Build a priority list of candidate directories and pick the first one
            # that actually contains .ppn files. This handles:
            #   - Running from the original project root
            #   - Running from a git worktree (which may have an empty models/wake_words/)
            #   - Running from any other working directory
            candidates = [
                # 1. CWD-relative (where the user launched the backend from)
                Path.cwd() / "models" / "wake_words",
                # 2. File-relative: 3 levels up from backend/voice/wake_word_discovery.py
                #    -> resolves to the IRISVOICE project root
                Path(__file__).parent.parent.parent / "models" / "wake_words",
                # 3. One more level up (handles deeper nesting like worktrees)
                Path(__file__).parent.parent.parent.parent / "models" / "wake_words",
            ]

            # 4. Git-based: find the main worktree (handles git worktree setups where
            #    the worktree's models/wake_words/ is empty but the main project has .ppn files)
            #
            # The project may be a SUBDIRECTORY of the git repo root (e.g. repo at
            # C:\dev\ with IRISVOICE\ inside it).  We compute the relative offset of
            # the current project root (3 levels up from this file) from the current
            # worktree root and apply the same offset to the main repo root so we land
            # in the right folder (e.g. C:\dev\IRISVOICE\models\wake_words\).
            try:
                file_dir = Path(__file__).parent
                # Current worktree root
                toplevel_result = subprocess.run(
                    ["git", "rev-parse", "--show-toplevel"],
                    capture_output=True, text=True, timeout=5, cwd=str(file_dir),
                )
                # Main repo root (parent of git-common-dir)
                common_result = subprocess.run(
                    ["git", "rev-parse", "--git-common-dir"],
                    capture_output=True, text=True, timeout=5, cwd=str(file_dir),
                )
                if toplevel_result.returncode == 0 and common_result.returncode == 0:
                    worktree_root = Path(toplevel_result.stdout.strip()).resolve()
                    main_repo_root = Path(common_result.stdout.strip()).resolve().parent

                    # project_root is 3 levels up from this file:
                    # backend/voice/wake_word_discovery.py -> backend/voice -> backend -> IRISVOICE
                    project_root = file_dir.parent.parent.resolve()

                    try:
                        # Relative path from the worktree root to the project root
                        # e.g. "IRISVOICE" when repo root is one level above IRISVOICE/
                        rel = project_root.relative_to(worktree_root)
                        main_project_root = main_repo_root / rel
                    except ValueError:
                        # project_root is not under worktree_root — fall back to repo root
                        main_project_root = main_repo_root

                    git_candidate = main_project_root / "models" / "wake_words"
                    if git_candidate not in candidates:
                        candidates.append(git_candidate)
                        logger.debug(
                            f"[WakeWordDiscovery] Added git main worktree candidate: {git_candidate}"
                        )
            except Exception as git_err:
                logger.debug(f"[WakeWordDiscovery] Git worktree detection skipped: {git_err}")

            wake_words_dir = candidates[-1]  # fallback: last candidate (dir may not exist, scan handles it)
            for candidate in candidates:
                if candidate.exists() and list(candidate.glob("*.ppn")):
                    wake_words_dir = candidate
                    logger.info(f"[WakeWordDiscovery] Found .ppn files in: {candidate}")
                    break
            else:
                logger.warning(
                    f"[WakeWordDiscovery] No .ppn files found in any candidate directory. "
                    f"Searched: {[str(c) for c in candidates]}"
                )

        self._wake_words_dir = Path(wake_words_dir)
        self._discovered_files: List[WakeWordFile] = []

        logger.info(f"[WakeWordDiscovery] Initialized with directory: {self._wake_words_dir}")
    
    def scan_directory(self) -> List[WakeWordFile]:
        """
        Scan wake_words directory for .ppn files.
        
        Returns:
            List of discovered WakeWordFile objects
        """
        self._discovered_files = []
        
        # Check if directory exists
        if not self._wake_words_dir.exists():
            logger.warning(
                f"[WakeWordDiscovery] Wake words directory does not exist: {self._wake_words_dir}"
            )
            return self._discovered_files
        
        # Scan for .ppn files
        ppn_files = list(self._wake_words_dir.glob("*.ppn"))
        
        if not ppn_files:
            logger.warning(
                f"[WakeWordDiscovery] No .ppn files found in {self._wake_words_dir}"
            )
            return self._discovered_files
        
        logger.info(f"[WakeWordDiscovery] Found {len(ppn_files)} .ppn file(s)")
        
        # Process each file
        for ppn_file in ppn_files:
            try:
                wake_word_file = self._parse_filename(ppn_file)
                if wake_word_file:
                    self._discovered_files.append(wake_word_file)
                    logger.info(
                        f"[WakeWordDiscovery] Discovered: {wake_word_file.filename} "
                        f"-> '{wake_word_file.display_name}'"
                    )
                else:
                    logger.warning(
                        f"[WakeWordDiscovery] Could not parse filename: {ppn_file.name}"
                    )
            except Exception as e:
                logger.error(
                    f"[WakeWordDiscovery] Error processing {ppn_file.name}: {e}",
                    exc_info=True
                )
        
        # Verify hey-iris file
        self.verify_hey_iris()
        
        return self._discovered_files
    
    def _parse_filename(self, file_path: Path) -> Optional[WakeWordFile]:
        """
        Parse wake word filename to extract metadata.
        
        Args:
            file_path: Path to the .ppn file
        
        Returns:
            WakeWordFile object or None if parsing fails
        """
        filename = file_path.name
        
        # Try to match the expected pattern
        match = self.FILENAME_PATTERN.match(filename)
        
        if not match:
            # Fallback: try to extract at least the name part
            logger.warning(
                f"[WakeWordDiscovery] Filename doesn't match expected pattern: {filename}"
            )
            # Simple fallback: use filename without extension as display name
            name_part = filename.replace('.ppn', '').replace('_', ' ').replace('-', ' ')
            return WakeWordFile(
                filename=filename,
                path=str(file_path.absolute()),
                display_name=self.get_display_name(filename),
                platform="unknown",
                version="unknown",
                language="en"
            )
        
        # Extract components from regex match
        name = match.group('name')
        lang = match.group('lang')
        platform = match.group('platform')
        version = match.group('version')
        
        # Generate display name
        display_name = self.get_display_name(filename)
        
        return WakeWordFile(
            filename=filename,
            path=str(file_path.absolute()),
            display_name=display_name,
            platform=platform,
            version=version,
            language=lang
        )
    
    def get_display_name(self, filename: str) -> str:
        """
        Convert filename to user-friendly display name.
        
        Removes .ppn extension, platform suffixes, and formats the name.
        
        Examples:
            hey-iris_en_windows_v4_0_0.ppn -> Hey Iris
            jarvis_en_linux_v3_0_0.ppn -> Jarvis
            computer_en_mac_v2_1_0.ppn -> Computer
        
        Args:
            filename: Original filename
        
        Returns:
            Formatted display name
        """
        # Remove .ppn extension
        name = filename.replace('.ppn', '')
        
        # Extract just the wake word name (first part before underscore)
        # Example: "hey-iris_en_windows_v4_0_0" -> "hey-iris"
        name_part = name.split('_')[0]
        
        # Replace hyphens with spaces
        name_part = name_part.replace('-', ' ')
        
        # Capitalize each word
        display_name = ' '.join(word.capitalize() for word in name_part.split())
        
        return display_name
    
    def verify_hey_iris(self) -> bool:
        """
        Verify that the hey-iris wake word file exists.
        
        Returns:
            True if hey-iris file is found, False otherwise
        """
        hey_iris_found = any(
            wf.filename == self.HEY_IRIS_FILENAME
            for wf in self._discovered_files
        )
        
        if hey_iris_found:
            logger.info(
                f"[WakeWordDiscovery] Verified: {self.HEY_IRIS_FILENAME} found"
            )
        else:
            logger.warning(
                f"[WakeWordDiscovery] Warning: {self.HEY_IRIS_FILENAME} not found in "
                f"{self._wake_words_dir}"
            )
        
        return hey_iris_found
    
    def get_discovered_files(self) -> List[WakeWordFile]:
        """
        Get list of discovered wake word files.
        
        Returns:
            List of WakeWordFile objects
        """
        return self._discovered_files
    
    def get_file_by_filename(self, filename: str) -> Optional[WakeWordFile]:
        """
        Get wake word file by filename.
        
        Args:
            filename: Filename to search for
        
        Returns:
            WakeWordFile object or None if not found
        """
        for wf in self._discovered_files:
            if wf.filename == filename:
                return wf
        return None
    
    def get_file_by_display_name(self, display_name: str) -> Optional[WakeWordFile]:
        """
        Get wake word file by display name.
        
        Args:
            display_name: Display name to search for
        
        Returns:
            WakeWordFile object or None if not found
        """
        for wf in self._discovered_files:
            if wf.display_name.lower() == display_name.lower():
                return wf
        return None
