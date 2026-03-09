import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, it, expect, vi } from 'vitest';
import FilterBar from '../FilterBar';

describe('FilterBar', () => {
  it('renders filter inputs', () => {
    render(<FilterBar onFilter={() => {}} />);
    expect(screen.getByPlaceholderText(/Zadajte kľúčové slovo/)).toBeInTheDocument();
    expect(screen.getByText('Filtrovať')).toBeInTheDocument();
    expect(screen.getByText('Vyčistiť')).toBeInTheDocument();
  });

  it('calls onFilter with search text', async () => {
    const onFilter = vi.fn();
    const user = userEvent.setup();
    render(<FilterBar onFilter={onFilter} />);

    const input = screen.getByPlaceholderText(/Zadajte kľúčové slovo/);
    await user.type(input, 'energetika');
    await user.click(screen.getByText('Filtrovať'));

    expect(onFilter).toHaveBeenCalledWith({ search: 'energetika' });
  });

  it('calls onFilter with empty object on clear', async () => {
    const onFilter = vi.fn();
    const user = userEvent.setup();
    render(<FilterBar onFilter={onFilter} />);

    await user.click(screen.getByText('Vyčistiť'));
    expect(onFilter).toHaveBeenCalledWith({});
  });

  it('shows loading state', () => {
    render(<FilterBar onFilter={() => {}} loading />);
    expect(screen.getByText('Načítavam...')).toBeInTheDocument();
  });
});
