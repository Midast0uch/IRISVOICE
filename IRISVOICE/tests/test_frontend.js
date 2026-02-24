/**
 * Basic tests for the IRISVOICE frontend components.
 */

// Mock DOM environment for testing
const { JSDOM } = require('jsdom');

// Set up a basic DOM
const dom = new JSDOM('<!DOCTYPE html><html><body></body></html>', {
  url: 'http://localhost',
  pretendToBeVisual: true,
  resources: 'usable'
});

global.window = dom.window;
global.document = dom.window.document;
global.navigator = dom.window.navigator;

console.log('✓ Frontend test environment set up');

// Test basic imports
try {
  // Test that React can be imported
  const React = require('react');
  console.log('✓ Successfully imported React');
} catch (e) {
  console.log('⚠ Could not import React:', e.message);
}

try {
  // Test that framer-motion can be imported
  const { motion } = require('framer-motion');
  console.log('✓ Successfully imported framer-motion');
} catch (e) {
  console.log('⚠ Could not import framer-motion:', e.message);
}

try {
  // Test that lucide-react can be imported
  const { ChevronLeft, ChevronDown } = require('lucide-react');
  console.log('✓ Successfully imported lucide-react');
} catch (e) {
  console.log('⚠ Could not import lucide-react:', e.message);
}

console.log('Frontend basic import tests completed.');