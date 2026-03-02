# Requirements: IRIS Memory Foundation

## Introduction

This specification defines the memory foundation system for IRIS that enables personalized, contextual responses by remembering user preferences and past interactions. The system implements a three-tier memory architecture (Working, Episodic, Semantic) designed to be Torus-ready from day one — capable of scaling from single-user operation to sovereign P2P swarm participation without architectural refactoring.

Success means: IRIS remembers what users prefer, learns from past interactions, and applies that knowledge to provide increasingly personalized assistance across sessions, all while maintaining privacy and preparing for future distributed operation.

---

## Requirements

### Requirement 1: Working Memory (Session Context)

**User Story:** As a user, I want IRIS to maintain context throughout our conversation, so that I don't have to repeat information within a single session.

#### Acceptance Criteria

1. WHEN a session starts THE SYSTEM SHALL create an isolated working memory instance for that session
2. WHEN a user sends a message THE SYSTEM SHALL store the conversation turn in working memory
3. WHEN the working memory reaches 80% of its capacity THE SYSTEM SHALL compress the oldest 40% of history using a compression model role
4. WHEN context is requested for a task THE SYSTEM SHALL assemble: semantic_header + episodic_injection + task_anchor + active_tool_state + working_history in that order
5. WHEN a session ends THE SYSTEM SHALL clear working memory for that session_id
6. THE SYSTEM SHALL NOT allow working memory to exceed configured token limits without compression

---

### Requirement 2: Episodic Memory (Persistent Task Storage)

**User Story:** As a user, I want IRIS to remember what tasks I've completed and how they turned out, so that it can reference relevant past experiences when helping me with similar tasks.

#### Acceptance Criteria

1. WHEN a task completes THE SYSTEM SHALL persist an episode record containing: session_id, task_summary, full_content, tool_sequence, outcome_type, duration_ms, tokens_used, model_id, source_channel, node_id, origin, and embedding
2. WHEN storing an episode THE SYSTEM SHALL compute an outcome_score (0.0-1.0) using the formula: 0.50 base for success + 0.30 for user_confirmed + 0.10 for not user_corrected + 0.10 for duration < 5s
3. WHEN retrieving similar episodes THE SYSTEM SHALL use vector similarity search with cosine distance on all-MiniLM-L6-v2 embeddings
4. WHEN assembling task context THE SYSTEM SHALL inject up to 3 similar successful episodes (score >= 0.6) and up to 2 failure episodes as warnings
5. THE SYSTEM SHALL encrypt all episodic data using AES-256 via SQLCipher
6. EVERY episode record SHALL include node_id="local" (Torus-ready field for future Dilithium3 pubkey)
7. EVERY episode record SHALL include origin="local" (Torus-ready field distinguishing local vs torus_task)

---

### Requirement 3: Semantic Memory (User Model)

**User Story:** As a user, I want IRIS to learn my preferences and working style over time, so that it can adapt to me personally rather than treating me generically.

#### Acceptance Criteria

1. WHEN a preference is explicitly set by the user THE SYSTEM SHALL store it in semantic memory under category "user_preferences" with confidence=1.0 and source="user_set"
2. WHEN the distillation process extracts patterns THE SYSTEM SHALL store them in semantic memory with confidence < 1.0 and source="distillation"
3. WHEN a semantic entry is updated THE SYSTEM SHALL increment its version integer (critical for Torus delta-sync)
4. WHEN assembling the startup context THE SYSTEM SHALL include semantic entries from categories: user_preferences, cognitive_model, domain_knowledge, named_skills, failure_patterns
5. THE SYSTEM SHALL provide a user-facing display of learned preferences that users can view and edit
6. WHEN a user chooses to "forget" a preference THE SYSTEM SHALL remove it from both semantic_entries and user_display_memory tables
7. EVERY semantic entry SHALL carry a version integer that increments on every update

---

### Requirement 4: Memory Interface (Single Access Boundary)

