import { render, screen } from '@testing-library/react';
import { BrowserRouter } from 'react-router-dom';
import { describe, it, expect } from 'vitest';
import CallCard from '../CallCard';
import type { GrantCall } from '../../lib/api';

const mockCall: GrantCall = {
  id: 1,
  source: 'portal.itms21.sk',
  source_url: 'https://portal.itms21.sk',
  call_url: 'https://portal.itms21.sk/vyhlasena-vyzva/?id=1',
  title: 'Výstavba stokovej siete',
  announced_at: '2024-01-15',
  deadline_at: '2025-06-30',
  provider: 'Ministerstvo životného prostredia SR',
  call_type: 'dopytovo-orientovaná',
  total_allocation: '5000000',
  status: 'Otvorená',
  created_at: '2024-01-01T00:00:00Z',
  updated_at: '2024-01-01T00:00:00Z',
};

function renderWithRouter(ui: React.ReactElement) {
  return render(<BrowserRouter>{ui}</BrowserRouter>);
}

describe('CallCard', () => {
  it('renders call title', () => {
    renderWithRouter(<CallCard call={mockCall} />);
    expect(screen.getByText('Výstavba stokovej siete')).toBeInTheDocument();
  });

  it('renders provider', () => {
    renderWithRouter(<CallCard call={mockCall} />);
    expect(screen.getByText(/Ministerstvo životného prostredia SR/)).toBeInTheDocument();
  });

  it('renders source badge', () => {
    renderWithRouter(<CallCard call={mockCall} />);
    expect(screen.getByText('portal.itms21.sk')).toBeInTheDocument();
  });

  it('renders status badge', () => {
    renderWithRouter(<CallCard call={mockCall} />);
    expect(screen.getByText('Otvorená')).toBeInTheDocument();
  });

  it('links to call detail', () => {
    renderWithRouter(<CallCard call={mockCall} />);
    const link = screen.getByRole('link');
    expect(link).toHaveAttribute('href', '/call/1');
  });
});
