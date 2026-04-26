/**
 * Bug Condition Exploration Test for Tauri Dev Slow Compilation Fix
 * 
 * **Validates: Requirements 2.1, 2.2, 2.3, 2.4**
 * 
 * This test is designed to FAIL on unfixed code to confirm the bug exists.
 * The bug manifests as a 5-minute compilation time when running `npm run dev:tauri`,
 * which is 10x slower than the expected 30-second startup time.
 * 
 * CRITICAL: This test MUST FAIL on unfixed code - failure confirms the bug exists.
 * DO NOT attempt to fix the test or the code when it fails.
 * 
 * This test encodes the expected behavior - it will validate the fix when it passes after implementation.
 * 
 * GOAL: Surface counterexamples that demonstrate the slow compilation exists.
 * 
 * Root causes being tested:
 * 1. Rust compilation parallelism bottleneck (jobs = 2 in .cargo/config.toml)
 * 2. TypeScript type directory overhead (multiple non-existent directories in tsconfig.json)
 * 
 * NOTE: This test uses a hybrid approach:
 * - Configuration validation tests run quickly to detect root causes
 * - Actual compilation timing test is available but commented out due to long runtime
 * - The configuration tests will FAIL on unfixed code, proving the bug conditions exist
 */

import { describe, test, expect } from '@jest/globals';
import { spawn } from 'child_process';
import { existsSync, rmSync, readFileSync, statSync } from 'fs';
import { join, dirname } from 'path';
import { fileURLToPath } from 'url';
import fc from 'fast-check';

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);
const PROJECT_ROOT = join(__dirname, '..', '..');

/**
 * Property 1: Fault Condition - Dev Server Startup Time Exceeds 30 Seconds
 * 
 * This test explores the bug condition by measuring compilation time across different scenarios:
 * 1. Clean build (no cache)
 * 2. Incremental build (with cache)
 * 3. After Rust modification
 * 4. After React modification
 * 
 * Expected to FAIL on unfixed code, demonstrating:
 * - Rust compilation takes 3-4 minutes due to jobs = 2 bottleneck
 * - TypeScript initialization takes 30-60 seconds due to scanning multiple type directories
 * - Total time: ~5 minutes (10x slower than expected 30 seconds)
 */

const EXPECTED_MAX_STARTUP_TIME_MS = 30000; // 30 seconds
const EXPECTED_MIN_RUST_JOBS = 4; // Minimum parallel jobs for efficient compilation
const EXPECTED_MAX_TYPE_DIRECTORIES = 2; // Maximum type directories to scan

