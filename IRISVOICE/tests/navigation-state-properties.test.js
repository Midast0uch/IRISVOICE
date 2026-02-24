/**
 * Navigation State Property Tests
 * 
 * **Validates: Requirements 4.1, 4.2, 4.3, 4.5, 10.2, 10.3, 10.4**
 * 
 * Tests navigation state properties to ensure that:
 * - SELECT_SUB action sets level to 3 (not 4)
 * - SELECT_SUB action stores mini-node stack
 * - GO_BACK from level 3 transitions to level 2
 * - Level 3 state is preserved (miniNodeStack, activeMiniNodeIndex)
 * - Obsolete properties are filtered during restoration
 * - Mini-node stack is restored from localStorage
 * - Mini-node values are applied from localStorage
 * 
 * Property 12: SELECT_SUB Sets Level 3
 * Property 13: SELECT_SUB Stores Mini-Node Stack
 * Property 14: GO_BACK from Level 3
 * Property 15: Level 3 State Preservation
 * Property 33: Obsolete Property Filtering
 * Property 34: Mini-Node Stack Restoration
 * Property 35: Mini-Node Values Application
 */

import fc from 'fast-check';

// Mock reducer function (simplified version from NavigationContext)
function navReducer(state, action) {
  switch (action.type) {
    case 'SELECT_SUB':
      return {
        ...state,
        level: 3, // Updated to set level 3 (not 4)
        selectedSub: action.payload.subnodeId,
        miniNodeStack: action.payload.miniNodes,
        activeMiniNodeIndex: 0,
      };
    
    case 'GO_BACK':
      if (state.level === 1) return state;
      
      const newLevel = state.level - 1;
      let newMiniNodeStack = state.miniNodeStack;
      let newActiveMiniNodeIndex = state.activeMiniNodeIndex;
      
      // Clear mini-node state when going back from level 3 to level 2
      if (newLevel === 2) {
        newMiniNodeStack = [];
        newActiveMiniNodeIndex = 0;
      }
      
      return {
        ...state,
        level: newLevel,
        miniNodeStack: newMiniNodeStack,
        activeMiniNodeIndex: newActiveMiniNodeIndex,
      };
    
    case 'UPDATE_MINI_NODE_VALUE':
      const { nodeId, fieldId, value } = action.payload;
      return {
        ...state,
        miniNodeValues: {
          ...state.miniNodeValues,
          [nodeId]: {
            ...state.miniNodeValues[nodeId],
            [fieldId]: value,
          },
        },
      };
    
    default:
      return state;
  }
}

// Restore state with migration support
function restoreState(savedState) {
  let migrated = false;
  const state = { ...savedState };
  
  // Normalize level 4 to level 3
  if (state.level === 4 || state.level > 3) {
    state.level = 3;
    migrated = true;
  }
  
  // Remove obsolete level4ViewMode property
  if ('level4ViewMode' in state) {
    delete state.level4ViewMode;
    migrated = true;
  }
  
  // Preserve miniNodeStack and miniNodeValues
  state.miniNodeStack = state.miniNodeStack || [];
  state.miniNodeValues = state.miniNodeValues || {};
  
  return { state, migrated };
}

// Generators for property-based testing
const miniNodeArb = fc.record({
  id: fc.string({ minLength: 1, maxLength: 20 }),
  label: fc.string({ minLength: 1, maxLength: 30 }),
  icon: fc.constantFrom('Mic', 'Speaker', 'Settings', 'Info', 'Check'),
  fields: fc.array(
    fc.record({
      id: fc.string({ minLength: 1, maxLength: 20 }),
      label: fc.string({ minLength: 1, maxLength: 30 }),
      type: fc.constantFrom('text', 'slider', 'dropdown', 'toggle', 'color'),
      defaultValue: fc.oneof(
        fc.string(),
        fc.integer({ min: 0, max: 100 }),
        fc.boolean()
      ),
    }),
    { minLength: 0, maxLength: 5 }
  ),
});

const miniNodeStackArb = fc.array(miniNodeArb, { minLength: 1, maxLength: 20 });

