import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { deleteAnalysis, listAnalyses } from "../api/client";

const AnalysesContext = createContext(null);

export function AnalysesProvider({ children }) {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await listAnalyses();
      setItems(Array.isArray(data) ? data : []);
    } catch (e) {
      // 404는 "아직 이력이 없음"으로 간주해 빈 상태 UI로 폴백.
      // 5xx·네트워크 오류 등만 사용자에게 노출.
      if (e?.response?.status === 404) {
        setItems([]);
      } else {
        setError("분석 이력을 불러오지 못했습니다.");
        setItems([]);
      }
    } finally {
      setLoading(false);
    }
  }, []);

  const remove = useCallback(
    async (id) => {
      await deleteAnalysis(id);
      await refresh();
    },
    [refresh],
  );

  useEffect(() => {
    refresh();
  }, [refresh]);

  return (
    <AnalysesContext.Provider value={{ items, loading, error, refresh, remove }}>
      {children}
    </AnalysesContext.Provider>
  );
}

export function useAnalyses() {
  const ctx = useContext(AnalysesContext);
  if (!ctx) {
    throw new Error("useAnalyses는 AnalysesProvider 하위에서만 사용 가능합니다.");
  }
  return ctx;
}
