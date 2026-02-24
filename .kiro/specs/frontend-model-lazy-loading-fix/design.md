# Frontend Model Lazy Loading Fix - Bugfix Design

## Overview

The IRIS Voice Tauri widget experiences severe memory spikes (7000+ MB) and extended freeze times (up to 16 minutes) during frontend startup in dev mode. The root cause is that Next.js's webpack build process is attempting to process or cache the large AI model files (7GB+) stored in the `IRISVOICE/models/` directory during frontend compilation. While the backend correctly has lazy loading commented out (`audio_engine.initialize()` is disabled in `main.py`), the frontend build system is still accessing these files during the cache write process.

The fix involves explicitly excluding the models directory from Next.js's webpack processing and filesystem watching, ensuring that model files are never touched during frontend compilation. The backend already has proper lazy loading infrastructure in place - models are only initialized when `lfm_audio_manager.initialize()` is explicitly called, which happens on-demand when voice features are used.

## Glossary

- **Bug_Condition (C)**: The condition that triggers the bug - when Next.js webpack processes or watches the models directory during dev mode startup
- **Property (P)**: The desired behavior - Next.js should completely ignore the models directory during build and watch processes
- **Preservation**: Backend lazy loading behavior and model inference capabilities that must remain unchanged
- **next.config.mjs**: The Next.js configuration file at `IRISVOICE/next.config.mjs` that controls webpack behavior
- **webpack.watchOptions**: Configuration that controls which files webpack monitors for changes
- **webpack.module.rules**: Configuration that controls how webpack processes different file types
- **models directory**: The `IRISVOICE/models/` directory containing LFM Audio (1.5B), LFM2-8B-A1B, and LFM2.5-1.2B-Instruct models
- **lfm_audio_manager**: The backend component in `backend/agent/lfm_audio_manager.py` that handles lazy model initialization
- **lifespan manager**: The FastAPI lifespan context in `backend/main.py` that controls backend startup behavior

## Bug Details

### Fault Condition

The bug manifests when Next.js starts in dev mode (`npm run dev:tauri`) and webpack begins its compilation and file watching process. The webpack bundler is either attempting to process model files as potential assets, watching the models directory for changes, or caching file metadata from the models directory. This causes the system to read or scan the 7GB+ of model files during the frontend build process.

**Formal Specification:**
```
FUNCTION isBugCondition(input)
  INPUT: input of type WebpackCompilationContext
  OUTPUT: boolean
  
  RETURN input.mode == "development"
         AND input.compilationPhase IN ["cache-write", "asset-processing", "file-watching"]
         AND modelsDirectoryExists("IRISVOICE/models/")
         AND NOT modelsDirectoryExcluded(input.webpackConfig)
END FUNCTION
```

### Examples

- **Dev Mode Startup**: Run `npm run dev:tauri` → Next.js compilation begins → Memory spikes to 7000+ MB → IDE freezes for 16 minutes during cache write → Eventually completes but with severe performance degradation
- **File Watch Trigger**: After initial startup, save any frontend file → Webpack recompilation triggers → System scans models directory → Brief freeze occurs
- **Clean Build**: Delete `.next` cache and run `npm run dev` → Webpack creates new cache → Attempts to process/scan models directory → Extended freeze during cache creation
- **Expected Behavior**: Run `npm run dev:tauri` → Next.js compilation begins → Models directory is completely ignored → Compilation completes in normal time (~30 seconds) → No memory spike → No IDE freeze

## Expected Behavior

### Preservation Requirements

**Unchanged Behaviors:**
- Backend lazy loading must continue to work - models should only initialize when `lfm_audio_manager.initialize()` is explicitly called
- Model inference capabilities must remain identical after models are loaded on-demand
- Production builds must continue to exclude model files from the bundle
- Backend startup sequence must remain unchanged - `audio_engine.initialize()` stays commented out in lifespan manager
- Voice command and chat features must continue to trigger model loading correctly when first used

**Scope:**
All inputs that do NOT involve Next.js webpack processing the models directory should be completely unaffected by this fix. This includes:
- Backend model loading and inference behavior
- Model file locations and structure
- API endpoints that trigger model initialization
- User interactions with voice/chat features after models are loaded
- Production build process and output

## Hypothesized Root Cause