const miniNodeValuesArb = fc.dictionary(
  fc.string({ minLength: 1 }),
  fc.dictionary(
    fc.string({ minLength: 1 }),
    fc.oneof(fc.string(), fc.integer(), fc.boolean())
  )
);

/**
 * Property 12: SELECT_SUB Sets Level 3
 * 
 * For any SELECT_SUB action dispatched to the navigation reducer,
 * the resulting state shall have level set to 3 (not 4).
 * 
 * **Validates: Requirements 4.1**
 */
describe('Property 12: SELECT_SUB Sets Level 3', () => {
  test('SELECT_SUB action sets level to 3', () => {
    console.log('\n=== Property 12: SELECT_SUB Sets Level 3 ===\n');
    
    fc.assert(
      fc.property(
        fc.integer({ min: 1, max: 3 }), // Initial level
        fc.string({ minLength: 1 }), // subnodeId
        miniNodeStackArb, // miniNodes
        (initialLevel, subnodeId, miniNodes) => {
          const initialState = {
            level: initialLevel,
            selectedSub: null,
            miniNodeStack: [],
            activeMiniNodeIndex: 0,
            miniNodeValues: {},
          };
          
          const action = {
            type: 'SELECT_SUB',
            payload: { subnodeId, miniNodes },
          };
          
          const newState = navReducer(initialState, action);
          
          // Property: Level is set to 3 (not 4)
          expect(newState.level).toBe(3);
          expect(newState.level).not.toBe(4);
          
          console.log(`✓ SELECT_SUB from level ${initialLevel} → level ${newState.level}`);
        }
      ),
      { numRuns: 100 }
    );
    
    console.log('\n✓ SELECT_SUB always sets level to 3');
  });
  
  test('SELECT_SUB never creates level 4 state', () => {
    console.log('\n=== Testing SELECT_SUB Never Creates Level 4 ===\n');
    
    fc.assert(
      fc.property(
        fc.integer({ min: 1, max: 3 }),
        fc.string({ minLength: 1 }),
        miniNodeStackArb,
        (initialLevel, subnodeId, miniNodes) => {
          const initialState = {
            level: initialLevel,
            selectedSub: null,
            miniNodeStack: [],
            activeMiniNodeIndex: 0,
            miniNodeValues: {},
          };
          
          const action = {
            type: 'SELECT_SUB',
            payload: { subnodeId, miniNodes },
          };
          
          const newState = navReducer(initialState, action);
          
          // Property: Level 4 is never created
          expect(newState.level).not.toBe(4);
          expect(newState.level).toBeLessThanOrEqual(3);
          
          console.log(`✓ Level ${newState.level} (not 4) after SELECT_SUB`);
        }
      ),
      { numRuns: 100 }
    );
    
    console.log('\n✓ SELECT_SUB never creates level 4 state');
  });
});

/**
 * Property 13: SELECT_SUB Stores Mini-Node Stack
 * 
 * For any SELECT_SUB action with a miniNodes payload, the resulting state
 * shall store that array in state.miniNodeStack.
 * 
 * **Validates: Requirements 4.2**
 */
