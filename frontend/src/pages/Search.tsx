import { useState } from 'react';
import { search, type SearchResult } from '../lib/api';
import ChunkResult from '../components/ChunkResult';

const EXAMPLE_QUERIES = [
  'Kto môže žiadať o dotáciu na energetiku?',
  'Podmienky pre neziskové organizácie',
  'Maximálna výška príspevku',
  'Hodnotiace kritériá',
  'Oprávnené náklady na rekonštrukciu',
];

export default function Search() {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<SearchResult[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [tookMs, setTookMs] = useState<number | null>(null);
  const [hasSearched, setHasSearched] = useState(false);

  async function handleSearch(q?: string) {
    const searchQuery = q || query;
    if (!searchQuery.trim()) return;

    setQuery(searchQuery);
    setLoading(true);
    setError(null);
    setHasSearched(true);

    try {
      const resp = await search(searchQuery.trim(), { limit: 10 });
      setResults(resp.results);
      setTookMs(resp.took_ms);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Vyhľadávanie zlyhalo');
      setResults([]);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div>
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-gray-900">Kontextové vyhľadávanie</h1>
        <p className="mt-1 text-sm text-gray-600">
          Hľadajte v obsahu výziev pomocou prirodzeného jazyka
        </p>
      </div>

      {/* Search box */}
      <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-6 mb-6">
        <form
          onSubmit={(e) => {
            e.preventDefault();
            handleSearch();
          }}
        >
          <div className="flex gap-3">
            <textarea
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Napíšte otázku, napr. 'Kto môže žiadať o dotáciu na energetiku?'"
              rows={2}
              className="flex-1 rounded-md border border-gray-300 px-4 py-3 text-sm focus:ring-blue-500 focus:border-blue-500 resize-none"
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault();
                  handleSearch();
                }
              }}
            />
            <button
              type="submit"
              disabled={loading || !query.trim()}
              className="bg-blue-600 text-white rounded-md px-6 py-3 text-sm font-medium hover:bg-blue-700 disabled:opacity-50 transition-colors self-end"
            >
              {loading ? '🔍 Hľadám...' : '🔍 Hľadať'}
            </button>
          </div>
        </form>

        {/* Example queries */}
        {!hasSearched && (
          <div className="mt-4">
            <p className="text-xs font-medium text-gray-500 mb-2">Skúste napríklad:</p>
            <div className="flex flex-wrap gap-2">
              {EXAMPLE_QUERIES.map((eq) => (
                <button
                  key={eq}
                  onClick={() => handleSearch(eq)}
                  className="text-xs bg-gray-100 hover:bg-blue-50 hover:text-blue-700 text-gray-600 rounded-full px-3 py-1.5 transition-colors"
                >
                  {eq}
                </button>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* Error */}
      {error && (
        <div className="bg-red-50 border border-red-200 rounded-md p-4 mb-4">
          <p className="text-red-700 text-sm">{error}</p>
        </div>
      )}

      {/* Loading */}
      {loading && (
        <div className="text-center py-12">
          <div className="animate-spin rounded-full h-10 w-10 border-b-2 border-blue-600 mx-auto mb-3"></div>
          <p className="text-gray-500">Hľadám v databáze výziev...</p>
        </div>
      )}

      {/* Results */}
      {!loading && hasSearched && (
        <div>
          <div className="flex items-center justify-between mb-4">
            <p className="text-sm text-gray-600">
              {results.length > 0
                ? `Nájdených ${results.length} výsledkov`
                : 'Žiadne výsledky'}
              {tookMs !== null && ` (${(tookMs / 1000).toFixed(1)}s)`}
            </p>
          </div>

          {results.length === 0 ? (
            <div className="text-center py-12 bg-white rounded-lg border border-gray-200">
              <p className="text-gray-500 text-lg">Žiadne výsledky pre vašu otázku</p>
              <p className="text-gray-400 text-sm mt-1">Skúste iné kľúčové slová</p>
            </div>
          ) : (
            <div className="space-y-4">
              {results.map((result) => (
                <ChunkResult key={result.id} result={result} />
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
