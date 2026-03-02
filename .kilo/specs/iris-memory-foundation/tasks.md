# Implementation Plan: IRIS Memory Foundation

## Overview

This implementation plan breaks the IRIS Memory Foundation spec into atomic tasks that can be executed autonomously. Each task includes:
- What to build
- Files to create/modify
- Requirements back-references
- Test instructions where applicable

**Task Groups:**
1. Project Setup & Dependencies
2. Database Layer (encryption, schema)
3. Embedding Service (singleton)
4. Storage Components (episodic, semantic)
5. Working Memory (zone-based context)
6. Memory Interface (single access boundary)
7. Learning System (distillation, skills)
8. Integration (AgentKernel, startup)
9. Testing & Verification
10. Additional Infrastructure (config, audit, retention, migration)

---

## Task Group 1: Project Setup & Dependencies

- [ ] 1.1 Add memory dependencies to requirements.txt
  - What to build: Add `sqlcipher3>=0.5.0`, `sqlite-vec>=0.1.0`, `sentence-transformers>=2.7.0` to requirements.txt
  - Files: `IRISVOICE/requirements.txt`
  - _Requirements: 6.1, 6.2, 9.5_

- [ ] 1.2 Create backend/memory package structure
  - What to build: Create `backend/memory/` directory with `__init__.py` exporting MemoryInterface and Episode
  - Files: `backend/memory/__init__.py`
  - _Requirements: 4.1, 9.1_

---

## Task Group 2: Database Layer

- [ ] 2.1 Implement open_encrypted_memory() function
  - What to build: SQLCipher connection factory with PRAGMA key, cipher_page_size=4096, kdf_iter=64000, journal_mode=WAL, foreign_keys=ON
  - Files: `backend/memory/db.py`
  - _Requirements: 6.1, 6.2, 6.5, 11.5_

- [ ] 2.2 Write tests for database encryption
  - What to build: Test that database cannot be read without correct key; test WAL mode is enabled
  - Files: `backend/memory/tests/test_db_encryption.py` (or appropriate test location)
  - Run: `pytest backend/memory/tests/test_db_encryption.py -v`
  - _Requirements: 6.1, 6.5_

---

## Task Group 3: Embedding Service

- [ ] 3.1 Implement EmbeddingService singleton
  - What to build: Thread-safe singleton with lazy loading of all-MiniLM-L6-v2; methods: encode(text), encode_batch(texts)
  - Files: `backend/memory/embedding.py`
  - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 11.2_

- [ ] 3.2 Write tests for EmbeddingService
  - What to build: Test singleton behavior (multiple instances same object); test lazy loading; test encode returns 384-dim vector
  - Files: `backend/memory/tests/test_embedding.py`
  - Run: `pytest backend/memory/tests/test_embedding.py -v`
  - _Requirements: 5.1, 5.2, 5.6_

---

## Task Group 4: Storage Components

### Episodic Store

- [ ] 4.1 Implement EpisodicStore schema initialization
  - What to build: _init_schema() creating episodes table with all Torus-ready fields and indexes
  - Files: `backend/memory/episodic.py` (schema portion)
  - _Requirements: 2.1, 2.6, 2.7, 6.3, 6.4, 10.1, 10.2_

- [ ] 4.2 Implement EpisodicStore.store() method
  - What to build: Persist episode with embedding; compute outcome_score using formula from spec; handle JSON serialization of tool_sequence
  - Files: `backend/memory/episodic.py`
  - _Requirements: 2.1, 2.2_

- [ ] 4.3 Implement EpisodicStore.retrieve_similar() method
  - What to build: Vector similarity search using sqlite-vec; filter by min_score; return top N results
  - Files: `backend/memory/episodic.py`
  - _Requirements: 2.3, 2.4_

- [ ] 4.4 Implement EpisodicStore.retrieve_failures() method
  - What to build: Similarity search filtered to outcome_type='failure' for warning injection
  - Files: `backend/memory/episodic.py`
  - _Requirements: 2.3, 2.4_