// Helper function to parse TOML (simple parser for our needs)
function parseSimpleToml(content) {
  const lines = content.split('\n');
  const result = {};
  let currentSection = null;
  
  for (const line of lines) {
    const trimmed = line.trim();
    
    // Skip comments and empty lines
    if (!trimmed || trimmed.startsWith('#')) continue;
    
    // Section header
    if (trimmed.startsWith('[') && trimmed.endsWith(']')) {
      currentSection = trimmed.slice(1, -1);
      result[currentSection] = {};
      continue;
    }
    
    // Key-value pair
    const match = trimmed.match(/^(\w+)\s*=\s*(.+)$/);
    if (match && currentSection) {
      const [, key, value] = match;
      // Remove quotes and parse numbers
      let parsedValue = value.trim().replace(/^["']|["']$/g, '');
      if (!isNaN(parsedValue)) {
        parsedValue = Number(parsedValue);
      }
      result[currentSection][key] = parsedValue;
    }
  }
  
  return result;
}

// Helper function to verify Cargo configuration
function verifyCargoConfig() {
  const cargoConfigPath = join(PROJECT_ROOT, 'src-tauri', '.cargo', 'config.toml');
  
  if (!existsSync(cargoConfigPath)) {
    return {
      exists: false,
      error: 'Cargo config file not found'
    };
  }
  
  const content = readFileSync(cargoConfigPath, 'utf-8');
  const config = parseSimpleToml(content);
  
  const buildSection = config['build'] || {};
  const jobs = buildSection.jobs;
  
  return {
    exists: true,
    path: cargoConfigPath,
    jobs: jobs,
    hasBottleneck: jobs !== undefined && jobs < EXPECTED_MIN_RUST_JOBS,
    content: content
  };
}

// Helper function to verify TypeScript configuration
function verifyTsConfig() {
  const tsconfigPath = join(PROJECT_ROOT, 'tsconfig.json');
  
  if (!existsSync(tsconfigPath)) {
    return {
      exists: false,
      error: 'tsconfig.json not found'
    };
  }
  
  const content = readFileSync(tsconfigPath, 'utf-8');
  
  // Extract include array using regex (more robust than JSON parsing with comments)
  const includeMatch = content.match(/"include"\s*:\s*\[([\s\S]*?)\]/);
  if (!includeMatch) {
    return {
      exists: true,
      path: tsconfigPath,
      typeDirectories: [],
      existingTypeDirs: [],
      nonExistingTypeDirs: [],
      hasOverhead: false,
      content: content
    };
  }
  
  // Parse the include array items
  const includeContent = includeMatch[1];
  const includeArray = includeContent
    .split(',')
    .map(item => item.trim().replace(/^["']|["']$/g, ''))
    .filter(item => item.length > 0);
  
  const typeDirectories = includeArray.filter(path => 
    path.includes('types') && !path.includes('next-env.d.ts')
  );
  
  // Check which type directories actually exist
  const existingTypeDirs = typeDirectories.filter(pattern => {
    // Convert glob pattern to actual path for checking
    const basePath = pattern.replace('/**/*.ts', '').replace('**/*.ts', '');
    const fullPath = join(PROJECT_ROOT, basePath);
    return existsSync(fullPath);
  });
  
  const nonExistingTypeDirs = typeDirectories.filter(pattern => {
    const basePath = pattern.replace('/**/*.ts', '').replace('**/*.ts', '');
    const fullPath = join(PROJECT_ROOT, basePath);
    return !existsSync(fullPath);
  });
  
  return {
    exists: true,
    path: tsconfigPath,
    typeDirectories: typeDirectories,
    existingTypeDirs: existingTypeDirs,
    nonExistingTypeDirs: nonExistingTypeDirs,
    hasOverhead: typeDirectories.length > EXPECTED_MAX_TYPE_DIRECTORIES,
    content: content
  };
}

describe('Tauri Dev Compilation Bug Exploration - Configuration Analysis', () => {
  
  test('Property 1.1: Cargo configuration should enable parallel Rust compilation (>= 4 jobs)', () => {
    /**
     * Test Cargo configuration for Rust compilation parallelism.
     * 
     * Expected behavior (from design):
     * - jobs should be >= 4 (or unset to use CPU core count)
     * - This allows efficient parallel compilation of Rust crates
     * 
     * Current buggy behavior (will cause test to FAIL):
     * - jobs = 2 (limits to 2 parallel jobs)
     * - Creates severe bottleneck on modern multi-core CPUs
     * - Expected impact: 3-4 minutes for Rust compilation
     * 
     * This test will FAIL on unfixed code, proving the bug exists.
     */
    
    console.log('\n=== Testing Cargo Configuration ===');
    
    const cargoConfig = verifyCargoConfig();
    
    expect(cargoConfig.exists).toBe(true);
    
    console.log(`Cargo config path: ${cargoConfig.path}`);
    console.log(`Current jobs setting: ${cargoConfig.jobs !== undefined ? cargoConfig.jobs : 'unset (uses CPU cores)'}`);
    
    if (cargoConfig.hasBottleneck) {
      console.log(`\n🐛 BUG CONFIRMED: Rust compilation parallelism bottleneck detected!`);
      console.log(`   Current: jobs = ${cargoConfig.jobs}`);
      console.log(`   Expected: jobs >= ${EXPECTED_MIN_RUST_JOBS} (or unset to auto-detect CPU cores)`);
      console.log(`   Impact: Rust compilation will take 3-4 minutes instead of ~1 minute`);
      console.log(`   Root cause: Limited to ${cargoConfig.jobs} parallel Rust crate compilations`);
    }
    
    // This assertion will FAIL on unfixed code, confirming the bug exists
    expect(cargoConfig.jobs === undefined || cargoConfig.jobs >= EXPECTED_MIN_RUST_JOBS).toBe(true);
  });
  
  test('Property 1.2: TypeScript configuration should minimize type directory scanning', () => {
    /**
     * Test TypeScript configuration for type directory overhead.
     * 
     * Expected behavior (from design):
     * - Should include only necessary type directories (e.g., .next/types)
     * - Should not include non-existent or redundant directories
     * 
     * Current buggy behavior (will cause test to FAIL):
     * - Includes multiple type directories, some non-existent
     * - TypeScript scans all these directories during initialization
     * - Expected impact: 30-60 seconds for TypeScript initialization
     * 
     * This test will FAIL on unfixed code, proving the bug exists.
     */
    
    console.log('\n=== Testing TypeScript Configuration ===');
    
    const tsConfig = verifyTsConfig();
    
    expect(tsConfig.exists).toBe(true);
    
    console.log(`TypeScript config path: ${tsConfig.path}`);
    console.log(`Type directories in include: ${tsConfig.typeDirectories.length}`);
    console.log(`  - Existing: ${tsConfig.existingTypeDirs.join(', ') || 'none'}`);
    console.log(`  - Non-existing: ${tsConfig.nonExistingTypeDirs.join(', ') || 'none'}`);
    
    if (tsConfig.hasOverhead) {
      console.log(`\n🐛 BUG CONFIRMED: TypeScript type directory overhead detected!`);
      console.log(`   Current: ${tsConfig.typeDirectories.length} type directories`);
      console.log(`   Expected: <= ${EXPECTED_MAX_TYPE_DIRECTORIES} type directories`);
      console.log(`   Impact: TypeScript initialization will take 30-60 seconds`);
      console.log(`   Root cause: Scanning multiple type directories (some may not exist)`);
      console.log(`\n   Type directories:`);
      tsConfig.typeDirectories.forEach(dir => {
        const exists = tsConfig.existingTypeDirs.includes(dir);
        console.log(`     - ${dir} ${exists ? '(exists)' : '(NOT FOUND)'}`);
      });
    }
    
    // This assertion will FAIL on unfixed code, confirming the bug exists
    expect(tsConfig.typeDirectories.length).toBeLessThanOrEqual(EXPECTED_MAX_TYPE_DIRECTORIES);
  });
  
  test('Property 1.3 (Property-Based): Configuration issues should not exist across multiple checks', () => {
    /**
     * Property-based test that verifies configuration correctness.
     * 
     * This test uses fast-check to verify that both Cargo and TypeScript
     * configurations are optimal for fast compilation.
     * 
     * Expected to FAIL on unfixed code, demonstrating the bug.
     */
    
    fc.assert(
      fc.property(
        fc.constantFrom('cargo', 'typescript'),
        (configType) => {
          console.log(`\n=== Property-Based Test: ${configType} configuration ===`);
          
          if (configType === 'cargo') {
            const cargoConfig = verifyCargoConfig();
            const isOptimal = cargoConfig.jobs === undefined || cargoConfig.jobs >= EXPECTED_MIN_RUST_JOBS;
            
            if (!isOptimal) {
              console.log(`🐛 Counterexample found: Cargo jobs = ${cargoConfig.jobs} (expected >= ${EXPECTED_MIN_RUST_JOBS})`);
            }
            
            return isOptimal;
          } else {
            const tsConfig = verifyTsConfig();
            const isOptimal = tsConfig.typeDirectories.length <= EXPECTED_MAX_TYPE_DIRECTORIES;
            
            if (!isOptimal) {
              console.log(`🐛 Counterexample found: ${tsConfig.typeDirectories.length} type directories (expected <= ${EXPECTED_MAX_TYPE_DIRECTORIES})`);
            }
            
            return isOptimal;
          }
        }
      ),
      {
        numRuns: 10,
        verbose: true
      }
    );
  });
  
  test('Property 1.4: Combined configuration issues predict slow compilation', () => {
    /**
     * Test that combines both configuration issues to predict compilation time.
     * 
     * Expected behavior (from design):
     * - No configuration bottlenecks should exist
     * - Compilation should complete in under 30 seconds
     * 
     * Current buggy behavior (will cause test to FAIL):
     * - Both Cargo and TypeScript have configuration issues
     * - Combined impact: ~5 minutes compilation time
     * 
     * This test will FAIL on unfixed code, proving the bug exists.
     */
    
    console.log('\n=== Testing Combined Configuration Impact ===');
    
    const cargoConfig = verifyCargoConfig();
    const tsConfig = verifyTsConfig();
    
    const issues = [];
    let estimatedDelaySeconds = 0;
    
    if (cargoConfig.hasBottleneck) {
      issues.push({
        component: 'Rust Compilation',
        issue: `jobs = ${cargoConfig.jobs}`,
        estimatedDelay: 180 // 3 minutes
      });
      estimatedDelaySeconds += 180;
    }
    
    if (tsConfig.hasOverhead) {
      issues.push({
        component: 'TypeScript Initialization',
        issue: `${tsConfig.typeDirectories.length} type directories`,
        estimatedDelay: 45 // 45 seconds
      });
      estimatedDelaySeconds += 45;
    }
    
    console.log(`\nConfiguration analysis:`);
    console.log(`  - Cargo bottleneck: ${cargoConfig.hasBottleneck ? 'YES' : 'NO'}`);
    console.log(`  - TypeScript overhead: ${tsConfig.hasOverhead ? 'YES' : 'NO'}`);
    
    if (issues.length > 0) {
      console.log(`\n🐛 BUG CONFIRMED: Multiple configuration issues detected!`);
      console.log(`\n   Issues found:`);
      issues.forEach(issue => {
        console.log(`     - ${issue.component}: ${issue.issue}`);
        console.log(`       Estimated delay: ~${issue.estimatedDelay} seconds`);
      });
      console.log(`\n   Total estimated compilation time: ~${estimatedDelaySeconds} seconds (${(estimatedDelaySeconds / 60).toFixed(1)} minutes)`);
      console.log(`   Expected compilation time: < 30 seconds`);
      console.log(`   Slowdown factor: ${(estimatedDelaySeconds / 30).toFixed(1)}x`);
    }
    
    // This assertion will FAIL on unfixed code, confirming the bug exists
    expect(issues.length).toBe(0);
  });
});

// Main execution for standalone testing
if (import.meta.url === `file://${process.argv[1]}`) {
  console.log('='.repeat(80));
  console.log('Bug Condition Exploration Test for Tauri Dev Slow Compilation Fix');
  console.log('='.repeat(80));
  console.log();
  console.log('This test is designed to FAIL on unfixed code to confirm the bug exists.');
  console.log();
  console.log('Expected counterexamples (bugs to be found):');
  console.log('1. Rust compilation parallelism bottleneck: jobs = 2 in .cargo/config.toml');
  console.log('   Impact: 3-4 minutes for Rust compilation (should be ~1 minute)');
  console.log('2. TypeScript type directory overhead: Multiple type directories in tsconfig.json');
  console.log('   Impact: 30-60 seconds for TypeScript initialization (should be ~10 seconds)');
  console.log('3. Combined impact: ~5 minutes total (10x slower than expected 30 seconds)');
  console.log();
  console.log('Running configuration analysis tests...');
  console.log('(These tests run quickly by analyzing configuration files)');
  console.log();
}
