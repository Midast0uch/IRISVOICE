/**
 * AuthFlowModal Component
 * 
 * Modal for handling different authentication flows:
 * - OAuth2 (opens browser, waits for callback)
 * - Telegram MTProto (phone + code)
 * - Credentials (form-based)
 */

'use client';

import React, { useState, useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { X, ExternalLink, Lock, Shield, CheckCircle2, Loader2 } from 'lucide-react';
import { AuthType, AuthConfig, AuthField } from '@/hooks/useIntegrations';

interface AuthFlowModalProps {
  isOpen: boolean;
  onClose: () => void;
  authData: {
    integrationId: string;
    authType: AuthType;
    authConfig: AuthConfig;
  } | null;
}

export function AuthFlowModal({ isOpen, onClose, authData }: AuthFlowModalProps) {
  if (!isOpen || !authData) return null;

  const { authType, authConfig } = authData;

  return (
    <AnimatePresence>
      {isOpen && (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          className="fixed inset-0 z-[100] flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm"
          onClick={onClose}
        >
          <motion.div
            initial={{ scale: 0.95, opacity: 0 }}
            animate={{ scale: 1, opacity: 1 }}
            exit={{ scale: 0.95, opacity: 0 }}
            onClick={(e) => e.stopPropagation()}
            className="relative w-full max-w-md overflow-hidden rounded-2xl bg-gradient-to-br from-gray-900 to-gray-950 border border-white/[0.08] shadow-2xl"
          >
            {/* Header gradient */}
            <div className="absolute inset-x-0 top-0 h-1 bg-gradient-to-r from-blue-500 via-purple-500 to-pink-500" />
            
            {/* Content based on auth type */}
            {authType === 'oauth2' && (
              <OAuthFlowContent config={authConfig} onClose={onClose} />
            )}
            {authType === 'telegram_mtproto' && (
              <TelegramFlowContent config={authConfig} onClose={onClose} />
            )}
            {authType === 'credentials' && (
              <CredentialsFlowContent config={authConfig} onClose={onClose} />
            )}
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}

// OAuth2 Flow Content
function OAuthFlowContent({ config, onClose }: { config: AuthConfig; onClose: () => void }) {
  const [isConnecting, setIsConnecting] = useState(false);

  const handleConnect = useCallback(() => {
    setIsConnecting(true);
    // The OAuth flow is handled by opening the browser
    // Backend will send the URL to open
    // For now, we just show a loading state
  }, []);

  return (
    <div className="p-6">
      {/* Close button */}
      <button
        onClick={onClose}
        className="absolute top-4 right-4 p-2 rounded-lg hover:bg-white/[0.05] transition-colors"
      >
        <X className="w-4 h-4 text-white/50" />
      </button>

      {/* Icon */}
      <div className="w-14 h-14 mx-auto mb-4 rounded-2xl bg-gradient-to-br from-blue-500/20 to-purple-500/20 flex items-center justify-center border border-white/[0.08]">
        <Shield className="w-6 h-6 text-blue-400" />
      </div>

      {/* Title */}
      <h2 className="text-[16px] font-semibold text-white/90 text-center mb-2">
        Connect {config.provider || 'Service'}
      </h2>

      {/* Permissions */}
      <div className="mb-6">
        <p className="text-[11px] text-white/50 uppercase tracking-wider mb-3 text-center">
          This will allow IRIS to:
        </p>
        <ul className="space-y-2">
          {(config.scopes || []).map((scope, idx) => (
            <li key={idx} className="flex items-center gap-2 text-[12px] text-white/70">
              <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400 flex-shrink-0" />
              <span className="capitalize">{scope.replace(/https?:\/\//, '').replace(/\/auth\//, ' ').replace(/\./g, ' ')}</span>
            </li>
          ))}
          {(!config.scopes || config.scopes.length === 0) && (
            <li className="flex items-center gap-2 text-[12px] text-white/70">
              <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400 flex-shrink-0" />
              <span>Access your account</span>
            </li>
          )}
        </ul>
      </div>

      {/* Security note */}
      <div className="flex items-start gap-2 p-3 rounded-lg bg-white/[0.03] border border-white/[0.05] mb-6">
        <Lock className="w-3.5 h-3.5 text-white/40 mt-0.5 flex-shrink-0" />
        <p className="text-[10px] text-white/40 leading-relaxed">
          Your credentials are encrypted and stored locally. IRIS never stores your passwords on our servers.
        </p>
      </div>

      {/* Actions */}
      <div className="flex gap-3">
        <button
          onClick={onClose}
          className="flex-1 py-2.5 rounded-lg bg-white/[0.05] hover:bg-white/[0.08] text-white/70 text-[12px] font-medium transition-colors"
        >
          Cancel
        </button>
        <button
          onClick={handleConnect}
          disabled={isConnecting}
          className="flex-1 py-2.5 rounded-lg bg-gradient-to-r from-blue-500 to-purple-500 hover:from-blue-400 hover:to-purple-400 text-white text-[12px] font-medium transition-all disabled:opacity-50 flex items-center justify-center gap-2"
        >
          {isConnecting ? (
            <>
              <Loader2 className="w-3.5 h-3.5 animate-spin" />
              Opening browser...
            </>
          ) : (
            <>
              <ExternalLink className="w-3.5 h-3.5" />
              Connect
            </>
          )}
        </button>
      </div>
    </div>
  );
}

// Telegram Flow Content
function TelegramFlowContent({ config, onClose }: { config: AuthConfig; onClose: () => void }) {
  const [step, setStep] = useState<'phone' | 'code'>('phone');
  const [phone, setPhone] = useState('');
  const [code, setCode] = useState('');
  const [isLoading, setIsLoading] = useState(false);

  const handleSendCode = useCallback(() => {
    if (!phone) return;
    setIsLoading(true);
    // Simulate API call
    setTimeout(() => {
      setIsLoading(false);
      setStep('code');
    }, 1000);
  }, [phone]);

  const handleVerify = useCallback(() => {
    if (!code) return;
    setIsLoading(true);
    // Submit code to backend
    setTimeout(() => {
      setIsLoading(false);
      onClose();
    }, 1000);
  }, [code, onClose]);

  return (
    <div className="p-6">
      <button
        onClick={onClose}
        className="absolute top-4 right-4 p-2 rounded-lg hover:bg-white/[0.05] transition-colors"
      >
        <X className="w-4 h-4 text-white/50" />
      </button>

      <div className="w-14 h-14 mx-auto mb-4 rounded-2xl bg-gradient-to-br from-blue-400/20 to-cyan-400/20 flex items-center justify-center border border-white/[0.08]">
        <svg className="w-6 h-6 text-blue-400" viewBox="0 0 24 24" fill="currentColor">
          <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm4.64 6.8c-.15 1.58-.8 5.42-1.13 7.19-.14.75-.42 1-.68 1.03-.58.05-1.02-.38-1.58-.75-.88-.58-1.38-.94-2.23-1.5-.99-.65-.35-1.01.22-1.59.15-.15 2.71-2.48 2.76-2.69a.2.2 0 0 0-.05-.18c-.06-.05-.14-.03-.21-.02-.09.02-1.49.95-4.22 2.79-.4.27-.76.41-1.08.4-.36-.01-1.04-.2-1.55-.37-.63-.2-1.12-.31-1.08-.66.02-.18.27-.36.74-.55 2.92-1.27 4.86-2.11 5.83-2.51 2.78-1.16 3.35-1.36 3.73-1.36.08 0 .27.02.39.12.1.08.13.19.14.27-.01.06.01.24 0 .38z"/>
        </svg>
      </div>

      <h2 className="text-[16px] font-semibold text-white/90 text-center mb-1">
        Connect Telegram
      </h2>
      <p className="text-[11px] text-white/50 text-center mb-6">
        Enter your phone number to receive a verification code
      </p>

      {step === 'phone' ? (
        <div className="space-y-4">
          <div>
            <label className="block text-[10px] text-white/50 uppercase tracking-wider mb-2">
              Phone Number
            </label>
            <input
              type="tel"
              value={phone}
              onChange={(e) => setPhone(e.target.value)}
              placeholder="+1 234 567 8900"
              className="w-full px-3 py-2.5 rounded-lg bg-white/[0.05] border border-white/[0.08] text-white text-[13px] placeholder:text-white/30 focus:outline-none focus:border-white/20 transition-colors"
            />
          </div>
          <button
            onClick={handleSendCode}
            disabled={!phone || isLoading}
            className="w-full py-2.5 rounded-lg bg-gradient-to-r from-blue-500 to-cyan-500 hover:from-blue-400 hover:to-cyan-400 text-white text-[12px] font-medium transition-all disabled:opacity-50 flex items-center justify-center gap-2"
          >
            {isLoading ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : 'Send Code'}
          </button>
        </div>
      ) : (
        <div className="space-y-4">
          <div>
            <label className="block text-[10px] text-white/50 uppercase tracking-wider mb-2">
              Verification Code
            </label>
            <input
              type="text"
              value={code}
              onChange={(e) => setCode(e.target.value)}
              placeholder="12345"
              maxLength={5}
              className="w-full px-3 py-2.5 rounded-lg bg-white/[0.05] border border-white/[0.08] text-white text-[13px] placeholder:text-white/30 focus:outline-none focus:border-white/20 transition-colors text-center tracking-widest"
            />
          </div>
          <div className="flex gap-3">
            <button
              onClick={() => setStep('phone')}
              className="flex-1 py-2.5 rounded-lg bg-white/[0.05] hover:bg-white/[0.08] text-white/70 text-[12px] font-medium transition-colors"
            >
              Back
            </button>
            <button
              onClick={handleVerify}
              disabled={!code || isLoading}
              className="flex-1 py-2.5 rounded-lg bg-gradient-to-r from-blue-500 to-cyan-500 hover:from-blue-400 hover:to-cyan-400 text-white text-[12px] font-medium transition-all disabled:opacity-50 flex items-center justify-center gap-2"
            >
              {isLoading ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : 'Verify'}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

// Credentials Flow Content
function CredentialsFlowContent({ config, onClose }: { config: AuthConfig; onClose: () => void }) {
  const [values, setValues] = useState<Record<string, string>>({});
  const [isLoading, setIsLoading] = useState(false);

  const handleSubmit = useCallback((e: React.FormEvent) => {
    e.preventDefault();
    setIsLoading(true);
    // Submit credentials to backend
    setTimeout(() => {
      setIsLoading(false);
      onClose();
    }, 1000);
  }, [onClose]);

  const handleChange = (key: string, value: string) => {
    setValues(prev => ({ ...prev, [key]: value }));
  };

  const fields = config.fields || [];

  return (
    <div className="p-6">
      <button
        onClick={onClose}
        className="absolute top-4 right-4 p-2 rounded-lg hover:bg-white/[0.05] transition-colors"
      >
        <X className="w-4 h-4 text-white/50" />
      </button>

      <div className="w-14 h-14 mx-auto mb-4 rounded-2xl bg-gradient-to-br from-amber-500/20 to-orange-500/20 flex items-center justify-center border border-white/[0.08]">
        <Lock className="w-6 h-6 text-amber-400" />
      </div>

      <h2 className="text-[16px] font-semibold text-white/90 text-center mb-1">
        Email Account
      </h2>
      <p className="text-[11px] text-white/50 text-center mb-6">
        Enter your email server credentials
      </p>

      <form onSubmit={handleSubmit} className="space-y-4">
        {fields.map((field: AuthField) => (
          <div key={field.key}>
            <label className="block text-[10px] text-white/50 uppercase tracking-wider mb-2">
              {field.label}
            </label>
            <input
              type={field.type === 'password' ? 'password' : field.type === 'email' ? 'email' : 'text'}
              value={values[field.key] || ''}
              onChange={(e) => handleChange(field.key, e.target.value)}
              placeholder={field.default?.toString() || ''}
              className="w-full px-3 py-2.5 rounded-lg bg-white/[0.05] border border-white/[0.08] text-white text-[13px] placeholder:text-white/30 focus:outline-none focus:border-white/20 transition-colors"
            />
          </div>
        ))}

        <div className="pt-2 flex gap-3">
          <button
            type="button"
            onClick={onClose}
            className="flex-1 py-2.5 rounded-lg bg-white/[0.05] hover:bg-white/[0.08] text-white/70 text-[12px] font-medium transition-colors"
          >
            Cancel
          </button>
          <button
            type="submit"
            disabled={isLoading || fields.some(f => !f.optional && !values[f.key])}
            className="flex-1 py-2.5 rounded-lg bg-gradient-to-r from-amber-500 to-orange-500 hover:from-amber-400 hover:to-orange-400 text-white text-[12px] font-medium transition-all disabled:opacity-50 flex items-center justify-center gap-2"
          >
            {isLoading ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : 'Connect'}
          </button>
        </div>
      </form>
    </div>
  );
}