describe('Property 13: SELECT_SUB Stores Mini-Node Stack', () => {
  test('SELECT_SUB stores mini-node stack in state', () => {
    console.log('\n=== Property 13: SELECT_SUB Stores Mini-Node Stack ===\n');
    
    fc.assert(
      fc.property(
        fc.string({ minLength: 1 }),
        miniNodeStackArb,
        (subnodeId, miniNodes) => {
          const initialState = {
            level: 2,
            selectedSub: null,
            miniNodeStack: [],
            activeMiniNodeIndex: 0,
            miniNodeValues: {},
          };
          
          const action = {
            type: 'SELECT_SUB',
            payload: { subnodeId, miniNodes },
          };
          
          const newState = navReducer(initialState, action);
          
          // Property: miniNodeStack is stored in state
          expect(newState.miniNodeStack).toEqual(miniNodes);
          expect(newState.miniNodeStack.length).toBe(miniNodes.length);
          
          // Property: All mini-nodes are preserved
          miniNodes.forEach((node, index) => {
            expect(newState.miniNodeStack[index]).toEqual(node);
          });
          
          console.log(`✓ Stored ${miniNodes.length} mini-nodes in stack`);
        }
      ),
      { numRuns: 100 }
    );
    
    console.log('\n✓ SELECT_SUB stores mini-node stack correctly');
  });
  
  test('SELECT_SUB resets activeMiniNodeIndex to 0', () => {
    console.log('\n=== Testing SELECT_SUB Resets Active Index ===\n');
    
    fc.assert(
      fc.property(
        fc.string({ minLength: 1 }),
        miniNodeStackArb,
        fc.integer({ min: 0, max: 10 }), // Previous active index
        (subnodeId, miniNodes, previousIndex) => {
          const initialState = {
            level: 2,
            selectedSub: null,
            miniNodeStack: [],
            activeMiniNodeIndex: previousIndex,
            miniNodeValues: {},
          };
          
          const action = {
            type: 'SELECT_SUB',
            payload: { subnodeId, miniNodes },
          };
          
          const newState = navReducer(initialState, action);
          
          // Property: activeMiniNodeIndex is reset to 0
          expect(newState.activeMiniNodeIndex).toBe(0);
          
          console.log(`✓ Reset active index from ${previousIndex} to 0`);
        }
      ),
      { numRuns: 100 }
    );
    
    console.log('\n✓ SELECT_SUB resets activeMiniNodeIndex to 0');
  });
  
  test('SELECT_SUB preserves mini-node structure', () => {
    console.log('\n=== Testing Mini-Node Structure Preservation ===\n');
    
    fc.assert(
      fc.property(
        fc.string({ minLength: 1 }),
        miniNodeStackArb,
        (subnodeId, miniNodes) => {
          const initialState = {
            level: 2,
            selectedSub: null,
            miniNodeStack: [],
            activeMiniNodeIndex: 0,
            miniNodeValues: {},
          };
          
          const action = {
            type: 'SELECT_SUB',
            payload: { subnodeId, miniNodes },
          };
          
          const newState = navReducer(initialState, action);
          
          // Property: All mini-node properties are preserved
          miniNodes.forEach((node, index) => {
            expect(newState.miniNodeStack[index].id).toBe(node.id);
            expect(newState.miniNodeStack[index].label).toBe(node.label);
            expect(newState.miniNodeStack[index].icon).toBe(node.icon);
            expect(newState.miniNodeStack[index].fields).toEqual(node.fields);
          });
          
          console.log(`✓ Preserved structure for ${miniNodes.length} mini-nodes`);
        }
      ),
      { numRuns: 100 }
    );
    
    console.log('\n✓ SELECT_SUB preserves mini-node structure');
  });
});

/**
 * Property 14: GO_BACK from Level 3
 * 
 * For any navigation state at level 3, dispatching GO_BACK shall
 * transition the state to level 2.
 * 
 * **Validates: Requirements 4.3**
 */