**User Story:** As a developer, I want a single, well-defined API for all memory operations, so that the system remains maintainable and future storage backend changes don't require widespread code modifications.

#### Acceptance Criteria

1. THE SYSTEM SHALL provide a MemoryInterface class as the ONLY access point for memory operations
2. WHEN any component needs memory access THE SYSTEM SHALL route through MemoryInterface — direct database access is prohibited
3. WHEN task context is needed for local execution THE SYSTEM SHALL call MemoryInterface.get_task_context(task, session_id)
4. WHEN task context is needed for remote execution THE SYSTEM SHALL call MemoryInterface.get_task_context_for_remote(task_summary, tool_sequence) which SHALL NOT include personal profile data
5. THE SYSTEM SHALL expose methods: append_to_session(), update_tool_state(), get_assembled_context(), clear_session(), store_episode(), update_preference(), get_user_profile_display(), forget_preference()
6. THE SYSTEM SHALL enforce that get_task_context_for_remote() returns only task-scoped data — no semantic_header, no user preferences, no cognitive model, no domain knowledge

---

### Requirement 5: Embedding Service

**User Story:** As a system, I want efficient vector embeddings for semantic search, so that IRIS can find relevant past experiences quickly without loading the model repeatedly.

#### Acceptance Criteria

1. THE SYSTEM SHALL provide EmbeddingService as a singleton class
2. WHEN the embedding service is first called THE SYSTEM SHALL lazily load the all-MiniLM-L6-v2 model (384-dim, ~80MB)
3. THE SYSTEM SHALL provide encode(text) -> list[float] for single text encoding
4. THE SYSTEM SHALL provide encode_batch(texts) -> list[list[float]] for batch encoding
5. THE SYSTEM SHALL NOT allow direct SentenceTransformer instantiation anywhere outside EmbeddingService
6. THE SYSTEM SHALL handle model loading with thread-safe double-checked locking

---

### Requirement 6: Database Layer

**User Story:** As a user, I want my personal data protected with encryption, so that even if someone accesses the database files, they cannot read my conversation history and preferences.

#### Acceptance Criteria

1. THE SYSTEM SHALL provide open_encrypted_memory(db_path, biometric_key) function that returns a SQLCipher connection
2. WHEN opening the database THE SYSTEM SHALL configure: PRAGMA key, cipher_page_size=4096, kdf_iter=64000, journal_mode=WAL, foreign_keys=ON
3. THE SYSTEM SHALL create tables on first access: episodes, semantic_entries, user_display_memory with Torus-ready schema
4. THE SYSTEM SHALL create indexes: idx_ep_vec (vector), idx_ep_fail (partial on outcome_type='failure'), idx_ep_score, idx_ep_node, idx_ep_origin, idx_sem_version, idx_sem_category
5. THE SYSTEM SHALL NOT allow any unencrypted SQLite connections for memory data
6. THE SYSTEM SHALL derive the biometric_key from platform biometrics or fallback passphrase at app startup

---

### Requirement 7: Distillation Process (Background Learning)

**User Story:** As a user, I want IRIS to automatically learn patterns from my interactions over time, so that it gets better at helping me without requiring manual configuration.

#### Acceptance Criteria

1. THE SYSTEM SHALL run a DistillationProcess as a background asyncio task every 4 hours when the system has been idle for at least 10 minutes
2. WHEN distillation runs THE SYSTEM SHALL fetch recent episodes (last 8 hours) requiring at least MIN_EPISODES_FOR_DISTILL (5) episodes
3. WHEN processing episodes THE SYSTEM SHALL use the model to extract patterns across categories: user_preferences, cognitive_model, domain_knowledge, failure_patterns
4. WHEN patterns are extracted THE SYSTEM SHALL store them in semantic memory with confidence=0.7 and source="distillation"
5. IF distillation fails THE SYSTEM SHALL fail silently without blocking user interactions or raising errors
6. THE SYSTEM SHALL record activity on every user interaction to reset the idle timer for distillation

