import { BrowserRouter, Routes, Route, Link, useLocation } from 'react-router-dom';
import CallList from './pages/CallList';
import CallDetail from './pages/CallDetail';
import Search from './pages/Search';
import Help from './pages/Help';
import AdminStatus from './pages/AdminStatus';

function NavLink({ to, children }: { to: string; children: React.ReactNode }) {
  const location = useLocation();
  const isActive = location.pathname === to || (to !== '/' && location.pathname.startsWith(to));
  return (
    <Link
      to={to}
      className={`px-3 py-2 rounded-md text-sm font-medium transition-colors ${
        isActive
          ? 'bg-blue-700 text-white'
          : 'text-blue-100 hover:bg-blue-600 hover:text-white'
      }`}
    >
      {children}
    </Link>
  );
}

function Layout() {
  return (
    <div className="min-h-screen bg-gray-50">
      {/* Header */}
      <nav className="bg-blue-800 shadow-lg">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex items-center justify-between h-16">
            <div className="flex items-center">
              <Link to="/" className="text-white text-xl font-bold">
                📋 Grant Viewer
              </Link>
              <div className="ml-10 flex items-baseline space-x-2">
                <NavLink to="/">Výzvy</NavLink>
                <NavLink to="/search">Vyhľadávanie</NavLink>
                <NavLink to="/help">Pomoc</NavLink>
                <NavLink to="/admin">Admin</NavLink>
              </div>
            </div>
          </div>
        </div>
      </nav>

      {/* Main content */}
      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        <Routes>
          <Route path="/" element={<CallList />} />
          <Route path="/call/:id" element={<CallDetail />} />
          <Route path="/search" element={<Search />} />
          <Route path="/help" element={<Help />} />
          <Route path="/admin" element={<AdminStatus />} />
        </Routes>
      </main>

      {/* Footer */}
      <footer className="bg-gray-100 border-t mt-auto">
        <div className="max-w-7xl mx-auto px-4 py-4 text-center text-sm text-gray-500">
          Grant Viewer SaaS &copy; {new Date().getFullYear()} | Powered by ITMS21 data
        </div>
      </footer>
    </div>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <Layout />
    </BrowserRouter>
  );
}
