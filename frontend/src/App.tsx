import { NavLink, Route, Routes } from "react-router-dom";
import { ToastProvider } from "./components/common";
import DashboardPage from "./pages/DashboardPage";
import JobsPage from "./pages/JobsPage";
import JobDetailPage from "./pages/JobDetailPage";
import ApplicationsPage from "./pages/ApplicationsPage";
import ApplicationDetailPage from "./pages/ApplicationDetailPage";
import ProfilePage from "./pages/ProfilePage";
import SettingsPage from "./pages/SettingsPage";

const nav = [
  { to: "/", label: "Dashboard", icon: "▦" },
  { to: "/jobs", label: "Jobs", icon: "☰" },
  { to: "/applications", label: "Applications", icon: "✓" },
  { to: "/profile", label: "Profile", icon: "☺" },
  { to: "/settings", label: "Settings", icon: "⚙" },
];

export default function App() {
  return (
    <ToastProvider>
      <div className="app-shell">
        <aside className="sidebar">
          <div className="brand">
            Job Agent
            <small>personal AI job assistant</small>
          </div>
          <nav>
            {nav.map((n) => (
              <NavLink key={n.to} to={n.to} end={n.to === "/"} className={({ isActive }) => (isActive ? "active" : "")}>
                <span aria-hidden>{n.icon}</span> {n.label}
              </NavLink>
            ))}
          </nav>
          <div className="foot">
            You stay in control: nothing is submitted automatically.
            <br />
            <a href="/docs" target="_blank" rel="noreferrer" style={{ color: "#9ca3af" }}>
              API docs
            </a>
          </div>
        </aside>
        <main className="main">
          <Routes>
            <Route path="/" element={<DashboardPage />} />
            <Route path="/jobs" element={<JobsPage />} />
            <Route path="/jobs/:id" element={<JobDetailPage />} />
            <Route path="/applications" element={<ApplicationsPage />} />
            <Route path="/applications/:id" element={<ApplicationDetailPage />} />
            <Route path="/profile" element={<ProfilePage />} />
            <Route path="/settings" element={<SettingsPage />} />
            <Route path="*" element={<div className="empty">Page not found</div>} />
          </Routes>
        </main>
      </div>
    </ToastProvider>
  );
}
