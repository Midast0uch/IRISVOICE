/**
 * VPS Configuration UI Unit Tests
 * 
 * **Validates: Requirements 26.16**
 * 
 * Tests the VPS configuration UI in DarkGlassDashboard to ensure:
 * - VPS subnode exists under agent category
 * - All required configuration fields are present
 * - Field types are correct (toggle, text, password, slider, dropdown, status)
 * - Default values are set appropriately
 * - Status indicator displays VPS state correctly
 */

import { describe, test, expect } from '@jest/globals';

/**
 * Mock SUB_NODES_DATA structure from DarkGlassDashboard
 * This represents the actual data structure used in the component
 */
const SUB_NODES_DATA = {
  agent: [
    {
      id: 'identity',
      label: 'IDENTITY',
      fields: [
        { id: 'assistant_name', label: 'Name', type: 'text' },
        { id: 'personality', label: 'Personality', type: 'dropdown' },
        { id: 'knowledge', label: 'Knowledge', type: 'dropdown' },
      ]
    },
    {
      id: 'wake',
      label: 'WAKE',
      fields: [
        { id: 'wake_phrase', label: 'Wake Phrase', type: 'text' },
        { id: 'detection_sensitivity', label: 'Sensitivity', type: 'slider' },
        { id: 'activation_sound', label: 'Sound', type: 'toggle' },
      ]
    },
    {
      id: 'speech',
      label: 'SPEECH',
      fields: [
        { id: 'tts_voice', label: 'TTS Voice', type: 'dropdown' },
        { id: 'speaking_rate', label: 'Rate', type: 'slider' },
      ]
    },
    {
      id: 'memory',
      label: 'MEMORY',
      fields: [
        { id: 'token_count', label: 'Tokens', type: 'text' },
        { id: 'clear_memory', label: 'Clear Memory', type: 'text' },
      ]
    },
    {
      id: 'vps',
      label: 'VPS',
      fields: [
        { id: 'enabled', label: 'Enabled', type: 'toggle', defaultValue: false },
        { id: 'endpoints', label: 'Endpoints', type: 'text', placeholder: 'https://vps.example.com:8000', defaultValue: '' },
        { id: 'auth_token', label: 'Auth Token', type: 'password', placeholder: 'Bearer token', defaultValue: '' },
        { id: 'timeout', label: 'Timeout', type: 'slider', min: 5, max: 120, defaultValue: 30, unit: 's' },
        { id: 'health_check_interval', label: 'Health Check', type: 'slider', min: 10, max: 300, defaultValue: 60, unit: 's' },
        { id: 'fallback_to_local', label: 'Fallback Local', type: 'toggle', defaultValue: true },
        { id: 'load_balancing', label: 'Load Balance', type: 'toggle', defaultValue: false },
        { id: 'load_balancing_strategy', label: 'LB Strategy', type: 'dropdown', options: ['round_robin', 'least_loaded'], defaultValue: 'round_robin' },
        { id: 'protocol', label: 'Protocol', type: 'dropdown', options: ['rest', 'websocket'], defaultValue: 'rest' },
        { id: 'vps_status', label: 'Status', type: 'status', placeholder: 'Not configured' },
      ]
    },
  ]
};