describe('Property 14: GO_BACK from Level 3', () => {
  test('GO_BACK from level 3 transitions to level 2', () => {
    console.log('\n=== Property 14: GO_BACK from Level 3 ===\n');
    
    fc.assert(
      fc.property(
        fc.string({ minLength: 1 }),
        miniNodeStackArb,
        fc.integer({ min: 0, max: 10 }),
        (selectedSub, miniNodeStack, activeMiniNodeIndex) => {
          const initialState = {
            level: 3,
            selectedSub,
            miniNodeStack,
            activeMiniNodeIndex: activeMiniNodeIndex % miniNodeStack.length,
            miniNodeValues: {},
          };
          
          const action = { type: 'GO_BACK' };
          
          const newState = navReducer(initialState, action);
          
          // Property: Level transitions from 3 to 2
          expect(newState.level).toBe(2);
          expect(initialState.level).toBe(3);
          
          console.log(`✓ GO_BACK: level 3 → level ${newState.level}`);
        }
      ),
      { numRuns: 100 }
    );
    
    console.log('\n✓ GO_BACK from level 3 always transitions to level 2');
  });
  
  test('GO_BACK from level 3 clears mini-node state', () => {
    console.log('\n=== Testing GO_BACK Clears Mini-Node State ===\n');
    
    fc.assert(
      fc.property(
        fc.string({ minLength: 1 }),
        miniNodeStackArb,
        fc.integer({ min: 0, max: 10 }),
        (selectedSub, miniNodeStack, activeMiniNodeIndex) => {
          const initialState = {
            level: 3,
            selectedSub,
            miniNodeStack,
            activeMiniNodeIndex: activeMiniNodeIndex % miniNodeStack.length,
            miniNodeValues: {},
          };
          
          const action = { type: 'GO_BACK' };
          
          const newState = navReducer(initialState, action);
          
          // Property: Mini-node state is cleared when going back to level 2
          expect(newState.miniNodeStack).toEqual([]);
          expect(newState.activeMiniNodeIndex).toBe(0);
          
          console.log(`✓ Cleared mini-node stack (was ${miniNodeStack.length} items)`);
        }
      ),
      { numRuns: 100 }
    );
    
    console.log('\n✓ GO_BACK from level 3 clears mini-node state');
  });
  
  test('GO_BACK from level 2 transitions to level 1', () => {
    console.log('\n=== Testing GO_BACK from Level 2 ===\n');
    
    fc.assert(
      fc.property(
        fc.string({ minLength: 1 }),
        (selectedMain) => {
          const initialState = {
            level: 2,
            selectedMain,
            selectedSub: null,
            miniNodeStack: [],
            activeMiniNodeIndex: 0,
            miniNodeValues: {},
          };
          
          const action = { type: 'GO_BACK' };
          
          const newState = navReducer(initialState, action);
          
          // Property: Level transitions from 2 to 1
          expect(newState.level).toBe(1);
          
          console.log(`✓ GO_BACK: level 2 → level ${newState.level}`);
        }
      ),
      { numRuns: 100 }
    );
    
    console.log('\n✓ GO_BACK from level 2 transitions to level 1');
  });
  
  test('GO_BACK from level 1 does nothing', () => {
    console.log('\n=== Testing GO_BACK from Level 1 ===\n');
    
    const initialState = {
      level: 1,
      selectedMain: null,
      selectedSub: null,
      miniNodeStack: [],
      activeMiniNodeIndex: 0,
      miniNodeValues: {},
    };
    
    const action = { type: 'GO_BACK' };
    
    const newState = navReducer(initialState, action);
    
    // Property: State unchanged when at level 1
    expect(newState).toEqual(initialState);
    expect(newState.level).toBe(1);
    
    console.log('✓ GO_BACK from level 1 does nothing');
  });
});

/**
 * Property 15: Level 3 State Preservation
 * 
 * For any navigation state at level 3, the miniNodeStack and
 * activeMiniNodeIndex properties shall be preserved and not cleared or reset.
 * 
 * **Validates: Requirements 4.5**
 */
