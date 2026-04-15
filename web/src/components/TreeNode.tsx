import { memo, useState } from "react";
import type { TreeNode as TNode } from "../types";

interface Props {
  node: TNode;
  activePath: string | null;
  onSelect: (path: string) => void;
}

function TreeNode({ node, activePath, onSelect }: Props) {
  const [open, setOpen] = useState(true);

  if (node.type === "dir") {
    const children = node.children ?? [];
    return (
      <div className="tree-section">
        <div className="tree-label" onClick={() => setOpen((v) => !v)}>
          <span className={`arrow ${open ? "open" : ""}`}>&#9654;</span>
          {node.name}
        </div>
        {open && (
          <div className="tree-children">
            {children.map((child, i) => (
              <MemoTreeNode
                key={child.path ?? `${child.name}-${i}`}
                node={child}
                activePath={activePath}
                onSelect={onSelect}
              />
            ))}
          </div>
        )}
      </div>
    );
  }

  const isActive = node.path === activePath;
  return (
    <div
      className={`tree-file ${isActive ? "active" : ""}`}
      title={node.path}
      onClick={() => node.path && onSelect(node.path)}
    >
      {node.name}
    </div>
  );
}

// Memo skips re-render when this subtree's inputs are referentially stable.
// Critical when refreshing a large tree: untouched branches stay mounted
// (preserving their expand/collapse state) and don't walk their children.
const MemoTreeNode = memo(TreeNode);

export default MemoTreeNode;
