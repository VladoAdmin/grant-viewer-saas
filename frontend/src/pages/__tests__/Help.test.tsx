import { render, screen } from '@testing-library/react';
import { BrowserRouter } from 'react-router-dom';
import { describe, it, expect } from 'vitest';
import Help from '../Help';

describe('Help page', () => {
  it('renders main heading', () => {
    render(<BrowserRouter><Help /></BrowserRouter>);
    expect(screen.getByText('Pomoc a návod')).toBeInTheDocument();
  });

  it('renders all sections', () => {
    render(<BrowserRouter><Help /></BrowserRouter>);
    expect(screen.getByText(/Čo je Grant Viewer/)).toBeInTheDocument();
    expect(screen.getByText(/Prehľad výziev/)).toBeInTheDocument();
    expect(screen.getByText(/Kontextové vyhľadávanie/)).toBeInTheDocument();
    expect(screen.getByText(/Export do PDF/)).toBeInTheDocument();
    expect(screen.getByText(/Podnety a opravy/)).toBeInTheDocument();
    expect(screen.getByText(/Zdroje údajov/)).toBeInTheDocument();
  });

  it('renders example queries', () => {
    render(<BrowserRouter><Help /></BrowserRouter>);
    expect(screen.getByText(/Kto môže žiadať/)).toBeInTheDocument();
  });
});
