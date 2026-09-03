"""
Baseline characterization for the config migration's local-provider endpoint
(Wave 0, T0d — pins T3 / REQ-8).

``InferenceConfig.migrate_flat_to_collection()`` (backend/iris_config.py,
~lines 374-383) builds a namespaced ``LOCAL_OPENAI`` ``ProviderEntry`` for a
legacy ``local_model_id`` and hardcodes its endpoint to
``http://127.0.0.1:8081``. That port has never matched
``LocalModelManager.PORT`` (8082) — the migrated entry points at the vision
server's port, not the local model server's port. This is a live bug, not a
theoretical one: it runs on every config load that still has flat fields.

T3 (REQ-8) landed: ``migrate_flat_to_collection()`` now derives the endpoint
from ``LocalModelManager.PORT`` (imported lazily inside
``_local_model_endpoint()``) instead of hardcoding ``8081``. These tests now
assert the NEW (fixed) behavior — the migrated endpoint agrees with
``LocalModelManager.PORT``.

No disk I/O: migration is driven purely through
``InferenceConfig.from_dict()`` (the sole production caller of
``migrate_flat_to_collection()``), which is pure in-memory construction. No
network, no GPU, no real config file is touched.
"""

import pytest

from backend.iris_config import InferenceConfig
from backend.agent.local_model_manager import LocalModelManager


LOCAL_MODEL_ID = "qwen3-9b-q4_k_m.gguf"


def _migrated_local_entry() -> "object":
    """Drive the migration in isolation via the real production entry point.

    ``InferenceConfig.from_dict()`` is the only caller of
    ``migrate_flat_to_collection()`` in production code (see
    ``InferenceConfig.from_dict``, which calls it unconditionally after
    construction). Passing a dict with a legacy flat ``local_model_id`` and
    no ``providers``/``config_version`` reproduces exactly the state a
    pre-migration config on disk would have, without touching any file.
    """
    cfg = InferenceConfig.from_dict({"local_model_id": LOCAL_MODEL_ID})
    ns_id = f"local:{LOCAL_MODEL_ID.rsplit('.', 1)[0]}"
    return cfg, cfg.providers[ns_id]


class TestLocalProviderMigrationBaseline:
    def test_migration_runs_and_bumps_config_version(self):
        """Sanity: the migration actually fires for a legacy flat config."""
        cfg, entry = _migrated_local_entry()
        assert cfg.config_version == 2
        assert entry is not None

    def test_migrated_local_entry_endpoint_derives_from_local_model_manager_port(self):
        """
        characterization: T3 (REQ-8) changed this to derive the endpoint from
        LocalModelManager.PORT instead of hardcoding 8081.

        Pinning the derivation so a regression back to a literal is visible
        as a diff here, not a silent behavior change.
        """
        _, entry = _migrated_local_entry()
        assert entry.endpoint == f"http://127.0.0.1:{LocalModelManager.PORT}"

    def test_migrated_endpoint_agrees_with_local_model_manager_port(self):
        """
        The fix, stated as a contract: the migrated endpoint's port and
        LocalModelManager.PORT (the actual local-model server port) now
        match. A migrated local provider binding points at the right server.
        """
        _, entry = _migrated_local_entry()
        migrated_port = int(entry.endpoint.rsplit(":", 1)[-1])
        assert migrated_port == LocalModelManager.PORT
        assert LocalModelManager.PORT == 8082  # documents today's real port

    def test_migrated_entry_shape_besides_endpoint(self):
        """
        Pin the rest of the entry's shape so T3 can be shown to have changed
        ONLY the endpoint field, nothing else about the migrated record.
        """
        _, entry = _migrated_local_entry()
        assert entry.id == "local:qwen3-9b-q4_k_m"
        assert entry.label == "Local Model"
        assert entry.kind == "LOCAL_OPENAI"
        assert entry.model == LOCAL_MODEL_ID

    def test_no_local_entry_when_local_model_id_absent(self):
        """Baseline: without a legacy local_model_id, no local: entry is created."""
        cfg = InferenceConfig.from_dict({})
        assert not any(k.startswith("local:") for k in cfg.providers)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
