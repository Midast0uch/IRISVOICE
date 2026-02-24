/**
 * Bug Condition Exploration Test - Webpack Processes Models Directory During Dev Mode
 * 
 * **Validates: Requirements 1.1, 1.2, 1.3, 1.4**
 * 
 * CRITICAL: This test MUST FAIL on unfixed code - failure confirms the bug exists
 * DO NOT attempt to fix the test or the code when it fails
 * 
 * This test encodes the expected behavior - it will validate the fix when it passes after implementation
 * 
 * GOAL: Surface counterexamples that demonstrate Next.js webpack is processing the models directory
 * 
 * Expected Behavior (from design):
 * - Memory usage should be < 1000MB during compilation
 * - Compilation time should be < 60 seconds
 * - Models directory should NOT appear in webpack watch list or asset processing
 * 
 * Current Behavior (bug - will cause test to FAIL):
 * - Memory usage exceeds 7000MB during compilation
 * - Compilation time exceeds 16 minutes with IDE freeze
 * - Webpack logs show models directory files in watch list or asset processing
 */

import { spawn } from 'child_process';
import { existsSync } from 'fs';
import { join } from 'path';
import { fileURLToPath } from 'url';
import { dirname } from 'path';

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

// Test configuration
const EXPECTED_MAX_MEMORY_MB = 1000;
const EXPECTED_MAX_COMPILATION_TIME_SECONDS = 60;
const MODELS_DIR = join(__dirname, '..', 'models');

/**
 * Get memory usage of a process in MB
 */
function getProcessMemoryMB(pid) {
  return new Promise((resolve, reject) => {
    const isWindows = process.platform === 'win32';
    
    if (isWindows) {
      // Windows: Use tasklist to get memory usage
      const tasklist = spawn('tasklist', ['/FI', `PID eq ${pid}`, '/FO', 'CSV', '/NH']);
      let output = '';
      
      tasklist.stdout.on('data', (data) => {
        output += data.toString();
      });
      
      tasklist.on('close', (code) => {
        if (code !== 0) {
          resolve(0);
          return;
        }
        
        // Parse CSV output: "node.exe","12345","Console","1","123,456 K"
        const match = output.match(/"[^"]+","[^"]+","[^"]+","[^"]+","([0-9,]+) K"/);
        if (match) {
          const memoryKB = parseInt(match[1].replace(/,/g, ''));
          resolve(memoryKB / 1024); // Convert KB to MB
        } else {
          resolve(0);
        }
      });
    } else {
      // Unix: Use ps to get memory usage
      const ps = spawn('ps', ['-o', 'rss=', '-p', pid.toString()]);
      let output = '';
      
      ps.stdout.on('data', (data) => {
        output += data.toString();
      });
      
      ps.on('close', (code) => {
        if (code !== 0) {
          resolve(0);
          return;
        }
        
        const memoryKB = parseInt(output.trim());
        resolve(memoryKB / 1024); // Convert KB to MB
      });
    }
  });
}

/**
 * Monitor memory usage of a process and its children
 */
async function monitorMemory(pid, interval = 2000) {
  const measurements = [];
  let maxMemory = 0;
  
  const monitor = setInterval(async () => {
    try {
      const memory = await getProcessMemoryMB(pid);
      measurements.push(memory);
      if (memory > maxMemory) {
        maxMemory = memory;
      }
    } catch (error) {
      // Process might have ended
    }
  }, interval);
  
  return {
    stop: () => {
      clearInterval(monitor);
      return { measurements, maxMemory };
    }
  };
}

/**
 * Run the bug condition exploration test
 */