- [ ] 4.5 Implement EpisodicStore.assemble_episodic_context() method
  - What to build: Format successes and failures for injection into prompts
  - Files: `backend/memory/episodic.py`
  - _Requirements: 2.4_

- [ ] 4.6 Implement EpisodicStore.get_stats() method
  - What to build: Return total_episodes, avg_score, successes, failures for UI/monitoring
  - Files: `backend/memory/episodic.py`
  - _Requirements: 2.1, 11.6_

- [ ] 4.7 Write tests for EpisodicStore
  - What to build: Test store/retrieve, similarity search, outcome scoring, failure retrieval
  - Files: `backend/memory/tests/test_episodic.py`
  - Run: `pytest backend/memory/tests/test_episodic.py -v`
  - _Requirements: 2.1, 2.2, 2.3, 2.4_

### Semantic Store

- [ ] 4.8 Implement SemanticStore schema initialization
  - What to build: _init_schema() creating semantic_entries and user_display_memory tables with indexes
  - Files: `backend/memory/semantic.py` (schema portion)
  - _Requirements: 3.1, 3.2, 3.4, 6.3, 6.4, 10.3_

- [ ] 4.9 Implement SemanticStore.update() method
  - What to build: Upsert with version increment on conflict; support category, key, value, confidence, source
  - Files: `backend/memory/semantic.py`
  - _Requirements: 3.2, 3.3, 10.3_

- [ ] 4.10 Implement SemanticStore.get() and delete() methods
  - What to build: Basic CRUD operations for semantic entries
  - Files: `backend/memory/semantic.py`
  - _Requirements: 3.1, 3.6_

- [ ] 4.11 Implement SemanticStore.get_startup_header() method
  - What to build: Assemble semantic_header string from HEADER_CATEGORIES for prompt injection
  - Files: `backend/memory/semantic.py`
  - _Requirements: 3.4, 3.5_

- [ ] 4.12 Implement SemanticStore.get_delta_since_version() method
  - What to build: Return all entries with version > since_version, ordered by version (for Torus device sync)
  - Files: `backend/memory/semantic.py`
  - _Requirements: 10.4_

- [ ] 4.13 Implement SemanticStore.get_max_version() method
  - What to build: Return highest version number for sync checkpoint
  - Files: `backend/memory/semantic.py`
  - _Requirements: 10.4_

- [ ] 4.14 Implement user display methods
  - What to build: update_user_display(), get_display_entries(), delete_display_entry()
  - Files: `backend/memory/semantic.py`
  - _Requirements: 3.5, 3.6_

- [ ] 4.15 Write tests for SemanticStore
  - What to build: Test CRUD, versioning, delta sync, user display
  - Files: `backend/memory/tests/test_semantic.py`
  - Run: `pytest backend/memory/tests/test_semantic.py -v`
  - _Requirements: 3.1, 3.2, 3.3, 3.5, 3.6, 10.3, 10.4_

---

## Task Group 5: Working Memory

- [ ] 5.1 Implement ContextManager zone structure
  - What to build: ZONES_ORDER constant, ANCHOR_ZONES set, _sessions dict storage
  - Files: `backend/memory/working.py`
  - _Requirements: 1.1, 1.2, 1.4_

- [ ] 5.2 Implement ContextManager.assemble_for_task() method
  - What to build: Initialize session zones with semantic_header, episodic_context, task_anchor; return render()
  - Files: `backend/memory/working.py`
  - _Requirements: 1.2, 1.4_

- [ ] 5.3 Implement ContextManager.append() method
  - What to build: Append content to zone; trigger compression if zone in ANCHOR_ZONES and usage > threshold
  - Files: `backend/memory/working.py`
  - _Requirements: 1.3, 1.5, 1.6_

- [ ] 5.4 Implement ContextManager.render() method
  - What to build: Join zones in ZONES_ORDER, filtering empty ones
  - Files: `backend/memory/working.py`
  - _Requirements: 1.4_