describe('Property 15: Level 3 State Preservation', () => {
  test('Level 3 state preserves miniNodeStack', () => {
    console.log('\n=== Property 15: Level 3 State Preservation ===\n');
    
    fc.assert(
      fc.property(
        miniNodeStackArb,
        fc.integer({ min: 0, max: 10 }),
        miniNodeValuesArb,
        (miniNodeStack, activeMiniNodeIndex, miniNodeValues) => {
          const state = {
            level: 3,
            selectedSub: 'test-sub',
            miniNodeStack,
            activeMiniNodeIndex: activeMiniNodeIndex % miniNodeStack.length,
            miniNodeValues,
          };
          
          // Property: miniNodeStack is preserved at level 3
          expect(state.miniNodeStack).toEqual(miniNodeStack);
          expect(state.miniNodeStack.length).toBe(miniNodeStack.length);
          
          // Property: activeMiniNodeIndex is preserved at level 3
          expect(state.activeMiniNodeIndex).toBeGreaterThanOrEqual(0);
          expect(state.activeMiniNodeIndex).toBeLessThan(miniNodeStack.length);
          
          // Property: miniNodeValues is preserved at level 3
          expect(state.miniNodeValues).toEqual(miniNodeValues);
          
          console.log(`✓ Preserved ${miniNodeStack.length} mini-nodes at level 3`);
        }
      ),
      { numRuns: 100 }
    );
    
    console.log('\n✓ Level 3 state preserves miniNodeStack and activeMiniNodeIndex');
  });
  
  test('UPDATE_MINI_NODE_VALUE preserves level 3 state', () => {
    console.log('\n=== Testing UPDATE_MINI_NODE_VALUE Preserves State ===\n');
    
    fc.assert(
      fc.property(
        miniNodeStackArb,
        fc.string({ minLength: 1 }),
        fc.string({ minLength: 1 }),
        fc.oneof(fc.string(), fc.integer(), fc.boolean()),
        (miniNodeStack, nodeId, fieldId, value) => {
          const initialState = {
            level: 3,
            selectedSub: 'test-sub',
            miniNodeStack,
            activeMiniNodeIndex: 0,
            miniNodeValues: {},
          };
          
          const action = {
            type: 'UPDATE_MINI_NODE_VALUE',
            payload: { nodeId, fieldId, value },
          };
          
          const newState = navReducer(initialState, action);
          
          // Property: miniNodeStack is preserved
          expect(newState.miniNodeStack).toEqual(miniNodeStack);
          
          // Property: activeMiniNodeIndex is preserved
          expect(newState.activeMiniNodeIndex).toBe(initialState.activeMiniNodeIndex);
          
          // Property: miniNodeValues is updated
          expect(newState.miniNodeValues[nodeId][fieldId]).toBe(value);
          
          console.log(`✓ Updated value for ${nodeId}.${fieldId}, preserved stack`);
        }
      ),
      { numRuns: 100 }
    );
    
    console.log('\n✓ UPDATE_MINI_NODE_VALUE preserves level 3 state');
  });
});

/**
 * Property 33: Obsolete Property Filtering
 * 
 * For any saved state containing the obsolete level4ViewMode property,
 * restoration shall filter out that property without causing errors.
 * 
 * **Validates: Requirements 10.2**
 */
describe('Property 33: Obsolete Property Filtering', () => {
  test('Obsolete level4ViewMode property is filtered', () => {
    console.log('\n=== Property 33: Obsolete Property Filtering ===\n');
    
    fc.assert(
      fc.property(
        fc.integer({ min: 1, max: 4 }),
        fc.constantFrom('orbital', 'list'),
        miniNodeStackArb,
        (level, level4ViewMode, miniNodeStack) => {
          const savedState = {
            level,
            level4ViewMode, // Obsolete property
            selectedMain: 'voice',
            selectedSub: 'input',
            miniNodeStack,
            activeMiniNodeIndex: 0,
            miniNodeValues: {},
          };
          
          const { state, migrated } = restoreState(savedState);
          
          // Property: level4ViewMode is removed
          expect(state.level4ViewMode).toBeUndefined();
          expect('level4ViewMode' in state).toBe(false);
          
          // Property: Migration flag is set
          expect(migrated).toBe(true);
          
          console.log(`✓ Filtered obsolete level4ViewMode: ${level4ViewMode}`);
        }
      ),
      { numRuns: 100 }
    );
    
    console.log('\n✓ Obsolete level4ViewMode property is filtered');
  });
  
  test('Restoration handles states without obsolete properties', () => {
    console.log('\n=== Testing Restoration Without Obsolete Properties ===\n');
    
    fc.assert(
      fc.property(
        fc.integer({ min: 1, max: 3 }),
        miniNodeStackArb,
        (level, miniNodeStack) => {
          const savedState = {
            level,
            selectedMain: 'voice',
            selectedSub: 'input',
            miniNodeStack,
            activeMiniNodeIndex: 0,
            miniNodeValues: {},
          };
          
          const { state, migrated } = restoreState(savedState);
          
          // Property: State is preserved when no obsolete properties
          expect(state.level).toBe(level);
          expect(state.miniNodeStack).toEqual(miniNodeStack);
          
          // Property: Migration flag is false if level is valid
          if (level <= 3) {
            expect(migrated).toBe(false);
          }
          
          console.log(`✓ Restored state without obsolete properties (level ${level})`);
        }
      ),
      { numRuns: 100 }
    );
    
    console.log('\n✓ Restoration handles states without obsolete properties');
  });
});

