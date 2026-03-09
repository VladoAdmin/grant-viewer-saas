import { render, screen } from '@testing-library/react';
import { BrowserRouter } from 'react-router-dom';
import { describe, it, expect } from 'vitest';
import ChunkResult from '../ChunkResult';
import type { SearchResult } from '../../lib/api';

const mockResult: SearchResult = {
  id: 100,
  call_id: 5,
  call_title: 'Výzva na podporu energetickej efektívnosti',
  chunk_content: 'Oprávnení žiadatelia sú obce, mestá a vyššie územné celky.',
  source: 'vyzva.pdf',
  doc_type: 'main',
  similarity: 0.85,
  rank: 1,
};

function renderWithRouter(ui: React.ReactElement) {
  return render(<BrowserRouter>{ui}</BrowserRouter>);
}

describe('ChunkResult', () => {
  it('renders call title as link', () => {
    renderWithRouter(<ChunkResult result={mockResult} />);
    const link = screen.getByRole('link');
    expect(link).toHaveTextContent('Výzva na podporu energetickej efektívnosti');
    expect(link).toHaveAttribute('href', '/call/5');
  });

  it('renders chunk content', () => {
    renderWithRouter(<ChunkResult result={mockResult} />);
    expect(screen.getByText(/Oprávnení žiadatelia/)).toBeInTheDocument();
  });

  it('renders similarity percentage', () => {
    renderWithRouter(<ChunkResult result={mockResult} />);
    expect(screen.getByText('85% zhoda')).toBeInTheDocument();
  });

  it('renders source and doc_type', () => {
    renderWithRouter(<ChunkResult result={mockResult} />);
    expect(screen.getByText(/vyzva.pdf/)).toBeInTheDocument();
    expect(screen.getByText('main')).toBeInTheDocument();
  });
});