- [ ] 5.5 Implement ContextManager.clear_session() method
  - What to build: Remove session from _sessions dict
  - Files: `backend/memory/working.py`
  - _Requirements: 1.5_

- [ ] 5.6 Implement ContextManager._compress() method
  - What to build: Split working_history at 40% point; summarize oldest with ModelRole.COMPRESSION; keep newest verbatim
  - Files: `backend/memory/working.py`
  - _Requirements: 1.3, 1.6_

- [ ] 5.7 Implement ContextManager._usage_pct() method
  - What to build: Calculate token count vs context size using adapter
  - Files: `backend/memory/working.py`
  - _Requirements: 1.3, 1.6_

- [ ] 5.8 Write tests for ContextManager
  - What to build: Test zone assembly, compression at threshold, render ordering, session cleanup
  - Files: `backend/memory/tests/test_working.py`
  - Run: `pytest backend/memory/tests/test_working.py -v`
  - _Requirements: 1.1, 1.3, 1.4, 1.5, 1.6_

---

## Task Group 6: Memory Interface

- [ ] 6.1 Implement Episode dataclass
  - What to build: @dataclass with all fields from spec including node_id="local", origin="local"
  - Files: `backend/memory/interface.py` (Episode class)
  - _Requirements: 2.1, 2.6, 2.7, 10.1, 10.2_

- [ ] 6.2 Implement MemoryInterface.__init__() and composition
  - What to build: Initialize episodic, semantic, context, embed components with proper dependencies
  - Files: `backend/memory/interface.py`
  - _Requirements: 4.1, 4.2_

- [ ] 6.3 Implement MemoryInterface.get_task_context() method
  - What to build: Assemble semantic header + episodic context + working context for local tasks
  - Files: `backend/memory/interface.py`
  - _Requirements: 4.3_

- [ ] 6.4 Implement MemoryInterface.get_task_context_for_remote() method
  - What to build: Return ONLY task + relevant tool patterns — NO semantic header, NO personal data
  - Files: `backend/memory/interface.py`
  - _Requirements: 4.4, 4.6, 10.5_

- [ ] 6.5 Implement session management methods
  - What to build: append_to_session(), update_tool_state(), get_assembled_context(), clear_session()
  - Files: `backend/memory/interface.py`
  - _Requirements: 4.5, 4.6_

- [ ] 6.6 Implement MemoryInterface.store_episode() method
  - What to build: Delegate to episodic.store() with _score_outcome() calculation
  - Files: `backend/memory/interface.py`
  - _Requirements: 2.1, 2.2_

- [ ] 6.7 Implement preference management methods
  - What to build: update_preference(), get_user_profile_display(), forget_preference()
  - Files: `backend/memory/interface.py`
  - _Requirements: 3.1, 3.5, 3.6_

- [ ] 6.8 Implement _score_outcome() helper
  - What to build: Formula: 0.50 base + 0.30 confirmed + 0.10 not corrected + 0.10 fast (<5s)
  - Files: `backend/memory/interface.py`
  - _Requirements: 2.2_

- [ ] 6.9 Write tests for MemoryInterface
  - What to build: Test boundary enforcement, privacy isolation (get_task_context_for_remote excludes personal data), outcome scoring
  - Files: `backend/memory/tests/test_interface.py`
  - Run: `pytest backend/memory/tests/test_interface.py -v`
  - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 5.6_

---

## Task Group 7: Learning System

### Distillation Process

- [ ] 7.1 Implement DistillationProcess structure
  - What to build: Class with INTERVAL, IDLE_THRESHOLD, MIN_EPISODES constants; __init__ with memory_interface and adapter
  - Files: `backend/memory/distillation.py`
  - _Requirements: 7.1, 7.2_

- [ ] 7.2 Implement record_activity() and start() methods
  - What to build: Activity tracking for idle detection; asyncio background loop checking every 5 minutes
  - Files: `backend/memory/distillation.py`
  - _Requirements: 7.1, 7.6_

