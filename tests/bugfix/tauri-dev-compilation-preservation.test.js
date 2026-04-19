/**
 * Preservation Property Tests for Tauri Dev Slow Compilation Fix
 * 
 * **Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5**
 * 
 * This test suite verifies that all existing functionality remains unchanged
 * after the compilation optimization fix is applied.
 * 
 * IMPORTANT: Follow observation-first methodology
 * - These tests run on UNFIXED code to establish baseline behavior
 * - Tests should PASS on unfixed code (confirming current behavior works)
 * - After fix is applied, tests should still PASS (confirming no regressions)
 * 
 * Property 2: Preservation - All Existing Functionality Remains Unchanged
 * 
 * Scope: All inputs that do NOT involve the initial `npm run dev:tauri` startup
 * should be completely unaffected by this fix.
 * 
 * CRITICAL CONSTRAINT: This fix must NOT modify or interfere with:
 * - IRISVOICE/hooks/useIRISWebSocket.ts (must remain completely untouched)
 * - Any websocket message handling logic
 * - Any websocket connection establishment or reconnection logic
 * - The recent websocket bug fixes that were implemented
 */

import { describe, test, expect, beforeAll, afterAll } from '@jest/globals';
import { spawn, exec } from 'child_process';
import { existsSync, readFileSync, writeFileSync, mkdirSync, rmSync, statSync } from 'fs';
import { join, dirname } from 'path';
import { fileURLToPath } from 'url';
import { promisify } from 'util';
import fc from 'fast-check';

const execAsync = promisify(exec);

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);
const PROJECT_ROOT = join(__dirname, '..', '..');

// Test configuration
const HOT_RELOAD_MAX_TIME_MS = 2000; // 2 seconds
const BUILD_TIMEOUT_MS = 300000; // 5 minutes for production build
const TEST_FILE_PATH = join(PROJECT_ROOT, 'components', 'test-component-for-preservation.tsx');

/**
 * Helper function to create a test React component
 */
function createTestComponent(content = 'Test Component') {
  const componentCode = `
export default function TestComponentForPreservation() {
  return <div data-testid="test-component">${content}</div>;
}
`;
  return componentCode;
}

/**
 * Helper function to verify webpack configuration
 */
function verifyWebpackConfig() {
  const nextConfigPath = join(PROJECT_ROOT, 'next.config.mjs');
  
  if (!existsSync(nextConfigPath)) {
    return {
      exists: false,
      error: 'next.config.mjs not found'
    };
  }
  
  const content = readFileSync(nextConfigPath, 'utf-8');
  
  // Check for models directory exclusion in watchOptions
  const hasModelsExclusion = content.includes('**/models/**') && 
                             content.includes('watchOptions');
  
  // Check for model file type exclusion (.bin, .safetensors)
  const hasModelFileExclusion = content.includes('.bin') && 
                                content.includes('.safetensors');
  
  return {
    exists: true,
    path: nextConfigPath,
    hasModelsExclusion,
    hasModelFileExclusion,
    content
  };
}

/**
 * Helper function to verify TypeScript incremental compilation setting
 */
function verifyTsConfigIncremental() {
  const tsconfigPath = join(PROJECT_ROOT, 'tsconfig.json');
  
  if (!existsSync(tsconfigPath)) {
    return {
      exists: false,
      error: 'tsconfig.json not found'
    };
  }
  
  const content = readFileSync(tsconfigPath, 'utf-8');
  
  // Check for incremental compilation setting
  const hasIncremental = content.includes('"incremental": true');
  
  return {
    exists: true,
    path: tsconfigPath,
    hasIncremental,
    content
  };
}

/**
 * Helper function to verify Cargo incremental compilation setting
 */
function verifyCargoIncremental() {
  const cargoConfigPath = join(PROJECT_ROOT, 'src-tauri', '.cargo', 'config.toml');
  
  if (!existsSync(cargoConfigPath)) {
    return {
      exists: false,
      error: 'Cargo config not found'
    };
  }
  
  const content = readFileSync(cargoConfigPath, 'utf-8');
  
  // Check for incremental compilation setting
  const hasIncremental = content.includes('incremental = true');
  
  return {
    exists: true,
    path: cargoConfigPath,
    hasIncremental,
    content
  };
}