---

### Requirement 8: Skill Crystallization

**User Story:** As a user, I want IRIS to recognize when I repeatedly use certain workflows successfully, so that it can offer them as reusable shortcuts.

#### Acceptance Criteria

1. THE SYSTEM SHALL provide SkillCrystalliser that scans episodic memory for high-performing tool sequences
2. WHEN scanning THE SYSTEM SHALL identify tool sequences used >= CRYSTALLISATION_MIN_USES (5) times with average score >= CRYSTALLISATION_MIN_SCORE (0.7)
3. WHEN a candidate is identified THE SYSTEM SHALL use the model to generate a descriptive skill name (3-5 words)
4. WHEN a skill is crystallized THE SYSTEM SHALL store it in semantic memory under category "named_skills" with confidence=0.9 and source="crystallisation"
5. THE SYSTEM SHALL call scan_and_crystallise() from the DistillationProcess after each distillation run

---

### Requirement 9: Integration Points

**User Story:** As a developer, I want clear integration points with the existing IRIS architecture, so that the memory system enhances rather than disrupts current functionality.

#### Acceptance Criteria

1. THE SYSTEM SHALL initialize MemoryInterface during app startup before AgentKernel processes the first task
2. WHEN processing a task THE SYSTEM SHALL: record_activity(), check intent confidence, assemble context, run inference, store episode, clear working memory
3. THE SYSTEM SHALL extend the existing IntentGate to check episodic memory before generating new clarification questions
4. THE SYSTEM SHALL integrate with the existing ConversationMemory in backend/agent/memory.py rather than replacing it
5. THE SYSTEM SHALL add dependencies to requirements.txt: sqlcipher3>=0.5.0, sqlite-vec>=0.1.0, sentence-transformers>=2.7.0

---

### Requirement 10: Torus-Ready Constraints

**User Story:** As a system architect, I want the memory system to be future-proof for Torus network integration, so that we don't need to refactor when swarm capabilities arrive.

#### Acceptance Criteria

1. EVERY episode record SHALL include node_id field (set to "local" now, Dilithium3 pubkey at Phase 6)
2. EVERY episode record SHALL include origin field distinguishing 'local' vs 'torus_task'
3. EVERY semantic entry SHALL include version integer for delta-sync across devices
4. THE SYSTEM SHALL provide get_delta_since_version(since_version) for device synchronization
5. THE SYSTEM SHALL provide get_task_context_for_remote() that returns no personal data — this SHALL be the only context method callable with remote TaskMessage
6. THE SYSTEM SHALL ensure memory.db encryption key can derive from Torus seed phrase at Phase 6
7. THE SYSTEM SHALL NOT require any schema changes for Phase 4-6 Torus integration

---

### Requirement 11: Performance & Non-Regression

**User Story:** As a user, I want IRIS to remain responsive even with memory features enabled, so that I don't experience noticeable delays.

#### Acceptance Criteria

1. THE SYSTEM SHALL ensure agent response latency increases by no more than 200ms due to embedding + retrieval overhead
2. THE SYSTEM SHALL ensure app startup time increases by no more than 3 seconds (embedding model loads lazily)
3. THE SYSTEM SHALL ensure all existing WebSocket message types continue to work after memory integration
4. THE SYSTEM SHALL use WAL mode for SQLite to enable better concurrent write performance
5. THE SYSTEM SHALL compress working memory automatically at 80% threshold to prevent context overflow
6. THE SYSTEM SHALL provide memory health stats via get_stats() for monitoring and UI display

---

### Requirement 12: Data Retention & Maintenance

**User Story:** As a user, I want IRIS to manage its memory automatically, so that storage doesn't grow unbounded and old irrelevant memories are pruned.

#### Acceptance Criteria

