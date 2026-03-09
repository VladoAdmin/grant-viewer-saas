import { useState } from 'react';
import { submitFeedback } from '../lib/api';

interface FeedbackModalProps {
  callId?: number;
  onClose: () => void;
}

export default function FeedbackModal({ callId, onClose }: FeedbackModalProps) {
  const [type, setType] = useState('correction');
  const [message, setMessage] = useState('');
  const [contact, setContact] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [success, setSuccess] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!message.trim()) return;

    setSubmitting(true);
    setError(null);
    try {
      await submitFeedback({
        call_id: callId,
        type,
        message: message.trim(),
        contact: contact.trim() || undefined,
      });
      setSuccess(true);
      setTimeout(onClose, 2000);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Odoslanie zlyhalo');
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-xl shadow-xl max-w-md w-full p-6">
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-lg font-semibold text-gray-900">Podnet / Oprava</h3>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 text-xl">&times;</button>
        </div>

        {success ? (
          <div className="text-center py-6">
            <p className="text-green-600 font-medium text-lg">✓ Ďakujeme za podnet!</p>
            <p className="text-gray-500 text-sm mt-1">Budeme sa ním zaoberať.</p>
          </div>
        ) : (
          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Typ podnetu</label>
              <select
                value={type}
                onChange={(e) => setType(e.target.value)}
                className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:ring-blue-500 focus:border-blue-500"
              >
                <option value="correction">Oprava údajov</option>
                <option value="missing">Chýbajúce informácie</option>
                <option value="suggestion">Návrh na zlepšenie</option>
                <option value="bug">Chyba v systéme</option>
              </select>
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Správa *</label>
              <textarea
                value={message}
                onChange={(e) => setMessage(e.target.value)}
                rows={4}
                required
                placeholder="Popíšte problém alebo návrh..."
                className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:ring-blue-500 focus:border-blue-500"
              />
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Kontakt (voliteľné)</label>
              <input
                type="text"
                value={contact}
                onChange={(e) => setContact(e.target.value)}
                placeholder="Email alebo meno"
                className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:ring-blue-500 focus:border-blue-500"
              />
            </div>

            {error && (
              <p className="text-red-600 text-sm">{error}</p>
            )}

            <div className="flex gap-3 pt-2">
              <button
                type="submit"
                disabled={submitting || !message.trim()}
                className="flex-1 bg-blue-600 text-white rounded-md px-4 py-2 text-sm font-medium hover:bg-blue-700 disabled:opacity-50 transition-colors"
              >
                {submitting ? 'Odosielam...' : 'Odoslať podnet'}
              </button>
              <button
                type="button"
                onClick={onClose}
                className="px-4 py-2 rounded-md border border-gray-300 text-sm text-gray-700 hover:bg-gray-50 transition-colors"
              >
                Zrušiť
              </button>
            </div>
          </form>
        )}
      </div>
    </div>
  );
}