- [ ] 7.3 Implement _should_distill() method
  - What to build: Check idle_minutes >= 10 AND hours_since >= 4 AND enough episodes
  - Files: `backend/memory/distillation.py`
  - _Requirements: 7.1, 7.2_

- [ ] 7.4 Implement _run_distillation() method
  - What to build: Fetch recent episodes, prompt model for pattern extraction, store results in semantic memory with confidence=0.7
  - Files: `backend/memory/distillation.py`
  - _Requirements: 7.3, 7.4_

- [ ] 7.5 Implement EpisodicStore.get_recent_for_distillation() helper
  - What to build: Query episodes from last N hours, return if count >= MIN_EPISODES_FOR_DISTILL
  - Files: `backend/memory/episodic.py` (add method)
  - _Requirements: 7.2_

- [ ] 7.6 Add error handling for silent failures
  - What to build: Try/except in _run_distillation that logs but never raises
  - Files: `backend/memory/distillation.py`
  - _Requirements: 7.5_

- [ ] 7.7 Write tests for DistillationProcess
  - What to build: Test idle detection, should_distill logic, silent failure handling (mock time and model)
  - Files: `backend/memory/tests/test_distillation.py`
  - Run: `pytest backend/memory/tests/test_distillation.py -v`
  - _Requirements: 7.1, 7.2, 7.5_

### Skill Crystallisation

- [ ] 7.8 Implement SkillCrystalliser structure
  - What to build: Class with MIN_USES=5, MIN_SCORE=0.7 constants; __init__ with memory_interface and adapter
  - Files: `backend/memory/skills.py`
  - _Requirements: 8.1, 8.2_

- [ ] 7.9 Implement scan_and_crystallise() method
  - What to build: Call get_crystallisation_candidates(), generate skill name with model, store in semantic memory
  - Files: `backend/memory/skills.py`
  - _Requirements: 8.1, 8.2, 8.3, 8.4_

- [ ] 7.10 Implement EpisodicStore.get_crystallisation_candidates() helper
  - What to build: SQL query grouping by tool_sequence pattern, filtering count >= 5 AND avg_score >= 0.7
  - Files: `backend/memory/episodic.py` (add method)
  - _Requirements: 8.2_

- [ ] 7.11 Integrate SkillCrystalliser into DistillationProcess
  - What to build: Call scan_and_crystallise() after each distillation run
  - Files: `backend/memory/distillation.py`
  - _Requirements: 8.5_

- [ ] 7.12 Write tests for SkillCrystalliser
  - What to build: Test candidate detection, skill naming, storage with confidence=0.9
  - Files: `backend/memory/tests/test_skills.py`
  - Run: `pytest backend/memory/tests/test_skills.py -v`
  - _Requirements: 8.1, 8.2, 8.3, 8.4_

---

## Task Group 8: Integration

- [ ] 8.1 Add biometric key derivation helper
  - What to build: derive_biometric_key() function — platform biometric or fallback passphrase
  - Files: `backend/core/biometric.py` (new) or appropriate existing file
  - _Requirements: 6.6_

- [ ] 8.2 Create initialise_memory() startup function
  - What to build: Async function creating MemoryInterface, starting DistillationProcess, returning memory instance
  - Files: `backend/memory/__init__.py` or `backend/core/app_startup.py`
  - _Requirements: 9.1, 9.2_

- [ ] 8.3 Integrate memory initialization into main.py lifespan
  - What to build: Call initialise_memory() in lifespan startup, before AgentKernel starts
  - Files: `backend/main.py`
  - _Requirements: 9.1, 9.2_

- [ ] 8.4 Extend AgentKernel with MemoryInterface
  - What to build: Accept memory parameter in __init__, call memory methods in handle_message flow
  - Files: `backend/agent/agent_kernel.py`
  - _Requirements: 9.2, 9.4_

- [ ] 8.5 Add memory calls to task lifecycle
  - What to build: In handle_message: record_activity, get_task_context, store_episode, clear_session
  - Files: `backend/agent/agent_kernel.py`
  - _Requirements: 9.2, 9.4_