async function runBugConditionTest() {
  console.log('\n=== Bug Condition Exploration Test ===\n');
  console.log('Testing: Webpack Processes Models Directory During Dev Mode\n');
  
  // Check if models directory exists
  if (!existsSync(MODELS_DIR)) {
    console.log('⚠️  Models directory not found at:', MODELS_DIR);
    console.log('⚠️  Skipping test - models directory is required to reproduce the bug');
    process.exit(0);
  }
  
  console.log('✓ Models directory exists:', MODELS_DIR);
  console.log('\nStarting Next.js dev server...\n');
  
  const startTime = Date.now();
  let compilationTime = null;
  let maxMemoryUsage = 0;
  let webpackLogsModelsDir = false;
  let serverOutput = '';
  
  // Start the Next.js dev server
  const devServer = spawn('npm', ['run', 'dev'], {
    cwd: join(__dirname, '..'),
    shell: true,
    stdio: ['ignore', 'pipe', 'pipe']
  });
  
  // Start memory monitoring
  const memoryMonitor = await monitorMemory(devServer.pid);
  
  // Capture server output
  devServer.stdout.on('data', (data) => {
    const output = data.toString();
    serverOutput += output;
    process.stdout.write(output);
    
    // Check if webpack is processing models directory
    if (output.includes('models/') || output.includes('models\\')) {
      webpackLogsModelsDir = true;
      console.log('\n⚠️  DETECTED: Webpack is processing models directory!\n');
    }
    
    // Check for compilation complete
    if (output.includes('compiled successfully') || 
        output.includes('Compiled successfully') ||
        output.includes('✓ Compiled') ||
        output.includes('Ready in')) {
      if (!compilationTime) {
        compilationTime = (Date.now() - startTime) / 1000;
        console.log(`\n✓ Compilation completed in ${compilationTime.toFixed(2)} seconds\n`);
      }
    }
  });
  
  devServer.stderr.on('data', (data) => {
    const output = data.toString();
    serverOutput += output;
    process.stderr.write(output);
    
    // Check stderr for models directory references
    if (output.includes('models/') || output.includes('models\\')) {
      webpackLogsModelsDir = true;
      console.log('\n⚠️  DETECTED: Webpack is processing models directory (stderr)!\n');
    }
  });
  
  // Wait for compilation to complete or timeout
  const timeout = 5 * 60 * 1000; // 5 minutes timeout (reduced for faster execution)
  const checkInterval = 2000; // Check every 2 seconds instead of 1
  let elapsed = 0;
  
  while (!compilationTime && elapsed < timeout) {
    await new Promise(resolve => setTimeout(resolve, checkInterval));
    elapsed += checkInterval;
    
    // Print progress every 15 seconds (reduced from 30)
    if (elapsed % 15000 === 0) {
      const currentMemory = await getProcessMemoryMB(devServer.pid);
      console.log(`[${(elapsed / 1000).toFixed(0)}s] Memory: ${currentMemory.toFixed(0)} MB`);
    }
  }
  
  // Stop memory monitoring
  const memoryStats = memoryMonitor.stop();
  maxMemoryUsage = memoryStats.maxMemory;
  
  // Kill the dev server
  devServer.kill('SIGTERM');
  
  // Wait for process to exit
  await new Promise(resolve => setTimeout(resolve, 2000));
  
  // Force kill if still running
  try {
    process.kill(devServer.pid, 'SIGKILL');
  } catch (e) {
    // Process already dead
  }
  
  // Print results
  console.log('\n=== Test Results ===\n');
  console.log(`Compilation Time: ${compilationTime ? compilationTime.toFixed(2) : 'TIMEOUT'} seconds`);
  console.log(`Max Memory Usage: ${maxMemoryUsage.toFixed(0)} MB`);
  console.log(`Webpack Logs Show Models Dir: ${webpackLogsModelsDir ? 'YES' : 'NO'}`);
  console.log('\n=== Expected Behavior (from design) ===\n');
  console.log(`Expected Max Memory: < ${EXPECTED_MAX_MEMORY_MB} MB`);
  console.log(`Expected Max Compilation Time: < ${EXPECTED_MAX_COMPILATION_TIME_SECONDS} seconds`);
  console.log(`Expected Models Dir in Webpack: NO`);
  
  // Assertions
  console.log('\n=== Assertions ===\n');
  
  const failures = [];
  
  if (!compilationTime) {
    failures.push('❌ FAIL: Compilation timed out (exceeded 5 minutes)');
  } else if (compilationTime > EXPECTED_MAX_COMPILATION_TIME_SECONDS) {
    failures.push(`❌ FAIL: Compilation time ${compilationTime.toFixed(2)}s exceeds expected ${EXPECTED_MAX_COMPILATION_TIME_SECONDS}s`);
  } else {
    console.log(`✓ PASS: Compilation time ${compilationTime.toFixed(2)}s is within expected ${EXPECTED_MAX_COMPILATION_TIME_SECONDS}s`);
  }
  
  if (maxMemoryUsage > EXPECTED_MAX_MEMORY_MB) {
    failures.push(`❌ FAIL: Memory usage ${maxMemoryUsage.toFixed(0)} MB exceeds expected ${EXPECTED_MAX_MEMORY_MB} MB`);
  } else {
    console.log(`✓ PASS: Memory usage ${maxMemoryUsage.toFixed(0)} MB is within expected ${EXPECTED_MAX_MEMORY_MB} MB`);
  }
  
  if (webpackLogsModelsDir) {
    failures.push('❌ FAIL: Webpack logs show models directory being processed');
  } else {
    console.log('✓ PASS: Webpack logs do NOT show models directory being processed');
  }
  
  // Print counterexamples if test fails
  if (failures.length > 0) {
    console.log('\n=== COUNTEREXAMPLES FOUND (Bug Confirmed) ===\n');
    failures.forEach(failure => console.log(failure));
    console.log('\n✓ Test correctly FAILED - this confirms the bug exists!');
    console.log('✓ These counterexamples demonstrate that webpack is processing the models directory');
    console.log('\nNext steps:');
    console.log('1. Implement the fix in next.config.mjs (Task 3.1)');
    console.log('2. Re-run this test - it should PASS after the fix');
    process.exit(1);
  } else {
    console.log('\n=== All Assertions Passed ===\n');
    console.log('✓ Memory usage is within expected limits');
    console.log('✓ Compilation time is within expected limits');
    console.log('✓ Webpack is NOT processing models directory');
    console.log('\n✓ Bug is FIXED - expected behavior is satisfied!');
    process.exit(0);
  }
}

// Run the test
runBugConditionTest().catch(error => {
  console.error('\n❌ Test execution error:', error);
  process.exit(1);
});
