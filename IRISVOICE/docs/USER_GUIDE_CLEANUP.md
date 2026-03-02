# IRISVOICE Cleanup System Guide

## Overview

The IRISVOICE cleanup system helps you identify and remove unused files and dependencies to:
- Free up disk space
- Reduce deployment size
- Keep the codebase clean
- Improve performance

## What Gets Analyzed

### Unused Files

The cleanup system scans for:

1. **Model Files**: Downloaded AI models not referenced in active code
2. **Wake Word Files**: `.ppn` files not selectable through the UI
3. **Configuration Files**: Config files not loaded by any component
4. **Other Files**: Temporary files, caches, and orphaned data

### Unused Dependencies

The cleanup system scans for:

1. **Python Packages**: Dependencies in `requirements.txt` not imported in any module
2. **Installation Size**: Calculates disk space used by each dependency
3. **Import Analysis**: Uses AST parsing to find actual imports

## Using the Cleanup System

### Generating a Cleanup Report (Dry-Run)

**WheelView:**
1. Navigate to **System** category
2. Select **Cleanup** mini-node
3. Click **Generate Report** button
4. Review the report in the UI

**DarkGlassDashboard:**
1. Open **System** settings tab
2. Scroll to **Cleanup** section
3. Click **Generate Report** button
4. Review the report in the panel

**Via WebSocket:**
```json
{
  "type": "get_cleanup_report",
  "payload": {
    "dry_run": true
  }
}
```

### Understanding the Report

The cleanup report includes:

**Unused Files:**
- Path to file
- Size in bytes (human-readable)
- Last accessed date
- Reason for being flagged as unused
- Category (model, wake_word, config, other)

**Unused Dependencies:**
- Package name
- Version
- Installation size
- Reason for being flagged as unused

**Summary:**
- Total size of unused items
- Total number of unused files
- Total number of unused dependencies
- Warnings for large items (>100MB)

**Example Report:**
```json
{
  "unused_files": [
    {
      "path": "models/old_model.bin",
      "size_bytes": 8589934592,
      "last_accessed": "2024-01-15T10:30:00Z",
      "reason": "Not referenced in active code",
      "category": "model"
    }
  ],
  "unused_dependencies": [
    {
      "name": "unused-package",
      "version": "1.0.0",
      "install_size_bytes": 1048576,
      "reason": "Not imported in any module"
    }
  ],
  "total_size_bytes": 8590983168,
  "total_files": 1,
  "total_dependencies": 1,
  "warnings": ["Large unused model file detected (8.0 GB)"]
}
```

### Executing Cleanup

**Important:** Always review the report before executing cleanup!

**WheelView:**
1. Generate a cleanup report first
2. Review the items to be removed
3. Select items to remove (or select all)
4. Click **Execute Cleanup** button
5. Confirm the action
6. Wait for completion

**DarkGlassDashboard:**
1. Generate a cleanup report first
2. Review the items in the list
3. Check boxes for items to remove
4. Click **Execute Cleanup** button
5. Confirm the action
6. Wait for completion

**Via WebSocket:**
```json
{
  "type": "execute_cleanup",
  "payload": {
    "items": [
      "models/old_model.bin",
      "wake_words/old_wake_word.ppn"
    ],
    "backup": true
  }
}
```

### Cleanup Result

After cleanup execution, you'll receive:

**Removed Files:**
- List of successfully removed files
- Paths of deleted items

**Removed Dependencies:**
- List of uninstalled packages
- Package names and versions

**Freed Space:**
- Total bytes freed
- Human-readable size (GB, MB, KB)

**Backup Path:**
- Location of backup archive (if backup was enabled)
- Timestamp of backup

**Errors:**
- List of any errors encountered
- Items that couldn't be removed

**Example Result:**
```json
{
  "removed_files": ["models/old_model.bin"],
  "removed_dependencies": ["unused-package"],
  "freed_bytes": 8590983168,
  "backup_path": "backend/backups/cleanup_2024-02-05_19-30-00.zip",
  "errors": []
}
```

## Backup System

### Automatic Backups

By default, the cleanup system creates a backup before removing any items:

**Backup Contents:**
- All files to be removed
- Metadata about removed dependencies
- Timestamp and cleanup report

**Backup Location:**
- `backend/backups/cleanup_{timestamp}.zip`
- Example: `backend/backups/cleanup_2024-02-05_19-30-00.zip`

**Backup Retention:**
- Backups are kept indefinitely
- Manually delete old backups if needed
- Consider archiving backups periodically

### Restoring from Backup

To restore removed items:

1. Locate the backup file in `backend/backups/`
2. Extract the ZIP archive
3. Copy files back to their original locations
4. Reinstall dependencies from backup metadata
5. Restart the application

**Manual Restoration:**
```bash
# Extract backup
unzip backend/backups/cleanup_2024-02-05_19-30-00.zip -d restore/

# Copy files back
cp restore/models/old_model.bin models/

# Reinstall dependencies (if needed)
pip install unused-package==1.0.0
```

