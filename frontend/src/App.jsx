import { BrowserRouter, Routes, Route, useNavigate } from "react-router-dom";
import UploadPage from "./pages/UploadPage";
import ResultPage from "./pages/ResultPage";

function Header() {
  const navigate = useNavigate();

  return (
    <header className="app-header" onClick={() => navigate("/")} style={{ cursor: "pointer" }}>
      <div className="header-inner">
        <img src="/logo.png" alt="K&H2" className="header-logo" />
      </div>
    </header>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <div className="app">
        <Header />
        <main className="app-main">
          <Routes>
            <Route path="/" element={<UploadPage />} />
            <Route path="/result" element={<ResultPage />} />
            <Route path="/result/:analysisId" element={<ResultPage />} />
          </Routes>
        </main>
        <footer className="app-footer">
          <div className="footer-inner">
            <span>K&H<sup>2</sup> 계약서 속 독소조항 탐지 시스템</span>
            <span className="footer-dot">&middot;</span>
            <span>AI 기반 법률 분석</span>
          </div>
        </footer>
      </div>
    </BrowserRouter>
  );
}