- [ ] 8.6 Extend IntentGate with memory lookup
  - What to build: Check episodic memory before generating new clarification questions
  - Files: `backend/core/intent_gate.py` (extend existing) or create new
  - _Requirements: 9.3_

- [ ] 8.7 Write integration tests
  - What to build: End-to-end test of task execution with episode storage and retrieval
  - Files: `backend/memory/tests/test_integration.py`
  - Run: `pytest backend/memory/tests/test_integration.py -v`
  - _Requirements: 9.1, 9.2, 9.3, 9.4_

---

## Task Group 9: Testing & Verification

- [ ] 9.1 Performance test: context assembly latency
  - What to build: Measure time for get_task_context() — must be <200ms
  - Files: `backend/memory/tests/test_performance.py`
  - Run: `pytest backend/memory/tests/test_performance.py -v`
  - _Requirements: 11.1, 11.6_

- [ ] 9.2 Performance test: startup time impact
  - What to build: Measure app startup with memory init — must add <3s
  - Files: `backend/memory/tests/test_startup.py`
  - Run: `pytest backend/memory/tests/test_startup.py -v`
  - _Requirements: 11.2, 11.6_

- [ ] 9.3 Security test: privacy boundary
  - What to build: Verify get_task_context_for_remote() returns no semantic_header, no preferences, no personal data
  - Files: `backend/memory/tests/test_privacy.py`
  - Run: `pytest backend/memory/tests/test_privacy.py -v`
  - _Requirements: 4.6, 10.5, 10.6_

- [ ] 9.4 Regression test: WebSocket compatibility
  - What to build: Verify all existing WebSocket message types work after memory integration
  - Files: `backend/memory/tests/test_regression.py`
  - Run: `pytest backend/memory/tests/test_regression.py -v`
  - _Requirements: 11.3_

- [ ] 9.5 User-facing test: preference display and forget
  - What to build: Test that get_user_profile_display() returns entries after interactions; test forget removes from display and header
  - Files: `backend/memory/tests/test_user_display.py`
  - Run: `pytest backend/memory/tests/test_user_display.py -v`
  - _Requirements: 3.5, 3.6, 11.7, 11.8_

- [ ] 9.6 Final acceptance criteria verification
  - What to build: Checklist test verifying all success criteria from spec Section 9
  - Files: `backend/memory/tests/test_acceptance.py`
  - Run: `pytest backend/memory/tests/test_acceptance.py -v`
  - _Requirements: All requirements

- [ ] 9.7 Test: data retention and pruning
  - What to build: Verify episodes older than retention_days with score < 0.3 are pruned; high-score episodes retained
  - Files: `backend/memory/tests/test_retention.py`
  - Run: `pytest backend/memory/tests/test_retention.py -v`
  - _Requirements: 12.1, 12.2, 12.3_

- [ ] 9.8 Test: duplicate detection
  - What to build: Verify similarity >0.95 updates existing episode; occurrence_count increments; score recalculated
  - Files: `backend/memory/tests/test_duplicates.py`
  - Run: `pytest backend/memory/tests/test_duplicates.py -v`
  - _Requirements: 13.1, 13.2, 13.3, 13.4_

- [ ] 9.9 Test: privacy audit logging
  - What to build: Verify get_task_context_for_remote() logs with content hash; rotation works; export API functional
  - Files: `backend/memory/tests/test_privacy_audit.py`
  - Run: `pytest backend/memory/tests/test_privacy_audit.py -v`
  - _Requirements: 14.1, 14.2, 14.3, 14.4_

- [ ] 9.10 Test: configuration management
  - What to build: Verify validation at startup; hot-reload for non-critical settings; integration with IRIS config
  - Files: `backend/memory/tests/test_config.py`
  - Run: `pytest backend/memory/tests/test_config.py -v`
  - _Requirements: 15.1, 15.2, 15.3, 15.4_

---

## Task Group 10: Additional Infrastructure