Based on the bug description and code analysis, the most likely issues are:

1. **Webpack File Watching**: Webpack's default file watching includes all directories in the project root, causing it to monitor the models directory for changes. This triggers file system scans of 7GB+ of model files during startup and on every recompilation.

2. **Webpack Asset Processing**: Webpack may be attempting to process model files (`.bin`, `.safetensors`, `.json`, `.txt`) as potential assets or resources, causing it to read and cache metadata about these large files during the build process.

3. **Next.js Cache System**: Next.js's incremental cache system may be attempting to cache file metadata or checksums for all files in the project directory, including the models directory, causing extensive file I/O during the cache write phase.

4. **Missing Explicit Exclusions**: While `.gitignore` excludes the models directory from version control, webpack and Next.js have separate configuration systems that don't automatically respect `.gitignore`. The `next.config.mjs` file lacks explicit exclusions for the models directory.

## Correctness Properties

Property 1: Fault Condition - Webpack Ignores Models Directory

_For any_ webpack compilation where the models directory exists and Next.js is running in development mode, the fixed webpack configuration SHALL completely exclude the models directory from file watching, asset processing, and cache operations, preventing any file I/O operations on model files during frontend compilation.

**Validates: Requirements 2.1, 2.2, 2.3**

Property 2: Preservation - Backend Lazy Loading Behavior

_For any_ backend operation that does NOT involve Next.js webpack compilation (model initialization, inference, API requests), the fixed configuration SHALL produce exactly the same behavior as the original system, preserving all lazy loading semantics and model inference capabilities.

**Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5**

## Fix Implementation

### Changes Required

Assuming our root cause analysis is correct:

**File**: `IRISVOICE/next.config.mjs`

**Function**: `webpack` configuration function

**Specific Changes**:

1. **Add watchOptions.ignored**: Configure webpack to explicitly ignore the models directory from file watching
   - Add `watchOptions: { ignored: ['**/models/**', '**/node_modules/**'] }` to webpack config
   - This prevents webpack from monitoring the models directory for changes

2. **Add module.rules exclusion**: Configure webpack to skip processing model file types
   - Add a rule that excludes `.bin`, `.safetensors`, `.json`, `.txt` files from the models directory
   - This prevents webpack from attempting to process model files as assets

3. **Verify existing exclusions**: Ensure the models directory is not inadvertently included by other webpack configurations
   - Check that no existing rules or plugins are processing the models directory
   - Verify that the `distDir` and other output paths don't overlap with models directory

4. **Add filesystem exclusion comment**: Document why the models directory is excluded
   - Add clear comments explaining that models are loaded by the backend on-demand
   - Reference the backend lazy loading implementation

**Example Configuration**:
```javascript
webpack: (config, { isServer }) => {
  // Exclude models directory from webpack processing and watching
  // Models are loaded lazily by the backend on-demand (see backend/agent/lfm_audio_manager.py)
  config.watchOptions = {
    ...config.watchOptions,
    ignored: ['**/models/**', '**/node_modules/**', '**/.git/**']
  };
  
  // Exclude model files from webpack asset processing
  config.module.rules.push({
    test: /\.(bin|safetensors)$/,
    type: 'asset/resource',
    exclude: /models\//,
  });
  
  if (!isServer) {
    config.optimization = {
      ...config.optimization,
      moduleIds: 'named',
      chunkIds: 'named',
    };
  }
  
  return config;
},
```

## Testing Strategy

### Validation Approach

The testing strategy follows a two-phase approach: first, surface counterexamples that demonstrate the bug on unfixed code by measuring memory usage and freeze times during dev mode startup, then verify the fix eliminates the memory spike and preserves all backend functionality.

### Exploratory Fault Condition Checking

**Goal**: Surface counterexamples that demonstrate the bug BEFORE implementing the fix. Confirm that Next.js webpack is indeed processing the models directory during dev mode startup.

**Test Plan**: Monitor system memory usage and webpack compilation logs during `npm run dev:tauri` startup on the UNFIXED code. Measure the time taken for compilation and identify when memory spikes occur. Use webpack's `--profile` flag to identify which files are being processed.