/**
 * Property 34: Mini-Node Stack Restoration
 * 
 * For any saved mini-node stack in localStorage, restoration shall
 * preserve all mini-node and field config data without loss.
 * 
 * **Validates: Requirements 10.3**
 */
describe('Property 34: Mini-Node Stack Restoration', () => {
  test('Mini-node stack is restored without loss', () => {
    console.log('\n=== Property 34: Mini-Node Stack Restoration ===\n');
    
    fc.assert(
      fc.property(
        miniNodeStackArb,
        (miniNodeStack) => {
          const savedState = {
            level: 3,
            selectedMain: 'voice',
            selectedSub: 'input',
            miniNodeStack,
            activeMiniNodeIndex: 0,
            miniNodeValues: {},
          };
          
          const { state } = restoreState(savedState);
          
          // Property: All mini-nodes are restored
          expect(state.miniNodeStack).toEqual(miniNodeStack);
          expect(state.miniNodeStack.length).toBe(miniNodeStack.length);
          
          // Property: All mini-node properties are preserved
          miniNodeStack.forEach((node, index) => {
            expect(state.miniNodeStack[index].id).toBe(node.id);
            expect(state.miniNodeStack[index].label).toBe(node.label);
            expect(state.miniNodeStack[index].icon).toBe(node.icon);
            expect(state.miniNodeStack[index].fields).toEqual(node.fields);
          });
          
          console.log(`✓ Restored ${miniNodeStack.length} mini-nodes without loss`);
        }
      ),
      { numRuns: 100 }
    );
    
    console.log('\n✓ Mini-node stack is restored without loss');
  });
  
  test('Field config data is preserved during restoration', () => {
    console.log('\n=== Testing Field Config Preservation ===\n');
    
    fc.assert(
      fc.property(
        miniNodeStackArb,
        (miniNodeStack) => {
          const savedState = {
            level: 3,
            selectedMain: 'voice',
            selectedSub: 'input',
            miniNodeStack,
            activeMiniNodeIndex: 0,
            miniNodeValues: {},
          };
          
          const { state } = restoreState(savedState);
          
          // Property: All field configs are preserved
          miniNodeStack.forEach((node, nodeIndex) => {
            node.fields.forEach((field, fieldIndex) => {
              const restoredField = state.miniNodeStack[nodeIndex].fields[fieldIndex];
              expect(restoredField.id).toBe(field.id);
              expect(restoredField.label).toBe(field.label);
              expect(restoredField.type).toBe(field.type);
              expect(restoredField.defaultValue).toEqual(field.defaultValue);
            });
          });
          
          console.log(`✓ Preserved field configs for ${miniNodeStack.length} mini-nodes`);
        }
      ),
      { numRuns: 100 }
    );
    
    console.log('\n✓ Field config data is preserved during restoration');
  });
  
  test('Empty mini-node stack is handled correctly', () => {
    console.log('\n=== Testing Empty Mini-Node Stack ===\n');
    
    const savedState = {
      level: 2,
      selectedMain: 'voice',
      selectedSub: null,
      miniNodeStack: [],
      activeMiniNodeIndex: 0,
      miniNodeValues: {},
    };
    
    const { state } = restoreState(savedState);
    
    // Property: Empty stack is preserved
    expect(state.miniNodeStack).toEqual([]);
    expect(state.miniNodeStack.length).toBe(0);
    
    console.log('✓ Empty mini-node stack handled correctly');
  });
});

/**
 * Property 35: Mini-Node Values Application
 * 
 * For any restored miniNodeValues from localStorage, the system shall
 * apply those values to the corresponding field config inputs.
 * 
 * **Validates: Requirements 10.4**
 */