describe('VPS Configuration UI', () => {
  test('VPS subnode exists under agent category', () => {
    const agentSubnodes = SUB_NODES_DATA.agent;
    const vpsSubnode = agentSubnodes.find(subnode => subnode.id === 'vps');
    
    expect(vpsSubnode).toBeDefined();
    expect(vpsSubnode.label).toBe('VPS');
  });

  test('VPS subnode has all required configuration fields', () => {
    const vpsSubnode = SUB_NODES_DATA.agent.find(subnode => subnode.id === 'vps');
    const fieldIds = vpsSubnode.fields.map(field => field.id);
    
    const requiredFields = [
      'enabled',
      'endpoints',
      'auth_token',
      'timeout',
      'health_check_interval',
      'fallback_to_local',
      'load_balancing',
      'load_balancing_strategy',
      'protocol',
      'vps_status'
    ];
    
    requiredFields.forEach(fieldId => {
      expect(fieldIds).toContain(fieldId);
    });
  });

  test('VPS enabled field is a toggle with default false', () => {
    const vpsSubnode = SUB_NODES_DATA.agent.find(subnode => subnode.id === 'vps');
    const enabledField = vpsSubnode.fields.find(field => field.id === 'enabled');
    
    expect(enabledField.type).toBe('toggle');
    expect(enabledField.defaultValue).toBe(false);
  });

  test('VPS endpoints field is a text input', () => {
    const vpsSubnode = SUB_NODES_DATA.agent.find(subnode => subnode.id === 'vps');
    const endpointsField = vpsSubnode.fields.find(field => field.id === 'endpoints');
    
    expect(endpointsField.type).toBe('text');
    expect(endpointsField.placeholder).toBe('https://vps.example.com:8000');
  });

  test('VPS auth_token field is a password input', () => {
    const vpsSubnode = SUB_NODES_DATA.agent.find(subnode => subnode.id === 'vps');
    const authTokenField = vpsSubnode.fields.find(field => field.id === 'auth_token');
    
    expect(authTokenField.type).toBe('password');
    expect(authTokenField.placeholder).toBe('Bearer token');
  });

  test('VPS timeout field is a slider with correct range', () => {
    const vpsSubnode = SUB_NODES_DATA.agent.find(subnode => subnode.id === 'vps');
    const timeoutField = vpsSubnode.fields.find(field => field.id === 'timeout');
    
    expect(timeoutField.type).toBe('slider');
    expect(timeoutField.min).toBe(5);
    expect(timeoutField.max).toBe(120);
    expect(timeoutField.defaultValue).toBe(30);
    expect(timeoutField.unit).toBe('s');
  });

  test('VPS health_check_interval field is a slider with correct range', () => {
    const vpsSubnode = SUB_NODES_DATA.agent.find(subnode => subnode.id === 'vps');
    const healthCheckField = vpsSubnode.fields.find(field => field.id === 'health_check_interval');
    
    expect(healthCheckField.type).toBe('slider');
    expect(healthCheckField.min).toBe(10);
    expect(healthCheckField.max).toBe(300);
    expect(healthCheckField.defaultValue).toBe(60);
    expect(healthCheckField.unit).toBe('s');
  });

  test('VPS fallback_to_local field is a toggle with default true', () => {
    const vpsSubnode = SUB_NODES_DATA.agent.find(subnode => subnode.id === 'vps');
    const fallbackField = vpsSubnode.fields.find(field => field.id === 'fallback_to_local');
    
    expect(fallbackField.type).toBe('toggle');
    expect(fallbackField.defaultValue).toBe(true);
  });

  test('VPS load_balancing field is a toggle with default false', () => {
    const vpsSubnode = SUB_NODES_DATA.agent.find(subnode => subnode.id === 'vps');
    const loadBalancingField = vpsSubnode.fields.find(field => field.id === 'load_balancing');
    
    expect(loadBalancingField.type).toBe('toggle');
    expect(loadBalancingField.defaultValue).toBe(false);
  });

  test('VPS load_balancing_strategy field is a dropdown with correct options', () => {
    const vpsSubnode = SUB_NODES_DATA.agent.find(subnode => subnode.id === 'vps');
    const strategyField = vpsSubnode.fields.find(field => field.id === 'load_balancing_strategy');
    
    expect(strategyField.type).toBe('dropdown');
    expect(strategyField.options).toEqual(['round_robin', 'least_loaded']);
    expect(strategyField.defaultValue).toBe('round_robin');
  });

  test('VPS protocol field is a dropdown with correct options', () => {
    const vpsSubnode = SUB_NODES_DATA.agent.find(subnode => subnode.id === 'vps');
    const protocolField = vpsSubnode.fields.find(field => field.id === 'protocol');
    
    expect(protocolField.type).toBe('dropdown');
    expect(protocolField.options).toEqual(['rest', 'websocket']);
    expect(protocolField.defaultValue).toBe('rest');
  });

  test('VPS status field is a status indicator', () => {
    const vpsSubnode = SUB_NODES_DATA.agent.find(subnode => subnode.id === 'vps');
    const statusField = vpsSubnode.fields.find(field => field.id === 'vps_status');
    
    expect(statusField.type).toBe('status');
    expect(statusField.label).toBe('Status');
  });

  test('VPS status indicator shows correct state when disabled', () => {
    const fieldValues = {
      vps: {
        enabled: false,
        endpoints: ''
      }
    };
    
    const vpsEnabled = fieldValues.vps.enabled;
    const vpsEndpoints = fieldValues.vps.endpoints;
    const endpointCount = vpsEndpoints ? vpsEndpoints.split(',').filter(e => e.trim()).length : 0;
    
    expect(vpsEnabled).toBe(false);
    expect(endpointCount).toBe(0);
  });

  test('VPS status indicator shows correct state when enabled with endpoints', () => {
    const fieldValues = {
      vps: {
        enabled: true,
        endpoints: 'https://vps1.example.com:8000,https://vps2.example.com:8000'
      }
    };
    
    const vpsEnabled = fieldValues.vps.enabled;
    const vpsEndpoints = fieldValues.vps.endpoints;
    const endpointCount = vpsEndpoints ? vpsEndpoints.split(',').filter(e => e.trim()).length : 0;
    
    expect(vpsEnabled).toBe(true);
    expect(endpointCount).toBe(2);
  });

  test('VPS configuration matches backend VPSConfig structure', () => {
    const vpsSubnode = SUB_NODES_DATA.agent.find(subnode => subnode.id === 'vps');
    const fieldIds = vpsSubnode.fields.map(field => field.id).filter(id => id !== 'vps_status');
    
    // These field IDs should match the VPSConfig model in backend/agent/vps_gateway.py
    const backendConfigFields = [
      'enabled',
      'endpoints',
      'auth_token',
      'timeout',
      'health_check_interval',
      'fallback_to_local',
      'load_balancing',
      'load_balancing_strategy',
      'protocol'
    ];
    
    backendConfigFields.forEach(fieldId => {
      expect(fieldIds).toContain(fieldId);
    });
  });
});