### Disabling Backups

You can disable backups for faster cleanup (not recommended):

```json
{
  "type": "execute_cleanup",
  "payload": {
    "items": ["models/old_model.bin"],
    "backup": false
  }
}
```

**Warning:** Disabling backups means removed items cannot be easily restored!

## Safety Features

### Dry-Run Mode

The default mode is dry-run, which:
- Analyzes files and dependencies
- Generates a report
- Does NOT remove anything
- Allows you to review before executing

### Confirmation Required

Cleanup execution requires explicit confirmation:
- Review the report first
- Select specific items to remove
- Confirm the action
- Cannot be undone (unless backup exists)

### Backup Creation

Automatic backups provide safety:
- All removed items are backed up
- Backups include metadata
- Easy restoration if needed

### Error Handling

The cleanup system handles errors gracefully:
- Continues processing if one item fails
- Reports all errors in the result
- Doesn't leave system in broken state

## What NOT to Remove

The cleanup system is conservative and won't flag:

**Active Models:**
- Models referenced in code
- Models configured in settings
- Models currently loaded

**Active Wake Words:**
- Wake words selectable in UI
- Currently selected wake word
- Platform-specific wake words

**Active Dependencies:**
- Packages imported in any module
- Transitive dependencies
- System packages

**Configuration Files:**
- Files loaded by components
- Active session data
- User settings

## Best Practices

1. **Review Before Removing**: Always generate and review the report first
2. **Keep Backups Enabled**: Don't disable backups unless absolutely necessary
3. **Test After Cleanup**: Verify the application works after cleanup
4. **Archive Old Backups**: Periodically move old backups to archive storage
5. **Run Periodically**: Run cleanup analysis monthly to keep system clean
6. **Check Warnings**: Pay attention to warnings about large files

## Troubleshooting

### Cleanup Report Shows Nothing

**Possible Causes:**
- All files are actively used
- All dependencies are imported
- System is already clean

**Solutions:**
- This is good! Your system is clean
- No action needed

### Cleanup Fails with Errors

**Possible Causes:**
- File permissions issues
- Files in use by another process
- Disk space issues

**Solutions:**
1. Check file permissions
2. Close other applications
3. Ensure sufficient disk space
4. Review error messages in result
5. Try removing items individually

### Backup Creation Fails

**Possible Causes:**
- Insufficient disk space
- Backup directory doesn't exist
- Permission issues

**Solutions:**
1. Check available disk space
2. Create `backend/backups/` directory
3. Check write permissions
4. Try cleanup without backup (not recommended)

### Application Breaks After Cleanup

**Possible Causes:**
- Removed an actively used file
- Removed a required dependency
- Cleanup system bug

**Solutions:**
1. Restore from backup immediately
2. Extract backup ZIP file
3. Copy files back to original locations
4. Reinstall removed dependencies
5. Restart application
6. Report the issue

## Advanced Usage

### Custom Cleanup Criteria

The cleanup system uses these criteria:

**File Analysis:**
- AST parsing to find model references
- UI configuration analysis for wake words
- Config file loading detection

**Dependency Analysis:**
- AST parsing to find imports
- Transitive dependency resolution
- System package exclusion

### Cleanup Scheduling

You can schedule periodic cleanup:

1. Generate reports automatically (e.g., weekly)
2. Review reports manually
3. Execute cleanup as needed
4. Archive old backups

**Example Cron Job (Linux):**
```bash
# Generate cleanup report every Monday at 2 AM
0 2 * * 1 cd /path/to/IRISVOICE && python -c "from backend.tools.cleanup_analyzer import CleanupAnalyzer; CleanupAnalyzer().generate_report()"
```

### Cleanup Metrics

Track cleanup metrics over time:
- Total space freed
- Number of items removed
- Cleanup frequency
- Backup sizes

## FAQ

**Q: Will cleanup remove my conversation history?**
A: No, cleanup only removes unused files and dependencies. Active data is never touched.

**Q: Can I undo a cleanup?**
A: Yes, if backups are enabled (default). Extract the backup ZIP and restore files manually.

**Q: How often should I run cleanup?**
A: Monthly is recommended, or whenever you notice disk space issues.

**Q: Will cleanup affect performance?**
A: Cleanup may improve performance by reducing disk usage and simplifying the codebase.

**Q: Can I customize what gets flagged as unused?**
A: Not currently. The cleanup system uses conservative criteria to avoid removing active items.

**Q: What if cleanup removes something I need?**
A: Restore from the backup immediately. Report the issue so the cleanup criteria can be improved.

**Q: Can I run cleanup while the application is running?**
A: Yes, but it's recommended to close the application first to avoid file-in-use errors.

**Q: How much space can I expect to free?**
A: This varies greatly. Check the cleanup report for estimated space savings before executing.

## Next Steps

- [System Overview](./SYSTEM_OVERVIEW.md)
- [Deployment Guide](../DEPLOYMENT_GUIDE.md)
- [Troubleshooting Guide](../TROUBLESHOOTING_GUIDE.md)
