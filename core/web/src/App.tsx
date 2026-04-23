import { useState, useCallback } from "react";
import Header from "./components/Header";
import Sidebar from "./components/Sidebar";
import Viewer from "./components/Viewer";
import SearchBar from "./components/SearchBar";
import type { ViewMode } from "./components/Viewer";

export default function App() {
  const [viewMode, setViewMode] = useState<ViewMode>({ kind: "empty" });
  const [activePath, setActivePath] = useState<string | null>(null);

  const openDoc = useCallback((path: string) => {
    setActivePath(path);
    setViewMode({ kind: "doc", path });
  }, []);

  return (
    <>
      <Header
        onStatus={() => {
          setActivePath(null);
          setViewMode({ kind: "status" });
        }}
        onLint={() => {
          setActivePath(null);
          setViewMode({ kind: "lint" });
        }}
        onRebuildIndex={() => {
          setActivePath(null);
          setViewMode({ kind: "rebuild" });
        }}
      />
      <Sidebar activePath={activePath} onSelect={openDoc} />
      <div className="viewer">
        <Viewer mode={viewMode} onNavigate={openDoc} />
      </div>
      <SearchBar onSelect={openDoc} />
    </>
  );
}