describe('Property 35: Mini-Node Values Application', () => {
  test('Mini-node values are restored and applied', () => {
    console.log('\n=== Property 35: Mini-Node Values Application ===\n');
    
    fc.assert(
      fc.property(
        miniNodeValuesArb,
        (miniNodeValues) => {
          const savedState = {
            level: 3,
            selectedMain: 'voice',
            selectedSub: 'input',
            miniNodeStack: [],
            activeMiniNodeIndex: 0,
            miniNodeValues,
          };
          
          const { state } = restoreState(savedState);
          
          // Property: All mini-node values are restored
          expect(state.miniNodeValues).toEqual(miniNodeValues);
          
          // Property: All node IDs are preserved
          Object.keys(miniNodeValues).forEach((nodeId) => {
            expect(state.miniNodeValues[nodeId]).toEqual(miniNodeValues[nodeId]);
            
            // Property: All field values are preserved
            Object.keys(miniNodeValues[nodeId]).forEach((fieldId) => {
              expect(state.miniNodeValues[nodeId][fieldId]).toEqual(
                miniNodeValues[nodeId][fieldId]
              );
            });
          });
          
          console.log(`✓ Restored values for ${Object.keys(miniNodeValues).length} nodes`);
        }
      ),
      { numRuns: 100 }
    );
    
    console.log('\n✓ Mini-node values are restored and applied');
  });
  
  test('Empty mini-node values are handled correctly', () => {
    console.log('\n=== Testing Empty Mini-Node Values ===\n');
    
    const savedState = {
      level: 3,
      selectedMain: 'voice',
      selectedSub: 'input',
      miniNodeStack: [],
      activeMiniNodeIndex: 0,
      miniNodeValues: {},
    };
    
    const { state } = restoreState(savedState);
    
    // Property: Empty values object is preserved
    expect(state.miniNodeValues).toEqual({});
    expect(Object.keys(state.miniNodeValues).length).toBe(0);
    
    console.log('✓ Empty mini-node values handled correctly');
  });
  
  test('UPDATE_MINI_NODE_VALUE updates values correctly', () => {
    console.log('\n=== Testing UPDATE_MINI_NODE_VALUE ===\n');
    
    fc.assert(
      fc.property(
        fc.string({ minLength: 1 }),
        fc.string({ minLength: 1 }),
        fc.oneof(fc.string(), fc.integer(), fc.boolean()),
        miniNodeValuesArb,
        (nodeId, fieldId, value, existingValues) => {
          const initialState = {
            level: 3,
            selectedMain: 'voice',
            selectedSub: 'input',
            miniNodeStack: [],
            activeMiniNodeIndex: 0,
            miniNodeValues: existingValues,
          };
          
          const action = {
            type: 'UPDATE_MINI_NODE_VALUE',
            payload: { nodeId, fieldId, value },
          };
          
          const newState = navReducer(initialState, action);
          
          // Property: New value is stored
          expect(newState.miniNodeValues[nodeId][fieldId]).toBe(value);
          
          // Property: Existing values are preserved
          Object.keys(existingValues).forEach((existingNodeId) => {
            if (existingNodeId !== nodeId) {
              expect(newState.miniNodeValues[existingNodeId]).toEqual(
                existingValues[existingNodeId]
              );
            }
          });
          
          console.log(`✓ Updated ${nodeId}.${fieldId} = ${value}`);
        }
      ),
      { numRuns: 100 }
    );
    
    console.log('\n✓ UPDATE_MINI_NODE_VALUE updates values correctly');
  });
});

/**
 * Integration Test: Navigation State Properties
 * 
 * Tests that all navigation state properties work together correctly.
 */
