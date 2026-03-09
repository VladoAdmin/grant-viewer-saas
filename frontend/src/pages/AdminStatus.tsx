import { useState, useEffect } from 'react';
import { getAdminStatus, triggerScraper, type AdminStatus as AdminStatusType } from '../lib/api';

function formatDate(dateStr: string | null | undefined): string {
  if (!dateStr) return '—';
  try {
    const d = new Date(dateStr);
    return d.toLocaleString('sk-SK', {
      day: '2-digit',
      month: '2-digit',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  } catch {
    return String(dateStr).slice(0, 19);
  }
}

export default function AdminStatus() {
  const [status, setStatus] = useState<AdminStatusType | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [triggering, setTriggering] = useState<string | null>(null);
  const [triggerMessage, setTriggerMessage] = useState<string | null>(null);

  async function fetchStatus() {
    setLoading(true);
    setError(null);
    try {
      const data = await getAdminStatus();
      setStatus(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Nastala chyba');
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    fetchStatus();
  }, []);

  async function handleTrigger(source: string) {
    setTriggering(source);
    setTriggerMessage(null);
    try {
      const resp = await triggerScraper(source);
      setTriggerMessage(resp.message);
      // Refresh status after short delay
      setTimeout(fetchStatus, 3000);
    } catch (err) {
      setTriggerMessage(`Chyba: ${err instanceof Error ? err.message : 'Unknown'}`);
    } finally {
      setTriggering(null);
    }
  }

  if (loading) {
    return (
      <div className="animate-pulse space-y-4">
        <div className="h-8 bg-gray-200 rounded w-1/4"></div>
        <div className="h-32 bg-gray-100 rounded"></div>
        <div className="h-48 bg-gray-100 rounded"></div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="bg-red-50 border border-red-200 rounded-md p-6">
        <p className="text-red-700">{error}</p>
        <button onClick={fetchStatus} className="mt-2 text-blue-600 hover:underline text-sm">
          Skúsiť znova
        </button>
      </div>
    );
  }

  const sources = status?.sources || {};
  const stats = status?.stats || { total_calls: 0, total_chunks: 0 };
  const recentRuns = (status?.recent_runs || []) as Array<Record<string, unknown>>;

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Admin Dashboard</h1>
          <p className="mt-1 text-sm text-gray-600">Stav scrapera a systémové štatistiky</p>
        </div>
        <button
          onClick={fetchStatus}
          className="text-sm text-blue-600 hover:underline"
        >
          🔄 Obnoviť
        </button>
      </div>

      {/* Stats overview */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 mb-6">
        <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-5">
          <p className="text-sm text-gray-500">Celkový počet výziev</p>
          <p className="text-3xl font-bold text-gray-900 mt-1">{stats.total_calls}</p>
        </div>
        <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-5">
          <p className="text-sm text-gray-500">Celkový počet chunkov</p>
          <p className="text-3xl font-bold text-gray-900 mt-1">{stats.total_chunks}</p>
        </div>
        <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-5">
          <p className="text-sm text-gray-500">Aktívne zdroje</p>
          <p className="text-3xl font-bold text-gray-900 mt-1">{Object.keys(sources).length}</p>
        </div>
      </div>

      {/* Sources */}
      <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-6 mb-6">
        <h2 className="text-lg font-semibold text-gray-900 mb-4">Zdroje</h2>

        {Object.keys(sources).length === 0 ? (
          <p className="text-gray-500 text-sm">Žiadne scraper runs zatiaľ.</p>
        ) : (
          <div className="space-y-3">
            {Object.entries(sources).map(([sourceName, run]) => {
              const r = run as Record<string, unknown>;
              return (
                <div key={sourceName} className="flex items-center justify-between p-3 bg-gray-50 rounded-md">
                  <div>
                    <p className="font-medium text-gray-900">{sourceName}</p>
                    <div className="text-xs text-gray-500 mt-0.5 space-x-3">
                      <span>Status: {(r.status as string) || '—'}</span>
                      <span>Posledný run: {formatDate(r.started_at as string)}</span>
                      <span>Nájdených: {(r.calls_found as number) || 0}</span>
                      <span>Nových: {(r.calls_new as number) || 0}</span>
                    </div>
                  </div>
                  <span className={`text-xs px-2 py-1 rounded font-medium ${
                    r.status === 'success' ? 'bg-green-100 text-green-700' :
                    r.status === 'error' ? 'bg-red-100 text-red-700' :
                    r.status === 'running' ? 'bg-yellow-100 text-yellow-700' :
                    'bg-gray-100 text-gray-600'
                  }`}>
                    {(r.status as string) || '?'}
                  </span>
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* Trigger buttons */}
      <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-6 mb-6">
        <h2 className="text-lg font-semibold text-gray-900 mb-4">Manuálny trigger</h2>
        <div className="flex flex-wrap gap-3">
          <button
            onClick={() => handleTrigger('itms21')}
            disabled={triggering !== null}
            className="bg-blue-600 text-white rounded-md px-4 py-2 text-sm font-medium hover:bg-blue-700 disabled:opacity-50 transition-colors"
          >
            {triggering === 'itms21' ? 'Spúšťam...' : 'Scrape ITMS21'}
          </button>
          <button
            onClick={() => handleTrigger('all')}
            disabled={triggering !== null}
            className="bg-green-600 text-white rounded-md px-4 py-2 text-sm font-medium hover:bg-green-700 disabled:opacity-50 transition-colors"
          >
            {triggering === 'all' ? 'Spúšťam...' : 'Scrape All'}
          </button>
        </div>
        {triggerMessage && (
          <p className="mt-3 text-sm text-gray-600">{triggerMessage}</p>
        )}
      </div>

      {/* Recent runs table */}
      {recentRuns.length > 0 && (
        <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-6">
          <h2 className="text-lg font-semibold text-gray-900 mb-4">Posledné runs</h2>
          <div className="overflow-x-auto">
            <table className="min-w-full text-sm">
              <thead>
                <tr className="border-b border-gray-200">
                  <th className="text-left py-2 px-3 text-gray-600 font-medium">Zdroj</th>
                  <th className="text-left py-2 px-3 text-gray-600 font-medium">Status</th>
                  <th className="text-left py-2 px-3 text-gray-600 font-medium">Začiatok</th>
                  <th className="text-left py-2 px-3 text-gray-600 font-medium">Nájdených</th>
                  <th className="text-left py-2 px-3 text-gray-600 font-medium">Nových</th>
                  <th className="text-left py-2 px-3 text-gray-600 font-medium">Chyba</th>
                </tr>
              </thead>
              <tbody>
                {recentRuns.map((run, i) => (
                  <tr key={i} className="border-b border-gray-100">
                    <td className="py-2 px-3">{run.source as string}</td>
                    <td className="py-2 px-3">
                      <span className={`text-xs px-2 py-0.5 rounded ${
                        run.status === 'success' ? 'bg-green-100 text-green-700' :
                        run.status === 'error' ? 'bg-red-100 text-red-700' :
                        'bg-yellow-100 text-yellow-700'
                      }`}>
                        {run.status as string}
                      </span>
                    </td>
                    <td className="py-2 px-3 text-gray-600">{formatDate(run.started_at as string)}</td>
                    <td className="py-2 px-3">{run.calls_found as number}</td>
                    <td className="py-2 px-3">{run.calls_new as number}</td>
                    <td className="py-2 px-3 text-red-600 text-xs max-w-xs truncate">
                      {(run.error_message as string) || '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