1. THE SYSTEM SHALL implement configurable retention policy for episodes (default: 90 days)
2. WHEN retention period expires THE SYSTEM SHALL automatically prune episodes with outcome_score < 0.3
3. THE SYSTEM SHALL retain high-value episodes (score >= 0.8) indefinitely regardless of age
4. WHEN pruning occurs THE SYSTEM SHALL log the number of episodes removed
5. THE SYSTEM SHALL provide manual "compact memory" option for immediate cleanup

---

### Requirement 13: Duplicate Detection

**User Story:** As a user, I want IRIS to avoid storing the same task multiple times, so that my memory stays clean and search results aren't cluttered.

#### Acceptance Criteria

1. WHEN storing an episode THE SYSTEM SHALL check for recent similar episodes (last 24 hours)
2. IF task_summary embedding similarity > 0.95 to existing episode THE SYSTEM SHALL update existing episode rather than create duplicate
3. WHEN updating an existing episode THE SYSTEM SHALL increment a "occurrence_count" field
4. THE SYSTEM SHALL recalculate outcome_score as weighted average of all occurrences
5. IF similarity is between 0.80-0.95 THE SYSTEM SHALL store as new episode (variant)

---

### Requirement 14: Privacy Audit Trail

**User Story:** As a privacy-conscious user, I want IRIS to maintain an audit log of when personal data is accessed externally, so I can verify my data isn't being misused.

#### Acceptance Criteria

1. WHEN get_task_context_for_remote() is called THE SYSTEM SHALL log: timestamp, requester_hash, content_hash, size_bytes
2. THE SYSTEM SHALL NOT log actual content (only hash for verification)
3. THE SYSTEM SHALL rotate audit logs every 30 days (configurable)
4. THE SYSTEM SHALL provide API for user to export audit trail
5. WHEN audit log reaches size limit THE SYSTEM SHALL archive and start new log (never silently delete)

---

### Requirement 15: Configuration Management

**User Story:** As a system administrator, I want memory system settings to be centralized and validated, so that configuration is maintainable and errors are caught early.

#### Acceptance Criteria

1. THE SYSTEM SHALL provide MemoryConfig dataclass with all tunable parameters and sensible defaults
2. THE SYSTEM SHALL validate configuration at startup and raise clear errors for invalid values
3. THE SYSTEM SHALL support hot-reload of non-critical settings (retention_days, compression_threshold)
4. THE SYSTEM SHALL integrate with existing IRIS config system (config.yaml / environment variables)
5. THE SYSTEM SHALL provide get_memory_config() method returning current effective configuration

---

## Summary

| Requirement | Key Deliverable | Success Criteria |
|-------------|-----------------|------------------|
| 1 | Working Memory | Context compression at 80%, ordered zone assembly |
| 2 | Episodic Memory | Encrypted SQLite + sqlite-vec, outcome scoring, failure warnings |
| 3 | Semantic Memory | Versioned entries, user display, forget capability |
| 4 | MemoryInterface | Single access boundary, privacy-safe remote context |
| 5 | EmbeddingService | Singleton all-MiniLM-L6-v2, lazy loading |
| 6 | Database Layer | AES-256 SQLCipher, WAL mode, Torus schema |
| 7 | Distillation | 4h idle daemon, silent failure, pattern extraction |
| 8 | Skill Crystallization | 5+ uses @ 0.7+ score, named skill generation |
| 9 | Integration | Startup init, task lifecycle hooks, IntentGate extension |
| 10 | Torus-Ready | node_id, version, delta-sync, privacy boundary |
| 11 | Performance | <200ms latency, <3s startup, WAL mode |
| 12 | Data Retention | 90-day policy, auto-prune low scores, manual compact |
| 13 | Duplicate Detection | Similarity >0.95 updates existing, occurrence counting |
| 14 | Privacy Audit | Content-hash logging, rotation, export API |
| 15 | Configuration | Centralized config, validation, hot-reload |
