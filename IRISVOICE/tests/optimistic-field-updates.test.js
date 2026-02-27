/**
 * Tests for optimistic field updates with timestamp-based out-of-order handling
 * 
 * Requirements: 21.1, 21.2, 21.3, 21.6, 21.7
 */

describe('Optimistic Field Updates with Timestamps', () => {
  let mockWebSocket;
  let fieldValues;
  let fieldTimestamps;
  
  beforeEach(() => {
    fieldValues = {};
    fieldTimestamps = new Map();
    mockWebSocket = {
      send: () => {},
      readyState: 1 // WebSocket.OPEN
    };
  });
  
  const handleFieldUpdated = (payload) => {
    const { subnode_id, field_id, value, timestamp } = payload;
    const updateKey = `${subnode_id}:${field_id}`;
    
    // Handle out-of-order updates using timestamps
    if (timestamp !== undefined) {
      const existingTimestamp = fieldTimestamps.get(updateKey) || 0;
      
      // Only apply update if timestamp is newer
      if (timestamp < existingTimestamp) {
        // This is an out-of-order update, ignore it
        return false;
      }
      
      // Update timestamp tracker
      fieldTimestamps.set(updateKey, timestamp);
    }
    
    // Apply the update to state
    if (!fieldValues[subnode_id]) {
      fieldValues[subnode_id] = {};
    }
    fieldValues[subnode_id][field_id] = value;
    return true;
  };
  
  test('should apply updates in order when timestamps are sequential', () => {
    // Simulate updates arriving in order
    const updates = [
      { subnode_id: 'input', field_id: 'volume', value: 50, timestamp: 1000 },
      { subnode_id: 'input', field_id: 'volume', value: 75, timestamp: 2000 },
      { subnode_id: 'input', field_id: 'volume', value: 100, timestamp: 3000 }
    ];
    
    updates.forEach(update => {
      const applied = handleFieldUpdated(update);
      expect(applied).toBe(true);
    });
    
    expect(fieldValues.input.volume).toBe(100);
    expect(fieldTimestamps.get('input:volume')).toBe(3000);
  });
  
  test('should ignore out-of-order updates with older timestamps', () => {
    // Simulate updates arriving out of order
    const updates = [
      { subnode_id: 'input', field_id: 'volume', value: 100, timestamp: 3000 }, // Latest arrives first
      { subnode_id: 'input', field_id: 'volume', value: 75, timestamp: 2000 },  // Older update
      { subnode_id: 'input', field_id: 'volume', value: 50, timestamp: 1000 }   // Oldest update
    ];
    
    const applied1 = handleFieldUpdated(updates[0]);
    expect(applied1).toBe(true);
    expect(fieldValues.input.volume).toBe(100);
    
    const applied2 = handleFieldUpdated(updates[1]);
    expect(applied2).toBe(false); // Should be ignored
    expect(fieldValues.input.volume).toBe(100); // Value unchanged
    
    const applied3 = handleFieldUpdated(updates[2]);
    expect(applied3).toBe(false); // Should be ignored
    expect(fieldValues.input.volume).toBe(100); // Value unchanged
  });
  
  test('should handle updates for different fields independently', () => {
    const updates = [
      { subnode_id: 'input', field_id: 'volume', value: 100, timestamp: 3000 },
      { subnode_id: 'input', field_id: 'device', value: 'Mic A', timestamp: 2000 },
      { subnode_id: 'input', field_id: 'volume', value: 50, timestamp: 1000 }, // Out of order
      { subnode_id: 'input', field_id: 'device', value: 'Mic B', timestamp: 4000 }
    ];
    
    updates.forEach(update => handleFieldUpdated(update));
    
    // Volume should be 100 (timestamp 3000), ignoring the older update
    expect(fieldValues.input.volume).toBe(100);
    expect(fieldTimestamps.get('input:volume')).toBe(3000);
    
    // Device should be 'Mic B' (timestamp 4000)
    expect(fieldValues.input.device).toBe('Mic B');
    expect(fieldTimestamps.get('input:device')).toBe(4000);
  });
  
  test('should handle updates from multiple clients with timestamps', () => {
    // Simulate updates from different clients arriving out of order
    const updates = [
      { subnode_id: 'input', field_id: 'volume', value: 75, timestamp: 2000 },  // Client B
      { subnode_id: 'input', field_id: 'volume', value: 50, timestamp: 1000 },  // Client A (older)
      { subnode_id: 'input', field_id: 'volume', value: 100, timestamp: 3000 }  // Client C (newest)
    ];
    
    updates.forEach(update => handleFieldUpdated(update));
    
    // Should end up with the newest value
    expect(fieldValues.input.volume).toBe(100);
    expect(fieldTimestamps.get('input:volume')).toBe(3000);
  });
  
  test('should apply update with same timestamp (last-write-wins)', () => {
    const updates = [
      { subnode_id: 'input', field_id: 'volume', value: 50, timestamp: 1000 },
      { subnode_id: 'input', field_id: 'volume', value: 75, timestamp: 1000 } // Same timestamp
    ];
    
    updates.forEach(update => handleFieldUpdated(update));
    
    // Last write wins when timestamps are equal
    expect(fieldValues.input.volume).toBe(75);
  });
  
  test('should handle updates without timestamps (backward compatibility)', () => {
    const updates = [
      { subnode_id: 'input', field_id: 'volume', value: 50 }, // No timestamp
      { subnode_id: 'input', field_id: 'volume', value: 75 }  // No timestamp
    ];
    
    updates.forEach(update => {
      const applied = handleFieldUpdated(update);
      expect(applied).toBe(true);
    });
    
    // Should apply all updates when no timestamps
    expect(fieldValues.input.volume).toBe(75);
  });
});
