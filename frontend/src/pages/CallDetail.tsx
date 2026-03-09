import { useState, useEffect } from 'react';
import { useParams, Link } from 'react-router-dom';
import { getCallDetail, getExportPdfUrl, type CallDetail as CallDetailType } from '../lib/api';
import FeedbackModal from '../components/FeedbackModal';

function formatDate(dateStr: string | null): string {
  if (!dateStr) return '—';
  try {
    const d = new Date(dateStr);
    return d.toLocaleDateString('sk-SK', { day: '2-digit', month: '2-digit', year: 'numeric' });
  } catch {
    return dateStr.slice(0, 10);
  }
}

function formatAllocation(alloc: string | null): string {
  if (!alloc) return '—';
  const num = parseFloat(alloc);
  if (isNaN(num)) return alloc;
  return new Intl.NumberFormat('sk-SK', {
    style: 'currency',
    currency: 'EUR',
    maximumFractionDigits: 0,
  }).format(num);
}

export default function CallDetail() {
  const { id } = useParams<{ id: string }>();
  const [detail, setDetail] = useState<CallDetailType | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showFeedback, setShowFeedback] = useState(false);

  useEffect(() => {
    if (!id) return;
    setLoading(true);
    getCallDetail(parseInt(id, 10))
      .then(setDetail)
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, [id]);

  if (loading) {
    return (
      <div className="animate-pulse space-y-4">
        <div className="h-8 bg-gray-200 rounded w-3/4"></div>
        <div className="h-4 bg-gray-100 rounded w-1/2"></div>
        <div className="h-64 bg-gray-100 rounded"></div>
      </div>
    );
  }

  if (error || !detail) {
    return (
      <div className="bg-red-50 border border-red-200 rounded-md p-6 text-center">
        <p className="text-red-700">{error || 'Výzva nebola nájdená'}</p>
        <Link to="/" className="text-blue-600 hover:underline mt-2 inline-block">← Späť na zoznam</Link>
      </div>
    );
  }

  const { call, attributes, attachments } = detail;

  // Key metadata fields
  const keyFields = [
    { label: 'Vyhlasovateľ', value: attributes['Vyhlasovateľ výzvy'] || call.provider },
    { label: 'Kód výzvy', value: attributes['Kód výzvy'] },
    { label: 'Program', value: attributes['Program'] },
    { label: 'Druh výzvy', value: attributes['Druh výzvy'] || call.call_type },
    { label: 'Typ výzvy', value: attributes['Typ výzvy'] },
    { label: 'Dátum vyhlásenia', value: formatDate(call.announced_at) },
    { label: 'Deadline', value: formatDate(call.deadline_at) },
    { label: 'Alokácia EÚ', value: attributes['Alokácia EÚ'] || formatAllocation(call.total_allocation) },
    { label: 'Alokácia spolu', value: attributes['Alokácia spolu'] },
    { label: 'Miesto realizácie', value: attributes['Miesto realizácie'] },
  ].filter((f) => f.value && f.value !== '—');

  // Additional attributes not shown in key fields
  const shownKeys = new Set([
    'Vyhlasovateľ výzvy', 'Kód výzvy', 'Program', 'Druh výzvy', 'Typ výzvy',
    'Miesto realizácie', 'Alokácia EÚ', 'Alokácia ŠR', 'Alokácia spolu',
    'Špecifický cieľ', 'opravneni_ziadatelia', 'vyhlasovatel_vyzvy', 'alokacia_eu',
  ]);
  const otherAttributes = Object.entries(attributes).filter(([k]) => !shownKeys.has(k));

  return (
    <div>
      {/* Back button */}
      <Link to="/" className="text-blue-600 hover:underline text-sm mb-4 inline-block">
        ← Späť na zoznam
      </Link>

      {/* Header */}
      <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-6 mb-6">
        <div className="flex items-start justify-between gap-4">
          <div>
            <h1 className="text-xl font-bold text-gray-900">{call.title}</h1>
            <div className="mt-2 flex items-center gap-3 text-sm text-gray-500">
              <span className="bg-blue-50 text-blue-700 px-2 py-0.5 rounded text-xs font-medium">
                {call.source}
              </span>
              {call.status && (
                <span className={`px-2 py-0.5 rounded text-xs font-medium ${
                  call.status.toLowerCase().includes('otvor') ? 'bg-green-100 text-green-800' :
                  call.status.toLowerCase().includes('uzavr') ? 'bg-red-100 text-red-800' :
                  'bg-gray-100 text-gray-700'
                }`}>
                  {call.status}
                </span>
              )}
            </div>
          </div>

          <div className="flex gap-2 shrink-0">
            <a
              href={getExportPdfUrl(call.id)}
              className="bg-blue-600 text-white rounded-md px-4 py-2 text-sm font-medium hover:bg-blue-700 transition-colors"
              target="_blank"
              rel="noopener noreferrer"
            >
              📄 Stiahnuť PDF
            </a>
            <button
              onClick={() => setShowFeedback(true)}
              className="border border-gray-300 text-gray-700 rounded-md px-4 py-2 text-sm font-medium hover:bg-gray-50 transition-colors"
            >
              💬 Podnet
            </button>
          </div>
        </div>
      </div>

      {/* Key metadata */}
      <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-6 mb-6">
        <h2 className="text-lg font-semibold text-gray-900 mb-4">Základné informácie</h2>
        <dl className="grid grid-cols-1 sm:grid-cols-2 gap-x-6 gap-y-3">
          {keyFields.map(({ label, value }) => (
            <div key={label}>
              <dt className="text-xs font-medium text-gray-500 uppercase tracking-wide">{label}</dt>
              <dd className="mt-0.5 text-sm text-gray-900">{value}</dd>
            </div>
          ))}
        </dl>
      </div>

      {/* Eligible applicants */}
      {(attributes['opravneni_ziadatelia'] || call.status) && (
        <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-6 mb-6">
          <h2 className="text-lg font-semibold text-gray-900 mb-3">Oprávnení žiadatelia</h2>
          <p className="text-sm text-gray-700 whitespace-pre-wrap">
            {attributes['opravneni_ziadatelia'] || '—'}
          </p>
        </div>
      )}

      {/* Specific objectives */}
      {attributes['Špecifický cieľ'] && (
        <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-6 mb-6">
          <h2 className="text-lg font-semibold text-gray-900 mb-3">Špecifický cieľ</h2>
          <p className="text-sm text-gray-700 whitespace-pre-wrap">
            {attributes['Špecifický cieľ']}
          </p>
        </div>
      )}

      {/* Other attributes */}
      {otherAttributes.length > 0 && (
        <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-6 mb-6">
          <h2 className="text-lg font-semibold text-gray-900 mb-4">Ďalšie informácie</h2>
          <dl className="space-y-2">
            {otherAttributes.map(([key, value]) => (
              <div key={key} className="flex gap-2">
                <dt className="text-sm font-medium text-gray-600 shrink-0">{key}:</dt>
                <dd className="text-sm text-gray-900">{value}</dd>
              </div>
            ))}
          </dl>
        </div>
      )}

      {/* Attachments */}
      {attachments.length > 0 && (
        <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-6 mb-6">
          <h2 className="text-lg font-semibold text-gray-900 mb-4">
            Prílohy ({attachments.length})
          </h2>
          <ul className="space-y-2">
            {attachments.map((att) => (
              <li key={att.id} className="flex items-center gap-2">
                <span className="text-gray-400">📎</span>
                <a
                  href={att.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-sm text-blue-600 hover:underline"
                >
                  {att.name}
                </a>
                {att.file_type && (
                  <span className="text-xs text-gray-400 uppercase">{att.file_type}</span>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* External link */}
      <div className="text-center py-4">
        <a
          href={call.call_url}
          target="_blank"
          rel="noopener noreferrer"
          className="text-blue-600 hover:underline text-sm"
        >
          Zobraziť pôvodnú výzvu na {call.source} →
        </a>
      </div>

      {showFeedback && (
        <FeedbackModal callId={call.id} onClose={() => setShowFeedback(false)} />
      )}
    </div>
  );
}
