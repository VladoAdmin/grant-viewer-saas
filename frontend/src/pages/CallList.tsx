import { useState, useEffect, useCallback } from 'react';
import { getCalls, type GrantCall } from '../lib/api';
import CallCard from '../components/CallCard';
import FilterBar from '../components/FilterBar';

export default function CallList() {
  const [calls, setCalls] = useState<GrantCall[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filters, setFilters] = useState<Record<string, string>>({});

  const limit = 20;

  const fetchCalls = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const params: Record<string, string> = {
        page: String(page),
        limit: String(limit),
        ...filters,
      };
      const resp = await getCalls(params);
      setCalls(resp.data);
      setTotal(resp.total);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Nastala chyba pri načítaní výziev');
    } finally {
      setLoading(false);
    }
  }, [page, filters]);

  useEffect(() => {
    fetchCalls();
  }, [fetchCalls]);

  function handleFilter(newFilters: Record<string, string>) {
    setFilters(newFilters);
    setPage(1);
  }

  const totalPages = Math.ceil(total / limit);

  return (
    <div>
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-gray-900">Otvorené výzvy</h1>
        <p className="mt-1 text-sm text-gray-600">
          Prehľad grantových výziev z ITMS21 a ďalších zdrojov
        </p>
      </div>

      <FilterBar onFilter={handleFilter} loading={loading} />

      {error && (
        <div className="bg-red-50 border border-red-200 rounded-md p-4 mb-4">
          <p className="text-red-700 text-sm">{error}</p>
        </div>
      )}

      {loading && calls.length === 0 ? (
        <div className="space-y-4">
          {[...Array(5)].map((_, i) => (
            <div key={i} className="bg-white rounded-lg border border-gray-200 p-5 animate-pulse">
              <div className="h-5 bg-gray-200 rounded w-3/4 mb-3"></div>
              <div className="h-4 bg-gray-100 rounded w-1/2 mb-2"></div>
              <div className="h-3 bg-gray-100 rounded w-1/4"></div>
            </div>
          ))}
        </div>
      ) : calls.length === 0 ? (
        <div className="text-center py-12 bg-white rounded-lg border border-gray-200">
          <p className="text-gray-500 text-lg">Žiadne výzvy neboli nájdené</p>
          <p className="text-gray-400 text-sm mt-1">Skúste zmeniť filtre</p>
        </div>
      ) : (
        <>
          <div className="flex items-center justify-between mb-4">
            <p className="text-sm text-gray-600">
              Zobrazených {calls.length} z {total} výziev
            </p>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {calls.map((call) => (
              <CallCard key={call.id} call={call} />
            ))}
          </div>

          {/* Pagination */}
          {totalPages > 1 && (
            <div className="flex items-center justify-center gap-2 mt-8">
              <button
                onClick={() => setPage((p) => Math.max(1, p - 1))}
                disabled={page === 1}
                className="px-4 py-2 rounded-md border border-gray-300 text-sm font-medium disabled:opacity-50 hover:bg-gray-50 transition-colors"
              >
                ← Predchádzajúca
              </button>
              <span className="text-sm text-gray-600 px-4">
                Strana {page} z {totalPages}
              </span>
              <button
                onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                disabled={page === totalPages}
                className="px-4 py-2 rounded-md border border-gray-300 text-sm font-medium disabled:opacity-50 hover:bg-gray-50 transition-colors"
              >
                Nasledujúca →
              </button>
            </div>
          )}
        </>
      )}
    </div>
  );
}
