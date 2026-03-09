import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, it, expect, vi } from 'vitest';
import FeedbackModal from '../FeedbackModal';

describe('FeedbackModal', () => {
  it('renders the modal with form fields', () => {
    render(<FeedbackModal onClose={() => {}} />);
    expect(screen.getByText('Podnet / Oprava')).toBeInTheDocument();
    expect(screen.getByText('Typ podnetu')).toBeInTheDocument();
    expect(screen.getByPlaceholderText(/Popíšte problém/)).toBeInTheDocument();
    expect(screen.getByText('Odoslať podnet')).toBeInTheDocument();
  });

  it('calls onClose when close button is clicked', async () => {
    const onClose = vi.fn();
    const user = userEvent.setup();
    render(<FeedbackModal onClose={onClose} />);
    await user.click(screen.getByText('Zrušiť'));
    expect(onClose).toHaveBeenCalled();
  });

  it('disables submit when message is empty', () => {
    render(<FeedbackModal onClose={() => {}} />);
    const submitBtn = screen.getByText('Odoslať podnet');
    expect(submitBtn).toBeDisabled();
  });

  it('enables submit when message is provided', async () => {
    const user = userEvent.setup();
    render(<FeedbackModal onClose={() => {}} />);

    await user.type(screen.getByPlaceholderText(/Popíšte problém/), 'Test feedback');
    const submitBtn = screen.getByText('Odoslať podnet');
    expect(submitBtn).not.toBeDisabled();
  });
});