**Test Cases**:
1. **Clean Build Memory Test**: Delete `.next` cache, run `npm run dev:tauri`, monitor memory usage during compilation (will show 7000+ MB spike on unfixed code)
2. **Compilation Time Test**: Measure time from `npm run dev:tauri` to "compiled successfully" message (will show 16+ minute freeze on unfixed code)
3. **Webpack Profile Test**: Run with `--profile` flag and check if models directory files appear in compilation output (will show model files being processed on unfixed code)
4. **File Watch Test**: After startup, touch a frontend file and observe if webpack scans models directory during recompilation (may show brief freeze on unfixed code)

**Expected Counterexamples**:
- Memory usage spikes to 7000+ MB during cache write phase
- Compilation takes 16+ minutes with IDE freeze
- Webpack logs show processing or watching files in models directory
- Possible causes: webpack file watching includes models directory, webpack asset processing attempts to handle model files, Next.js cache system scans all project files

### Fix Checking

**Goal**: Verify that for all webpack compilations where the models directory exists, the fixed configuration prevents any file I/O on model files.

**Pseudocode:**
```
FOR ALL compilation WHERE modelsDirectoryExists() DO
  result := runWebpackCompilation_fixed()
  ASSERT result.memoryUsage < 1000MB
  ASSERT result.compilationTime < 60 seconds
  ASSERT NOT modelsDirectoryInWatchList(result)
  ASSERT NOT modelsFilesInAssetList(result)
END FOR
```

**Test Plan**: After applying the fix, run the same test cases and verify that memory usage stays under 1GB, compilation completes in under 60 seconds, and webpack logs show no references to the models directory.

**Test Cases**:
1. **Clean Build Memory Test (Fixed)**: Delete `.next` cache, run `npm run dev:tauri`, verify memory stays under 1GB
2. **Compilation Time Test (Fixed)**: Measure time from start to "compiled successfully", verify under 60 seconds
3. **Webpack Profile Test (Fixed)**: Run with `--profile` flag, verify no model files in output
4. **File Watch Test (Fixed)**: Touch frontend file, verify no models directory scan during recompilation

### Preservation Checking

**Goal**: Verify that for all backend operations that do NOT involve webpack compilation, the fixed configuration produces the same behavior as the original system.

**Pseudocode:**
```
FOR ALL operation WHERE NOT isWebpackCompilation(operation) DO
  ASSERT backendBehavior_original(operation) = backendBehavior_fixed(operation)
END FOR
```

**Testing Approach**: Property-based testing is recommended for preservation checking because:
- It generates many test cases automatically across different backend operations
- It catches edge cases that manual unit tests might miss (e.g., different model loading sequences, concurrent requests)
- It provides strong guarantees that backend behavior is unchanged for all non-webpack operations

**Test Plan**: Observe backend behavior on UNFIXED code first for model initialization and inference, then write property-based tests capturing that behavior and verify it continues after the fix.

**Test Cases**:
1. **Model Initialization Preservation**: Verify that calling `lfm_audio_manager.initialize()` loads models correctly and produces the same initialization logs and timing
2. **Model Inference Preservation**: Verify that after models are loaded, inference requests produce identical results (transcription accuracy, response generation, audio synthesis)
3. **Lazy Loading Preservation**: Verify that models are NOT loaded during backend startup (lifespan manager) and only load when explicitly requested
4. **API Endpoint Preservation**: Verify that all voice/chat API endpoints continue to work correctly and trigger model loading as expected
5. **Production Build Preservation**: Verify that `npm run build` continues to exclude model files from the production bundle

### Unit Tests

- Test that webpack config includes models directory in watchOptions.ignored
- Test that webpack config excludes model file types from asset processing
- Test that Next.js dev mode starts without accessing models directory
- Test that backend lazy loading still works after frontend config changes

### Property-Based Tests

- Generate random frontend file changes and verify webpack never scans models directory during recompilation
- Generate random backend API requests and verify model loading behavior is unchanged
- Generate random model initialization sequences and verify lazy loading semantics are preserved

### Integration Tests

- Test full dev mode startup flow: `npm run dev:tauri` → backend starts → frontend compiles → models NOT loaded → memory usage normal
- Test on-demand model loading: Start app → trigger voice command → models load → inference works correctly
- Test production build: `npm run build` → verify models excluded from bundle → verify backend can still load models in production mode
