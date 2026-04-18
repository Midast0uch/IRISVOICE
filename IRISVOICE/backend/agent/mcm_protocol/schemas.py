"""
Pydantic v2 models for all MCM protocol JSON structures.

All JSON files are validated through these models at orchestrator startup.
TypeAdapter instances are cached for repeated validation performance.

Per JsonManagement.md: Use Pydantic for all JSON → Python conversion.
Generate JSON Schema from models for self-validation of dynamic updates.
"""

from __future__ import annotations

from typing import Any, Optional
from pydantic import BaseModel, Field


# ── Core config models ────────────────────────────────────────────────────


class CompressionConfig(BaseModel):
    budget_pct:              float = 0.70
    recovery_target_tokens:  int   = 200
    nbl_max_tokens:          int   = 40
    active_files_max:        int   = 5
    unverified_edits_max:    int   = 3
    warnings_max:            int   = 2


class DCPConfig(BaseModel):
    turn_protection:  int        = 6
    error_age_turns:  int        = 4
    protected_tools:  list[str]  = Field(default_factory=list)


class MCMCore(BaseModel):
    protocol_version: str               = "0.2"
    description:      str               = ""
    enabled:          bool              = True
    last_updated:     str               = ""
    author:           str               = ""
    compression:      CompressionConfig = Field(default_factory=CompressionConfig)
    dcp:              DCPConfig         = Field(default_factory=DCPConfig)


# ── NBL / MITO schema models ──────────────────────────────────────────────


class MitoTagConfig(BaseModel):
    format:          str = "short"
    max_tokens:      int = 300
    inject_position: int = 1
    template:        str = ""
    note:            str = ""


class NBLSchema(BaseModel):
    protocol_version: str           = "0.2"
    description:      str           = ""
    nbl_format:       dict[str, Any] = Field(default_factory=dict)
    mito_tag:         MitoTagConfig  = Field(default_factory=MitoTagConfig)
    fallback:         str            = "plain_system_message"


# ── Recall rules models ───────────────────────────────────────────────────


class RecallPass(BaseModel):
    pass_:          int   = Field(alias="pass", default=1)
    name:           str   = ""
    description:    str   = ""
    enabled:        bool  = True
    min_similarity: float = 0.25

    model_config = {"populate_by_name": True}


class RecallRules(BaseModel):
    protocol_version:          str         = "0.2"
    description:               str         = ""
    fallback_ladder:           list[RecallPass] = Field(default_factory=list)
    max_results_per_pass:      int         = 3
    episodic_context_max_tokens: int       = 2000


# ── Workflow models ───────────────────────────────────────────────────────


class WorkflowStep(BaseModel):
    action:   str            = ""
    on_error: str            = "continue"   # "continue" | "abort"
    dry_run:  bool           = False
    params:   dict[str, Any] = Field(default_factory=dict)


class Workflow(BaseModel):
    name:        str               = ""
    description: str               = ""
    dry_run:     bool              = False
    steps:       list[WorkflowStep] = Field(default_factory=list)


# ── Root protocol model ───────────────────────────────────────────────────


class MCMProtocol(BaseModel):
    """
    Root model — merged from all JSON files at orchestrator startup.
    Batch-loaded once; hot-reloaded when any JSON mtime changes.
    """
    core:         MCMCore              = Field(default_factory=MCMCore)
    nbl_schema:   NBLSchema            = Field(default_factory=NBLSchema)
    recall_rules: RecallRules          = Field(default_factory=RecallRules)
    workflows:    dict[str, Workflow]  = Field(default_factory=dict)