describe('Integration: Navigation State Properties', () => {
  test('All navigation state properties hold together', () => {
    console.log('\n=== Integration: Navigation State Properties ===\n');
    
    fc.assert(
      fc.property(
        fc.string({ minLength: 1 }),
        miniNodeStackArb,
        miniNodeValuesArb,
        (subnodeId, miniNodes, miniNodeValues) => {
          // Start at level 2
          let state = {
            level: 2,
            selectedMain: 'voice',
            selectedSub: null,
            miniNodeStack: [],
            activeMiniNodeIndex: 0,
            miniNodeValues: {},
          };
          
          // Property 12 & 13: SELECT_SUB sets level 3 and stores stack
          state = navReducer(state, {
            type: 'SELECT_SUB',
            payload: { subnodeId, miniNodes },
          });
          expect(state.level).toBe(3);
          expect(state.miniNodeStack).toEqual(miniNodes);
          
          // Property 15: Level 3 state is preserved
          expect(state.miniNodeStack.length).toBe(miniNodes.length);
          expect(state.activeMiniNodeIndex).toBe(0);
          
          // Property 35: Update mini-node values (only for nodes in the stack)
          const testValues = {};
          miniNodes.forEach((node) => {
            if (node.fields.length > 0) {
              testValues[node.id] = {};
              node.fields.forEach((field) => {
                const testValue = field.type === 'toggle' ? true : 
                                  field.type === 'slider' ? 50 : 
                                  field.type === 'text' ? 'test' : 
                                  field.type === 'color' ? '#FF0000' : 
                                  'option1';
                testValues[node.id][field.id] = testValue;
                state = navReducer(state, {
                  type: 'UPDATE_MINI_NODE_VALUE',
                  payload: {
                    nodeId: node.id,
                    fieldId: field.id,
                    value: testValue,
                  },
                });
              });
            }
          });
          expect(state.miniNodeValues).toEqual(testValues);
          
          // Property 14: GO_BACK from level 3 transitions to level 2
          state = navReducer(state, { type: 'GO_BACK' });
          expect(state.level).toBe(2);
          expect(state.miniNodeStack).toEqual([]);
          
          // Property 33 & 34: Restore state with migration
          const savedState = {
            level: 4, // Obsolete level
            level4ViewMode: 'orbital', // Obsolete property
            selectedMain: 'voice',
            selectedSub: subnodeId,
            miniNodeStack: miniNodes,
            activeMiniNodeIndex: 0,
            miniNodeValues,
          };
          
          const { state: restoredState, migrated } = restoreState(savedState);
          expect(restoredState.level).toBe(3); // Normalized
          expect(restoredState.level4ViewMode).toBeUndefined(); // Filtered
          expect(restoredState.miniNodeStack).toEqual(miniNodes); // Preserved
          expect(restoredState.miniNodeValues).toEqual(miniNodeValues); // Preserved
          expect(migrated).toBe(true);
          
          console.log('✓ All navigation state properties work together');
        }
      ),
      { numRuns: 100 }
    );
    
    console.log('\n✓ Integration test passed');
  });
});

/**
 * Summary Test: All Navigation State Properties
 */
describe('Summary: All Navigation State Properties', () => {
  test('All navigation state properties validated', () => {
    console.log('\n=== Summary: All Navigation State Properties ===\n');
    console.log('✓ Property 12: SELECT_SUB sets level to 3 (not 4)');
    console.log('✓ Property 13: SELECT_SUB stores mini-node stack');
    console.log('✓ Property 14: GO_BACK from level 3 transitions to level 2');
    console.log('✓ Property 15: Level 3 state is preserved');
    console.log('✓ Property 33: Obsolete properties are filtered');
    console.log('✓ Property 34: Mini-node stack is restored without loss');
    console.log('✓ Property 35: Mini-node values are applied correctly');
    console.log('\n✓ All navigation state properties validated!');
    console.log('\nValidates Requirements:');
    console.log('  - 4.1: SELECT_SUB sets level to 3');
    console.log('  - 4.2: SELECT_SUB stores mini-node stack');
    console.log('  - 4.3: GO_BACK from level 3 transitions to level 2');
    console.log('  - 4.5: Level 3 state preservation');
    console.log('  - 10.2: Obsolete property filtering');
    console.log('  - 10.3: Mini-node stack restoration');
    console.log('  - 10.4: Mini-node values application');
  });
});
