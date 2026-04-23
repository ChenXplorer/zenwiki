interface Props {
  onStatus: () => void;
  onLint: () => void;
  onRebuildIndex: () => void;
}

export default function Header({ onStatus, onLint, onRebuildIndex }: Props) {
  return (
    <div className="header">
      <h1>
        <span>Zen</span>Wiki
      </h1>
      <div className="header-actions">
        <button onClick={onStatus}>Status</button>
        <button onClick={onLint}>Lint</button>
        <button onClick={onRebuildIndex}>Rebuild Index</button>
      </div>
    </div>
  );
}
