"""
Handles session backup, migration, and persistence operations.
"""
import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional, List
import asyncio
import aiofiles

from .session_types import Session, SessionType
from .state_isolation import IsolatedStateManager

class SessionBackupManager:
    """Manages session backup and migration operations."""
    
    def __init__(self, backup_dir: Path = None):
        self.backup_dir = backup_dir or Path("backups/sessions")
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        self.migration_dir = self.backup_dir / "migrations"
        self.migration_dir.mkdir(exist_ok=True)
    
    async def create_backup(self, session: Session, state_manager: IsolatedStateManager) -> str:
        """Create a backup of a session."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_name = f"{session.session_id}_{session.session_type.name}_{timestamp}"
        backup_path = self.backup_dir / backup_name
        
        try:
            # Create backup directory
            backup_path.mkdir(parents=True, exist_ok=True)
            
            # Save session metadata
            metadata = {
                "session_id": session.session_id,
                "session_type": session.session_type.name,
                "created_at": datetime.now().isoformat(),
                "backup_version": "1.0"
            }
            
            async with aiofiles.open(backup_path / "metadata.json", 'w') as f:
                await f.write(json.dumps(metadata, indent=2))
            
            # Save session state
            state_data = await state_manager.get_state()
            async with aiofiles.open(backup_path / "state.json", 'w') as f:
                await f.write(json.dumps(state_data.dict() if hasattr(state_data, 'dict') else state_data, indent=2))
            
            return backup_name
            
        except Exception as e:
            # Clean up partial backup on failure
            if backup_path.exists():
                shutil.rmtree(backup_path)
            raise RuntimeError(f"Failed to create backup: {e}")
    
    async def restore_backup(self, backup_name: str, new_session_id: str) -> Dict[str, Any]:
        """Restore a session from backup."""
        backup_path = self.backup_dir / backup_name
        
        if not backup_path.exists():
            raise FileNotFoundError(f"Backup {backup_name} not found")
        
        try:
            # Load metadata
            async with aiofiles.open(backup_path / "metadata.json", 'r') as f:
                metadata = json.loads(await f.read())
            
            # Load state
            async with aiofiles.open(backup_path / "state.json", 'r') as f:
                state_data = json.loads(await f.read())
            
            # Update session ID for the restored session
            metadata["original_session_id"] = metadata["session_id"]
            metadata["session_id"] = new_session_id
            metadata["restored_at"] = datetime.now().isoformat()
            
            return {
                "metadata": metadata,
                "state": state_data
            }
            
        except Exception as e:
            raise RuntimeError(f"Failed to restore backup: {e}")
    
    async def list_backups(self, session_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """List available backups."""
        backups = []
        
        for backup_path in self.backup_dir.iterdir():
            if backup_path.is_dir() and (session_id is None or backup_path.name.startswith(session_id)):
                try:
                    metadata_path = backup_path / "metadata.json"
                    if metadata_path.exists():
                        async with aiofiles.open(metadata_path, 'r') as f:
                            metadata = json.loads(await f.read())
                        backups.append(metadata)
                except Exception:
                    continue
        
        # Sort by creation time (newest first)
        backups.sort(key=lambda x: x.get("created_at", ""), reverse=True)
        return backups
    
    async def migrate_session(self, old_session: Session, new_session_type: SessionType, 
                            state_manager: IsolatedStateManager) -> Session:
        """Migrate a session to a new type."""
        migration_id = f"{old_session.session_id}_to_{new_session_type.name}"
        migration_path = self.migration_dir / migration_id
        
        try:
            # Create migration backup
            backup_name = await self.create_backup(old_session, state_manager)
            
            # Create migration record
            migration_record = {
                "migration_id": migration_id,
                "old_session_id": old_session.session_id,
                "old_session_type": old_session.session_type.name,
                "new_session_type": new_session_type.name,
                "backup_name": backup_name,
                "migrated_at": datetime.now().isoformat(),
                "status": "in_progress"
            }
            
            migration_path.mkdir(parents=True, exist_ok=True)
            async with aiofiles.open(migration_path / "migration.json", 'w') as f:
                await f.write(json.dumps(migration_record, indent=2))
            
            # Create new session
            new_session = Session(
                session_id=old_session.session_id,  # Keep same ID
                session_type=new_session_type
            )
            
            # Update migration record
            migration_record["status"] = "completed"
            migration_record["completed_at"] = datetime.now().isoformat()
            
            async with aiofiles.open(migration_path / "migration.json", 'w') as f:
                await f.write(json.dumps(migration_record, indent=2))
            
            return new_session
            
        except Exception as e:
            # Update migration record with failure
            if migration_path.exists():
                try:
                    migration_record["status"] = "failed"
                    migration_record["error"] = str(e)
                    async with aiofiles.open(migration_path / "migration.json", 'w') as f:
                        await f.write(json.dumps(migration_record, indent=2))
                except:
                    pass
            
            raise RuntimeError(f"Failed to migrate session: {e}")
    
    async def cleanup_old_backups(self, days_to_keep: int = 30) -> int:
        """Clean up backups older than specified days."""
        cutoff_date = datetime.now() - timedelta(days=days_to_keep)
        cleaned_count = 0
        
        for backup_path in self.backup_dir.iterdir():
            if backup_path.is_dir():
                try:
                    # Get creation time from directory stats
                    stat = backup_path.stat()
                    creation_time = datetime.fromtimestamp(stat.st_ctime)
                    
                    if creation_time < cutoff_date:
                        shutil.rmtree(backup_path)
                        cleaned_count += 1
                        
                except Exception:
                    continue
        
        return cleaned_count
