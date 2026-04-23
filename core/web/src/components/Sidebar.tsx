import { useEffect, useState } from "react";
import type { TreeNode as TNode } from "../types";
import { fetchTree } from "../api";
import TreeNode from "./TreeNode";

interface Props {
  activePath: string | null;
  onSelect: (path: string) => void;
}

export default function Sidebar({ activePath, onSelect }: Props) {
  const [tree, setTree] = useState<TNode[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);

  useEffect(() => {
    let cancelled = false;
    fetchTree()
      .then((data) => {
        if (cancelled) return;
        setTree(data);
        setLoading(false);
        setError(null);
      })
      .catch((err) => {
        if (cancelled) return;
        setError(err.message ?? String(err));
        setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const handleRefresh = () => {
    setRefreshing(true);
    fetchTree()
      .then((data) => {
        setTree(data);
        setError(null);
      })
      .catch((err) => setError(err.message ?? String(err)))
      .finally(() => setRefreshing(false));
  };

  return (
    <div className="sidebar">
      <div className="sidebar-toolbar">
        <button
          className="sidebar-refresh-btn"
          onClick={handleRefresh}
          disabled={refreshing}
          title="Refresh tree"
        >
          <span className={refreshing ? "spin" : ""}>&#x21bb;</span>
        </button>
      </div>
      {loading && <div className="sidebar-loading">Loading...</div>}
      {error && <div className="sidebar-error">Error: {error}</div>}
      {!loading &&
        !error &&
        tree.map((root, i) => (
          <TreeNode
            key={root.name ?? i}
            node={root}
            activePath={activePath}
            onSelect={onSelect}
          />
        ))}
    </div>
  );
}
