import { Link } from 'react-router-dom';
import type { SearchResult } from '../lib/api';

function highlightSnippet(text: string, maxLen = 400): string {
  if (text.length <= maxLen) return text;
  return text.slice(0, maxLen) + '...';
}

export default function ChunkResult({ result }: { result: SearchResult }) {
  const similarity = Math.round(result.similarity * 100);

  return (
    <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-5 hover:border-blue-200 transition-colors">
      <div className="flex items-start justify-between gap-3 mb-2">
        <Link
          to={`/call/${result.call_id}`}
          className="text-blue-600 hover:underline font-medium text-sm line-clamp-1"
        >
          {result.call_title}
        </Link>
        <span className={`shrink-0 text-xs font-medium px-2 py-0.5 rounded ${
          similarity >= 70 ? 'bg-green-100 text-green-700' :
          similarity >= 40 ? 'bg-yellow-100 text-yellow-700' :
          'bg-gray-100 text-gray-600'
        }`}>
          {similarity}% zhoda
        </span>
      </div>

      <p className="text-sm text-gray-700 leading-relaxed whitespace-pre-wrap">
        {highlightSnippet(result.chunk_content)}
      </p>

      <div className="mt-3 flex items-center gap-3 text-xs text-gray-500">
        {result.source && (
          <span>📄 {result.source}</span>
        )}
        {result.doc_type && (
          <span className="bg-gray-100 px-2 py-0.5 rounded">{result.doc_type}</span>
        )}
        <span>#{result.rank}</span>
        {result.rerank_score !== undefined && (
          <span className="bg-purple-100 text-purple-700 px-2 py-0.5 rounded font-medium" title={result.rerank_reason || ''}>
            🧠 {result.rerank_score.toFixed(1)}/10
          </span>
        )}
      </div>
    </div>
  );
}