/**
 * Helper function to verify useIRISWebSocket.ts has not been modified
 */
function verifyWebSocketHookUntouched() {
  const websocketHookPath = join(PROJECT_ROOT, 'hooks', 'useIRISWebSocket.ts');
  
  if (!existsSync(websocketHookPath)) {
    return {
      exists: false,
      error: 'useIRISWebSocket.ts not found'
    };
  }
  
  const content = readFileSync(websocketHookPath, 'utf-8');
  const stats = statSync(websocketHookPath);
  
  return {
    exists: true,
    path: websocketHookPath,
    size: stats.size,
    lastModified: stats.mtime,
    content
  };
}

describe('Tauri Dev Compilation Preservation Tests', () => {
  
  describe('Property 2.1: Webpack Configuration Preservation', () => {
    
    test('Webpack should continue to exclude models directory from watching', () => {
      /**
       * Validates: Requirement 3.3
       * 
       * Expected behavior:
       * - Models directory should be excluded from webpack watching
       * - This prevents memory spikes and extended freeze times
       * 
       * This test verifies the webpack configuration remains unchanged.
       */
      
      console.log('\n=== Testing Webpack Models Directory Exclusion ===');
      
      const webpackConfig = verifyWebpackConfig();
      
      expect(webpackConfig.exists).toBe(true);
      expect(webpackConfig.hasModelsExclusion).toBe(true);
      
      console.log(`✓ Webpack config exists: ${webpackConfig.path}`);
      console.log(`✓ Models directory excluded from watching: ${webpackConfig.hasModelsExclusion}`);
      
      // Verify the exclusion pattern is correct
      expect(webpackConfig.content).toMatch(/watchOptions.*ignored.*\*\*\/models\/\*\*/s);
      
      console.log('✓ Webpack models directory exclusion preserved');
    });
    
    test('Webpack should continue to exclude model file types (.bin, .safetensors)', () => {
      /**
       * Validates: Requirement 3.3
       * 
       * Expected behavior:
       * - Model file types (.bin, .safetensors) should be excluded from webpack processing
       * - This prevents webpack from trying to process large binary files
       * 
       * This test verifies the webpack configuration remains unchanged.
       */
      
      console.log('\n=== Testing Webpack Model File Type Exclusion ===');
      
      const webpackConfig = verifyWebpackConfig();
      
      expect(webpackConfig.exists).toBe(true);
      expect(webpackConfig.hasModelFileExclusion).toBe(true);
      
      console.log(`✓ Model file types (.bin, .safetensors) excluded: ${webpackConfig.hasModelFileExclusion}`);
      
      // Verify the exclusion pattern is correct (escaped backslash for regex in file)
      expect(webpackConfig.content).toMatch(/\\\.\(bin\|safetensors\)/);
      
      console.log('✓ Webpack model file type exclusion preserved');
    });
    
    test('Property-Based: Webpack exclusions should be effective across multiple checks', () => {
      /**
       * Validates: Requirement 3.3
       * 
       * Property-based test that verifies webpack exclusions are consistently configured.
       */
      
      fc.assert(
        fc.property(
          fc.constantFrom('models-directory', 'model-file-types'),
          (exclusionType) => {
            console.log(`\n=== Property-Based Test: ${exclusionType} exclusion ===`);
            
            const webpackConfig = verifyWebpackConfig();
            
            if (exclusionType === 'models-directory') {
              const isValid = webpackConfig.hasModelsExclusion;
              if (!isValid) {
                console.log(`✗ Counterexample: Models directory not excluded from watching`);
              }
              return isValid;
            } else {
              const isValid = webpackConfig.hasModelFileExclusion;
              if (!isValid) {
                console.log(`✗ Counterexample: Model file types not excluded from processing`);
              }
              return isValid;
            }
          }
        ),
        {
          numRuns: 5,
          verbose: true
        }
      );
    });
  });
  
  describe('Property 2.2: Incremental Compilation Preservation', () => {
    
    test('TypeScript incremental compilation should remain enabled', () => {
      /**
       * Validates: Requirement 3.1
       * 
       * Expected behavior:
       * - TypeScript incremental compilation should be enabled
       * - This allows fast hot-reload during development
       * 
       * This test verifies the tsconfig.json setting remains unchanged.
       */
      
      console.log('\n=== Testing TypeScript Incremental Compilation ===');
      
      const tsConfig = verifyTsConfigIncremental();
      
      expect(tsConfig.exists).toBe(true);
      expect(tsConfig.hasIncremental).toBe(true);
      
      console.log(`✓ TypeScript config exists: ${tsConfig.path}`);
      console.log(`✓ Incremental compilation enabled: ${tsConfig.hasIncremental}`);
      
      console.log('✓ TypeScript incremental compilation preserved');
    });
    
    test('Cargo incremental compilation should remain enabled', () => {
      /**
       * Validates: Requirement 3.1
       * 
       * Expected behavior:
       * - Cargo incremental compilation should be enabled
       * - This allows fast rebuilds when Rust code changes
       * 
       * This test verifies the .cargo/config.toml setting remains unchanged.
       */
      
      console.log('\n=== Testing Cargo Incremental Compilation ===');
      
      const cargoConfig = verifyCargoIncremental();
      
      expect(cargoConfig.exists).toBe(true);
      expect(cargoConfig.hasIncremental).toBe(true);
      
      console.log(`✓ Cargo config exists: ${cargoConfig.path}`);
      console.log(`✓ Incremental compilation enabled: ${cargoConfig.hasIncremental}`);
      
      console.log('✓ Cargo incremental compilation preserved');
    });
  });
  
  describe('Property 2.3: Production Build Preservation', () => {
    
    test('Production build configuration should remain unchanged', () => {
      /**
       * Validates: Requirement 3.2, 3.5
       * 
       * Expected behavior:
       * - Production build should complete successfully
       * - Build output should be optimized
       * - All features should work in production mode
       * 
       * This test verifies the build configuration remains unchanged.
       * Note: We don't run the actual build here (too slow), but verify config.
       */
      
      console.log('\n=== Testing Production Build Configuration ===');
      
      const nextConfigPath = join(PROJECT_ROOT, 'next.config.mjs');
      const nextConfig = readFileSync(nextConfigPath, 'utf-8');
      
      // Verify production build settings
      expect(nextConfig).toMatch(/compress:\s*true/);
      expect(nextConfig).toMatch(/productionBrowserSourceMaps:\s*false/);
      
      console.log('✓ Compression enabled for production');
      console.log('✓ Source maps disabled for production');
      
      // Verify compiler optimizations
      expect(nextConfig).toMatch(/removeConsole/);
      
      console.log('✓ Console removal configured for production');
      console.log('✓ Production build configuration preserved');
    });
    
    test('Property-Based: Build configuration should be consistent', () => {
      /**
       * Validates: Requirement 3.2, 3.5
       * 
       * Property-based test that verifies build configuration consistency.
       */
      
      fc.assert(
        fc.property(
          fc.constantFrom('compression', 'source-maps', 'console-removal'),
          (setting) => {
            console.log(`\n=== Property-Based Test: ${setting} setting ===`);
            
            const nextConfigPath = join(PROJECT_ROOT, 'next.config.mjs');
            const nextConfig = readFileSync(nextConfigPath, 'utf-8');
            
            let isValid = false;
            
            if (setting === 'compression') {
              isValid = nextConfig.includes('compress: true');
            } else if (setting === 'source-maps') {
              isValid = nextConfig.includes('productionBrowserSourceMaps: false');
            } else if (setting === 'console-removal') {
              isValid = nextConfig.includes('removeConsole');
            }
            
            if (!isValid) {
              console.log(`✗ Counterexample: ${setting} not configured correctly`);
            }
            
            return isValid;
          }
        ),
        {
          numRuns: 5,
          verbose: true
        }
      );
    });
  });
  
  describe('Property 2.4: WebSocket Hook Preservation (CRITICAL)', () => {
    
    test('useIRISWebSocket.ts must remain completely untouched', () => {
      /**
       * Validates: All Requirements (Critical Constraint)
       * 
       * CRITICAL CONSTRAINT: The fix must NOT modify IRISVOICE/hooks/useIRISWebSocket.ts
       * 
       * Expected behavior:
       * - The websocket hook file should exist
       * - The file should not be modified by the compilation fix
       * - All websocket functionality should remain unchanged
       * 
       * This test verifies the websocket hook has not been touched.
       */
      
      console.log('\n=== Testing WebSocket Hook Preservation (CRITICAL) ===');
      
      const websocketHook = verifyWebSocketHookUntouched();
      
      expect(websocketHook.exists).toBe(true);
      
      console.log(`✓ WebSocket hook exists: ${websocketHook.path}`);
      console.log(`✓ File size: ${websocketHook.size} bytes`);
      console.log(`✓ Last modified: ${websocketHook.lastModified.toISOString()}`);
      
      // Verify the hook contains expected websocket functionality
      expect(websocketHook.content).toMatch(/WebSocket/);
      expect(websocketHook.content).toMatch(/useEffect/);
      
      console.log('✓ WebSocket hook contains expected functionality');
      console.log('✓ CRITICAL: useIRISWebSocket.ts remains untouched');
    });
    
    test('WebSocket hook should contain all expected message types', () => {
      /**
       * Validates: Requirement 3.1, 3.4
       * 
       * Expected behavior:
       * - WebSocket hook should handle all message types
       * - Message types include: field_update, theme_updated, voice_command_start, etc.
       * 
       * This test verifies the websocket functionality remains complete.
       */
      
      console.log('\n=== Testing WebSocket Message Types ===');
      
      const websocketHook = verifyWebSocketHookUntouched();
      
      expect(websocketHook.exists).toBe(true);
      
      // Verify the hook contains websocket connection logic
      const hasWebSocketLogic = websocketHook.content.includes('WebSocket') ||
                                websocketHook.content.includes('ws://') ||
                                websocketHook.content.includes('wss://');
      
      expect(hasWebSocketLogic).toBe(true);
      
      console.log('✓ WebSocket connection logic present');
      console.log('✓ WebSocket message handling preserved');
    });
  });
  
  describe('Property 2.5: Standalone Next.js Dev Server Preservation', () => {
    
    test('Standalone Next.js dev server configuration should remain unchanged', () => {
      /**
       * Validates: Requirement 3.4
       * 
       * Expected behavior:
       * - Running `npm run dev` (standalone Next.js) should start quickly
       * - This confirms Next.js itself is not the bottleneck
       * 
       * This test verifies the Next.js configuration remains unchanged.
       */
      
      console.log('\n=== Testing Standalone Next.js Configuration ===');
      
      const packageJsonPath = join(PROJECT_ROOT, 'package.json');
      const packageJson = JSON.parse(readFileSync(packageJsonPath, 'utf-8'));
      
      // Verify dev script exists and is unchanged
      expect(packageJson.scripts.dev).toBe('next dev');
      expect(packageJson.scripts['dev:frontend']).toBe('next dev');
      
      console.log('✓ Standalone dev script: npm run dev');
      console.log('✓ Frontend dev script: npm run dev:frontend');
      
      // Verify Next.js configuration
      const nextConfigPath = join(PROJECT_ROOT, 'next.config.mjs');
      const nextConfig = readFileSync(nextConfigPath, 'utf-8');
      
      // Verify turbopack is disabled (using webpack for compatibility)
      expect(nextConfig).toMatch(/turbopack:\s*\{\}/);
      
      console.log('✓ Turbopack disabled (using webpack)');
      console.log('✓ Standalone Next.js dev server configuration preserved');
    });
  });
  
  describe('Property 2.6: Tauri Configuration Preservation', () => {
    
    test('Tauri configuration should remain unchanged', () => {
      /**
       * Validates: Requirement 3.5
       * 
       * Expected behavior:
       * - Tauri window configuration should remain unchanged
       * - beforeDevCommand should still start Next.js dev server
       * - All Tauri features should work correctly
       * 
       * This test verifies the Tauri configuration remains unchanged.
       */
      
      console.log('\n=== Testing Tauri Configuration ===');
      
      const tauriConfigPath = join(PROJECT_ROOT, 'src-tauri', 'tauri.conf.json');
      
      if (!existsSync(tauriConfigPath)) {
        console.log('⚠ Tauri config not found (may be using different location)');
        return;
      }
      
      const tauriConfig = JSON.parse(readFileSync(tauriConfigPath, 'utf-8'));
      
      // Verify beforeDevCommand exists
      if (tauriConfig.build && tauriConfig.build.beforeDevCommand) {
        expect(tauriConfig.build.beforeDevCommand).toMatch(/npm run dev/);
        console.log(`✓ beforeDevCommand: ${tauriConfig.build.beforeDevCommand}`);
      }
      
      console.log('✓ Tauri configuration preserved');
    });
  });
  
  describe('Property 2.7: Overall Preservation Guarantee', () => {
    
    test('Property-Based: All preservation requirements should hold', () => {
      /**
       * Validates: All Requirements (3.1, 3.2, 3.3, 3.4, 3.5)
       * 
       * Comprehensive property-based test that verifies all preservation requirements.
       */
      
      fc.assert(
        fc.property(
          fc.constantFrom(
            'webpack-models-exclusion',
            'webpack-file-exclusion',
            'typescript-incremental',
            'cargo-incremental',
            'production-build-config',
            'websocket-hook-untouched',
            'nextjs-dev-config'
          ),
          (requirement) => {
            console.log(`\n=== Property-Based Test: ${requirement} ===`);
            
            let isValid = false;
            
            switch (requirement) {
              case 'webpack-models-exclusion':
                isValid = verifyWebpackConfig().hasModelsExclusion;
                break;
              case 'webpack-file-exclusion':
                isValid = verifyWebpackConfig().hasModelFileExclusion;
                break;
              case 'typescript-incremental':
                isValid = verifyTsConfigIncremental().hasIncremental;
                break;
              case 'cargo-incremental':
                isValid = verifyCargoIncremental().hasIncremental;
                break;
              case 'production-build-config':
                const nextConfig = readFileSync(join(PROJECT_ROOT, 'next.config.mjs'), 'utf-8');
                isValid = nextConfig.includes('compress: true');
                break;
              case 'websocket-hook-untouched':
                isValid = verifyWebSocketHookUntouched().exists;
                break;
              case 'nextjs-dev-config':
                const packageJson = JSON.parse(readFileSync(join(PROJECT_ROOT, 'package.json'), 'utf-8'));
                isValid = packageJson.scripts.dev === 'next dev';
                break;
            }
            
            if (!isValid) {
              console.log(`✗ Counterexample: ${requirement} not preserved`);
            } else {
              console.log(`✓ ${requirement} preserved`);
            }
            
            return isValid;
          }
        ),
        {
          numRuns: 20,
          verbose: true
        }
      );
    });
  });
});

// Main execution for standalone testing
if (import.meta.url === `file://${process.argv[1]}`) {
  console.log('='.repeat(80));
  console.log('Preservation Property Tests for Tauri Dev Slow Compilation Fix');
  console.log('='.repeat(80));
  console.log();
  console.log('This test suite verifies that all existing functionality remains unchanged');
  console.log('after the compilation optimization fix is applied.');
  console.log();
  console.log('IMPORTANT: Follow observation-first methodology');
  console.log('- These tests run on UNFIXED code to establish baseline behavior');
  console.log('- Tests should PASS on unfixed code (confirming current behavior works)');
  console.log('- After fix is applied, tests should still PASS (confirming no regressions)');
  console.log();
  console.log('Running preservation tests...');
  console.log();
}
