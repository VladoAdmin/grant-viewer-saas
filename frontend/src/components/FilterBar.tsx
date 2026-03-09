import { useState } from 'react';

interface FilterBarProps {
  onFilter: (filters: Record<string, string>) => void;
  loading?: boolean;
}

export default function FilterBar({ onFilter, loading }: FilterBarProps) {
  const [source, setSource] = useState('');
  const [search, setSearch] = useState('');
  const [deadlineAfter, setDeadlineAfter] = useState('');
  const [deadlineBefore, setDeadlineBefore] = useState('');

  function handleApply() {
    const filters: Record<string, string> = {};
    if (source) filters.source = source;
    if (search.trim()) filters.search = search.trim();
    if (deadlineAfter) filters.deadline_after = deadlineAfter;
    if (deadlineBefore) filters.deadline_before = deadlineBefore;
    onFilter(filters);
  }

  function handleClear() {
    setSource('');
    setSearch('');
    setDeadlineAfter('');
    setDeadlineBefore('');
    onFilter({});
  }

  return (
    <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-4 mb-6">
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-3">
        {/* Text search */}
        <div>
          <label className="block text-xs font-medium text-gray-600 mb-1">Hľadať v názve</label>
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Zadajte kľúčové slovo..."
            className="w-full rounded-md border-gray-300 shadow-sm text-sm px-3 py-2 border focus:ring-blue-500 focus:border-blue-500"
            onKeyDown={(e) => e.key === 'Enter' && handleApply()}
          />
        </div>

        {/* Source filter */}
        <div>
          <label className="block text-xs font-medium text-gray-600 mb-1">Zdroj</label>
          <select
            value={source}
            onChange={(e) => setSource(e.target.value)}
            className="w-full rounded-md border-gray-300 shadow-sm text-sm px-3 py-2 border focus:ring-blue-500 focus:border-blue-500"
          >
            <option value="">Všetky zdroje</option>
            <option value="portal.itms21.sk">ITMS21</option>
          </select>
        </div>

        {/* Deadline range */}
        <div>
          <label className="block text-xs font-medium text-gray-600 mb-1">Deadline od</label>
          <input
            type="date"
            value={deadlineAfter}
            onChange={(e) => setDeadlineAfter(e.target.value)}
            className="w-full rounded-md border-gray-300 shadow-sm text-sm px-3 py-2 border focus:ring-blue-500 focus:border-blue-500"
          />
        </div>

        <div>
          <label className="block text-xs font-medium text-gray-600 mb-1">Deadline do</label>
          <input
            type="date"
            value={deadlineBefore}
            onChange={(e) => setDeadlineBefore(e.target.value)}
            className="w-full rounded-md border-gray-300 shadow-sm text-sm px-3 py-2 border focus:ring-blue-500 focus:border-blue-500"
          />
        </div>

        {/* Buttons */}
        <div className="flex items-end gap-2">
          <button
            onClick={handleApply}
            disabled={loading}
            className="flex-1 bg-blue-600 text-white rounded-md px-4 py-2 text-sm font-medium hover:bg-blue-700 disabled:opacity-50 transition-colors"
          >
            {loading ? 'Načítavam...' : 'Filtrovať'}
          </button>
          <button
            onClick={handleClear}
            className="text-gray-600 hover:text-gray-800 rounded-md px-3 py-2 text-sm border border-gray-300 hover:bg-gray-50 transition-colors"
          >
            Vyčistiť
          </button>
        </div>
      </div>
    </div>
  );
}
