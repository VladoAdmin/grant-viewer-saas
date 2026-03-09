import { Link } from 'react-router-dom';
import type { GrantCall } from '../lib/api';

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

function StatusBadge({ status }: { status: string | null }) {
  if (!status) return null;
  const lower = status.toLowerCase();
  let color = 'bg-gray-100 text-gray-700';
  if (lower.includes('otvor') || lower.includes('vyhlás')) color = 'bg-green-100 text-green-800';
  else if (lower.includes('uzavr')) color = 'bg-red-100 text-red-800';
  else if (lower.includes('plán') || lower.includes('priprav')) color = 'bg-yellow-100 text-yellow-800';

  return (
    <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${color}`}>
      {status}
    </span>
  );
}

export default function CallCard({ call }: { call: GrantCall }) {
  return (
    <Link
      to={`/call/${call.id}`}
      className="block bg-white rounded-lg shadow-sm border border-gray-200 hover:shadow-md hover:border-blue-300 transition-all p-5"
    >
      <div className="flex items-start justify-between gap-3">
        <h3 className="text-base font-semibold text-gray-900 line-clamp-2 flex-1">
          {call.title}
        </h3>
        <StatusBadge status={call.status} />
      </div>

      <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-sm text-gray-600">
        {call.provider && (
          <span>🏢 {call.provider}</span>
        )}
        <span>📅 Deadline: {formatDate(call.deadline_at)}</span>
        <span>💰 {formatAllocation(call.total_allocation)}</span>
      </div>

      <div className="mt-2 flex items-center gap-2">
        <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-blue-50 text-blue-700">
          {call.source}
        </span>
        {call.call_type && (
          <span className="text-xs text-gray-500">{call.call_type}</span>
        )}
      </div>
    </Link>
  );
}
