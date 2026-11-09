'use client';

import { useCallback, useEffect, useState } from 'react';
import type { FormEvent } from 'react';

type KeyStatus = {
  key_source: 'keychain' | 'launcher' | string;
  locked: boolean;
  unlocked: boolean;
  memory_ready: boolean;
};

/**
 * Dashboard fallback for the launcher passphrase.
 *
 * In release mode (`key_source: "launcher"`) the launcher hands the phrase to
 * the backend. If the user starts IRIS without it, the memory store stays
 * locked and this card is the only way in. The phrase is sent once, over the
 * local API, and the backend keeps the derived key in process memory only —
 * the input is cleared and the value is never read back.
 *
 * In development (`key_source: "keychain"`) the card renders one line and no
 * input, because the OS keychain already holds the key.
 */
export function MemoryKeyUnlockCard({ glowColor }: { glowColor: string }) {
  const [status, setStatus] = useState<KeyStatus | null>(null);
  const [phrase, setPhrase] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const res = await fetch('/api/memory/key-status');
      if (res.ok) setStatus(await res.json());
    } catch {
      // The backend may still be starting; the card stays neutral.
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  if (!status) return null;

  if (status.key_source !== 'launcher') {
    return (
      <p className="iris-fok">
        Memory key: held by the OS keychain. The launcher passphrase is used at release.
      </p>
    );
  }

  if (!status.locked) {
    return (
      <p className="iris-fok">
        Memory is unlocked for this session.
        {status.memory_ready ? '' : ' Starting the memory system…'}
      </p>
    );
  }

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    const value = phrase.trim();
    if (!value || busy) return;
    setBusy(true);
    setError(null);
    try {
      const res = await fetch('/api/memory/unlock', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ passphrase: value }),
      });
      const body = await res.json().catch(() => ({}));
      if (!res.ok || !body?.ok) {
        setError(res.status === 401 ? 'That passphrase did not open the memory store.' : (body?.error || 'Unlock failed.'));
      } else {
        setPhrase('');
        await refresh();
      }
    } catch {
      setError('The backend is not reachable.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <form onSubmit={submit} className="col-span-full mt-1 mb-2">
      <label
        htmlFor="memory-passphrase"
        className="block text-[11px] uppercase tracking-wider mb-1"
        style={{ color: 'rgba(255,255,255,0.5)' }}
      >
        Memory passphrase
      </label>
      <div className="flex items-center gap-2">
        <input
          id="memory-passphrase"
          type="password"
          value={phrase}
          onChange={(e) => setPhrase(e.target.value)}
          placeholder="Your IRIS memory passphrase"
          autoComplete="off"
          spellCheck={false}
          className="iris-input flex-1"
          disabled={busy}
        />
        <button
          type="submit"
          disabled={busy || !phrase.trim()}
          className="iris-fbtn"
          style={{ borderColor: `${glowColor}55`, color: glowColor }}
        >
          {busy ? 'Unlocking…' : 'Unlock'}
        </button>
      </div>
      {error && <p className="iris-ferr">{error}</p>}
      {!status.memory_ready && (
        <p className="iris-fok" style={{ opacity: 0.7 }}>
          The memory store is encrypted. IRIS cannot read or write it until it is unlocked.
        </p>
      )}
    </form>
  );
}

export default MemoryKeyUnlockCard;