- [x] 10.1 Implement MemoryConfig dataclass
  - What to build: Centralized configuration with all tunable parameters, validation, defaults
  - Files: `backend/memory/config.py`
  - _Requirements: 15.1, 15.2, 15.4_
  - <!-- done: MemoryConfig dataclass with validation, defaults, and from_file() method -->

- [x] 10.2 Implement privacy audit logger
  - What to build: AuditLogger class for get_task_context_for_remote() calls with content hashing, rotation, export
  - Files: `backend/memory/audit.py`
  - _Requirements: 14.1, 14.2, 14.3, 14.4, 14.5_
  - <!-- done: AuditLogger with content hashing, automatic rotation, and privacy boundary logging -->

- [x] 10.3 Implement data retention manager
  - What to build: Background task for episode pruning based on retention policy; preserve high-value episodes
  - Files: `backend/memory/retention.py`
  - _Requirements: 12.1, 12.2, 12.3, 12.4, 12.5_
  - <!-- done: RetentionManager with configurable policies, high-value preservation, and background cleanup -->

- [x] 10.4 Implement episode deduplication logic
  - What to build: Similarity check before store; update existing if >0.95; occurrence_count tracking; score recalculation
  - Files: `backend/memory/episodic.py` (add methods)
  - _Requirements: 13.1, 13.2, 13.3, 13.4, 13.5_
  - <!-- done: _find_duplicate() with 0.95 threshold, store() updates existing episodes with content append -->

- [x] 10.5 Implement vector search fallback
  - What to build: Degrade gracefully to keyword/FTS search if sqlite-vec unavailable; feature flag detection
  - Files: `backend/memory/episodic.py` (modify retrieve_similar)
  - _Requirements: 6.3, 11.1_
  - <!-- done: numpy-based cosine similarity implementation as primary search (no sqlite-vec dependency) -->

- [x] 10.6 Implement data migration from conversation.json
  - What to build: On-first-run migration; version marker; background processing; preserve originals
  - Files: `backend/memory/migration.py`
  - _Requirements: 9.4_
  - <!-- done: DataMigration with version marker, background processing, conversation.json to episodes migration -->

- [x] 10.7 Create installation/setup documentation
  - What to build: docs/MEMORY_SETUP.md with platform-specific SQLCipher installation commands
  - Files: `docs/MEMORY_SETUP.md`
  - _Requirements: 6.1_
  - <!-- done: Comprehensive setup guide with Windows, macOS, and Linux SQLCipher installation instructions -->

---

## Task Group 11: Critical Bug Fixes (Post-Review)

### 11.1 Fix Duplicate Episode Dataclass ✅
- **Issue**: Episode defined in both interface.py and episodic.py causes import conflicts
- **Fix**: Remove definition from interface.py, import from episodic.py
- **Files**: `backend/memory/interface.py`
- _Requirements: Code Quality_
- **Status**: COMPLETE - Removed duplicate Episode class from interface.py

### 11.2 Add Memory Initialization to Startup ✅
- **Issue**: Memory system never initialized in main.py lifespan
- **Fix**: Add initialise_memory() call before AgentKernel initialization; start background processes
- **Files**: `backend/main.py`, `backend/memory/__init__.py` (add initialise_memory)
- _Requirements: 9.1, 9.2_
- **Status**: COMPLETE - Added initialise_memory() to lifespan() with proper wiring to AgentKernel

### 11.3 Implement Biometric Key Derivation ✅
- **Issue**: No key derivation implementation exists
- **Fix**: Create derive_biometric_key() with platform-specific biometric or passphrase fallback
- **Files**: `backend/core/biometric.py`
- _Requirements: 6.6_
- **Status**: COMPLETE - Created backend/core/biometric.py with PBKDF2 and platform biometric support

