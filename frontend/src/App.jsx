import { useState } from "react";
import { BrowserRouter, Routes, Route, useNavigate } from "react-router-dom";
import UploadPage from "./pages/UploadPage";
import ResultPage from "./pages/ResultPage";
import Sidebar from "./components/Sidebar";
import { AnalysesProvider } from "./context/AnalysesContext";

function Header({ sidebarOpen, onToggleSidebar }) {
  const navigate = useNavigate();

  return (
    <header className="app-header" onClick={() => navigate("/")} style={{ cursor: "pointer" }}>
      <button
        type="button"
        className="sidebar-toggle"
        aria-label={sidebarOpen ? "사이드바 닫기" : "사이드바 열기"}
        aria-expanded={sidebarOpen}
        onClick={(e) => {
          e.stopPropagation();
          onToggleSidebar();
        }}
      >
        <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
          <line x1="3" y1="6" x2="21" y2="6" />
          <line x1="3" y1="12" x2="21" y2="12" />
          <line x1="3" y1="18" x2="21" y2="18" />
        </svg>
      </button>
      <div className="header-inner">
        <img src="/logo.png" alt="K&H2" className="header-logo" />
      </div>
    </header>
  );
}

function AppShell() {
  const [sidebarOpen, setSidebarOpen] = useState(true);

  return (
    <div className="app">
      <Header
        sidebarOpen={sidebarOpen}
        onToggleSidebar={() => setSidebarOpen((v) => !v)}
      />
      <div className="app-body">
        <Sidebar isOpen={sidebarOpen} />
        <main className="app-main">
          <Routes>
            <Route path="/" element={<UploadPage />} />
            <Route path="/result" element={<ResultPage />} />
            <Route path="/result/:analysisId" element={<ResultPage />} />
          </Routes>
        </main>
      </div>
      <footer className="app-footer">
        <div className="footer-inner">
          <span>K&H<sup>2</sup> 계약서 속 독소조항 탐지 시스템</span>
          <span className="footer-dot">&middot;</span>
          <span>AI 기반 법률 분석</span>
        </div>
      </footer>
    </div>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <AnalysesProvider>
        <AppShell />
      </AnalysesProvider>
    </BrowserRouter>
  );
}