### 11.4 Add WebSocket Endpoints for Memory UI ✅
- **Issue**: Frontend cannot access memory preferences or trigger forget action
- **Fix**: Add WebSocket message handlers for memory/get_preferences, memory/forget_preference, memory/get_stats
- **Files**: `backend/main.py` or `backend/iris_gateway.py`
- _Requirements: 3.5, 3.6, 9.3_
- **Status**: COMPLETE - Added handle_memory_message() with 3 memory endpoints

### 11.5 Integrate Memory with AgentKernel ✅
- **Issue**: AgentKernel never calls memory methods
- **Fix**: Add _memory_interface to AgentKernel; call get_task_context before inference, store_episode after task
- **Files**: `backend/agent/agent_kernel.py`
- _Requirements: 9.2, 9.4_
- **Status**: COMPLETE - Added set_memory_interface(), _get_memory_context(), _store_task_episode()

### 11.6 Implement Vector Search ✅
- **Issue**: retrieve_similar() uses timestamp sorting instead of semantic similarity
- **Fix**: Integrate sqlite-vec for cosine similarity or implement numpy-based similarity
- **Files**: `backend/memory/episodic.py`
- _Requirements: 2.3, 2.4, 5.1_
- <!-- done: Added _cosine_similarity() method, updated retrieve_similar() and retrieve_failures() to use numpy-based cosine similarity search on 384-dim embeddings -->

### 11.7 Add Episode Deduplication ✅
- **Issue**: No similarity check before storing episodes
- **Fix**: Check embedding similarity >0.95; update existing episode if found; track occurrence_count
- **Files**: `backend/memory/episodic.py`
- _Requirements: 13.1, 13.2, 13.3_
- <!-- done: Added _find_duplicate() method with DEDUP_THRESHOLD=0.95, updated store() to update existing episodes when duplicate found, appends new content to existing episode -->

### 11.8 Fix Context Manager Adapter Interface ✅
- **Issue**: ModelRole.COMPRESSION import may fail; adapter role handling uncertain
- **Fix**: Add try/except with fallback to simple truncation; verify adapter interface
- **Files**: `backend/memory/working.py`
- _Requirements: 1.3, 1.6_
- <!-- done: Added graceful fallback in _compress() method with try/except around ModelRole.COMPRESSION import; falls back to simple truncation when adapter unavailable -->

---

## Summary

| Group | Tasks | Focus |
|-------|-------|-------|
| 1 | 2 | Project setup, dependencies |
| 2 | 2 | Database encryption layer |
| 3 | 2 | Embedding service singleton |
| 4 | 8 | Episodic & semantic storage |
| 5 | 4 | Working memory zones |
| 6 | 4 | MemoryInterface boundary |
| 7 | 7 | Distillation & skills |
| 8 | 5 | Integration with existing code |
| 9 | 10 | Testing & verification |
| 10 | 7 | Config, audit, retention, migration |
| 11 | 8 | Critical bug fixes (post-review) |
| **Total** | **59** | |

**Total Acceptance Criteria Coverage:** 15 requirements × 50+ criteria = full coverage via _Requirements: X.Y_ references throughout.

---

## Execution Order Recommendation

1. Groups 1-3 (Setup, DB, Embedding) — foundation layers, no dependencies
2. Group 10.1 (Config) — needed by all subsequent groups
3. Groups 4-5 (Storage, Working) — depend on embedding and DB
4. Group 6 (Interface) — depends on storage and working
5. Group 10.4 (Deduplication) — extends episodic storage
6. Group 10.5 (Fallback) — extends retrieval
7. Group 7 (Learning) — depends on interface and storage
8. Group 8 (Integration) — depends on all above
9. Group 10.6 (Migration) — runs after integration
10. Group 10.2-10.3 (Audit, Retention) — background services
11. Groups 9-10.7 (Testing, Docs) — verify everything

Parallel work possible:
- Groups 1-3 and 10.1 can be done in parallel
- EpisodicStore and SemanticStore (4.1-4.7, 4.8-4.15) can be parallel
- Distillation and Skills (7.1-7.7, 7.8-7.12) can be parallel after storage complete
- Testing tasks (Group 9) can be written in parallel with implementation
