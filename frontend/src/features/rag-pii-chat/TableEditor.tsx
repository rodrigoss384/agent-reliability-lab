import { useEffect, useRef, useState } from "react";
import {
  getKnowledgeDocuments,
  type EmbeddingSummary,
  type KnowledgeDocumentRow,
  type KnowledgeDocumentsResponse,
} from "../../api/client";

interface TableEditorProps {
  onClose: () => void;
}

const PAGE_SIZE = 20;

function formatNumber(n: number): string {
  return n.toLocaleString("en-US", { minimumFractionDigits: 4, maximumFractionDigits: 4 });
}

function Sparkline({ values }: { values: number[] }) {
  if (values.length === 0) return null;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;
  const width = 96;
  const height = 18;
  const stepX = width / (values.length - 1 || 1);
  const points = values
    .map((v, i) => {
      const x = i * stepX;
      const y = height - ((v - min) / range) * height;
      return `${x.toFixed(2)},${y.toFixed(2)}`;
    })
    .join(" ");
  return (
    <svg width={width} height={height} aria-hidden style={{ verticalAlign: "middle" }}>
      <polyline
        fill="none"
        stroke="currentColor"
        strokeWidth={1.5}
        strokeLinecap="round"
        strokeLinejoin="round"
        points={points}
      />
    </svg>
  );
}

function EmbeddingCell({ summary }: { summary: EmbeddingSummary }) {
  const sparkValues = [...summary.first5, ...summary.last5];
  return (
    <div className="te-emb" data-testid="embedding-cell">
      <div className="te-emb-row">
        <span className="te-emb-label">dim</span>
        <span className="text-mono">{summary.dim}</span>
        <span className="te-emb-label">norm</span>
        <span className="text-mono">{formatNumber(summary.l2_norm)}</span>
      </div>
      <div className="te-emb-row">
        <span className="te-emb-label">min</span>
        <span className="text-mono">{formatNumber(summary.min)}</span>
        <span className="te-emb-label">max</span>
        <span className="text-mono">{formatNumber(summary.max)}</span>
        <span className="te-emb-label">mean</span>
        <span className="text-mono">{formatNumber(summary.mean)}</span>
      </div>
      <div className="te-emb-spark" style={{ color: "var(--color-cobalt)" }}>
        <Sparkline values={sparkValues} />
        <span className="te-emb-hint text-muted">first 5 + last 5</span>
      </div>
    </div>
  );
}

function truncate(s: string, n: number): string {
  if (s.length <= n) return s;
  return s.slice(0, n) + "...";
}

export default function TableEditor({ onClose }: TableEditorProps) {
  const [data, setData] = useState<KnowledgeDocumentsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [offset, setOffset] = useState(0);
  const [sourceFilter, setSourceFilter] = useState("");
  const [sourceFilterDraft, setSourceFilterDraft] = useState("");
  const closeRef = useRef<HTMLButtonElement>(null);

  const load = async (nextOffset: number, nextSource: string) => {
    setLoading(true);
    setError(null);
    try {
      const res = await getKnowledgeDocuments(PAGE_SIZE, nextOffset, nextSource || undefined);
      setData(res);
      setOffset(nextOffset);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erro desconhecido");
      setData(null);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load(0, "");
    closeRef.current?.focus();
  }, []);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const total = data?.total ?? 0;
  const rows: KnowledgeDocumentRow[] = data?.rows ?? [];
  const start = total === 0 ? 0 : offset + 1;
  const end = offset + rows.length;

  const goPrev = () => {
    if (offset === 0) return;
    load(Math.max(0, offset - PAGE_SIZE), sourceFilter);
  };
  const goNext = () => {
    if (end >= total) return;
    load(offset + PAGE_SIZE, sourceFilter);
  };
  const applyFilter = () => {
    setSourceFilter(sourceFilterDraft.trim());
    load(0, sourceFilterDraft.trim());
  };

  return (
    <div className="te-overlay" role="dialog" aria-modal="true" aria-label="Table Editor">
      <style>{`
        .te-overlay {
          position: fixed; inset: 0; z-index: 50;
          background-color: var(--bg-canvas);
          color: var(--fg-text);
          font-family: var(--font-sans);
          display: flex; flex-direction: column;
          animation: te-fade 0.18s ease-out;
        }
        @keyframes te-fade {
          from { opacity: 0; }
          to { opacity: 1; }
        }
        .te-header {
          flex-shrink: 0;
          border-bottom: 1px solid var(--border-line);
          padding: 16px 24px;
          display: flex; align-items: center; justify-content: space-between; gap: 16px;
          background-color: var(--bg-canvas);
        }
        .te-title { font-family: var(--font-serif); font-size: 22px; font-weight: 700; line-height: 1.15; margin: 0; }
        .te-subtitle { font-size: 12px; color: var(--fg-muted); letter-spacing: 0.05em; text-transform: uppercase; margin-top: 2px; }
        .te-header-actions { display: flex; gap: 12px; align-items: center; }
        .te-back {
          font-family: var(--font-sans); font-size: 13px; font-weight: 600;
          padding: 9px 16px; border-radius: 6px;
          background-color: var(--color-cobalt); color: var(--color-paper);
          border: 0; cursor: pointer;
        }
        .te-back:hover { opacity: 0.9; }
        .te-toolbar {
          flex-shrink: 0;
          display: flex; align-items: center; gap: 12px;
          padding: 12px 24px;
          border-bottom: 1px solid var(--border-line);
          background-color: var(--bg-surface);
        }
        .te-toolbar input {
          font-family: var(--font-sans); font-size: 13px;
          padding: 6px 10px; border-radius: 6px;
          border: 1px solid var(--border-line);
          background-color: var(--bg-canvas);
          color: var(--fg-text);
          min-width: 220px;
        }
        .te-toolbar input:focus { outline: 2px solid var(--color-cobalt); outline-offset: -1px; }
        .te-btn {
          font-family: var(--font-sans); font-size: 12px; font-weight: 600;
          letter-spacing: 0.04em; text-transform: uppercase;
          padding: 6px 12px; border-radius: 6px;
          background: transparent; color: var(--fg-text);
          border: 1px solid var(--border-line); cursor: pointer;
        }
        .te-btn:hover { background-color: var(--bg-surface-2); border-color: var(--color-cobalt); }
        .te-btn:disabled { opacity: 0.4; cursor: not-allowed; }
        .te-pager { margin-left: auto; font-size: 12px; color: var(--fg-muted); }
        .te-pager button { margin-left: 8px; }
        .te-body {
          flex: 1; overflow: auto; padding: 16px 24px 24px;
        }
        .te-table-wrap {
          border: 1px solid var(--border-line);
          border-radius: 8px;
          overflow: hidden;
          background-color: var(--bg-surface);
        }
        table.te-table { width: 100%; border-collapse: collapse; font-size: 13px; }
        .te-table thead th {
          position: sticky; top: 0; z-index: 1;
          background-color: var(--bg-surface-2);
          text-align: left;
          font-size: 11px; font-weight: 600;
          letter-spacing: 0.04em; text-transform: uppercase;
          color: var(--fg-muted);
          padding: 10px 12px;
          border-bottom: 1px solid var(--border-line);
        }
        .te-table thead th .te-col-type {
          display: block;
          font-family: var(--font-mono); font-size: 10px; font-weight: 500;
          text-transform: none; letter-spacing: 0;
          color: var(--fg-muted); margin-top: 2px;
        }
        .te-table tbody td {
          padding: 10px 12px;
          border-bottom: 1px solid var(--border-line);
          vertical-align: top;
        }
        .te-table tbody tr:last-child td { border-bottom: 0; }
        .te-table tbody tr:hover { background-color: var(--bg-surface-2); }
        .te-content {
          max-width: 360px;
          white-space: pre-wrap;
          word-break: break-word;
        }
        .te-mono { font-family: var(--font-mono); font-size: 12px; }
        .te-emb { font-size: 11px; line-height: 1.5; }
        .te-emb-row { display: flex; gap: 8px; align-items: center; margin-bottom: 2px; }
        .te-emb-label { color: var(--fg-muted); font-family: var(--font-mono); font-size: 10px; min-width: 32px; }
        .te-emb-spark { display: flex; align-items: center; gap: 8px; margin-top: 4px; }
        .te-emb-hint { font-size: 10px; }
        .te-skeleton-row td {
          height: 40px;
          background: linear-gradient(90deg, var(--bg-surface-2), var(--bg-surface), var(--bg-surface-2));
        }
        .te-badge-preco {
          display: inline-block;
          margin-left: 8px;
          padding: 1px 6px;
          border-radius: 4px;
          font-family: var(--font-mono);
          font-size: 10px;
          font-weight: 600;
          letter-spacing: 0.02em;
          color: var(--color-moss);
          border: 1px solid var(--color-moss);
          background-color: transparent;
          vertical-align: middle;
        }
        .te-empty, .te-error {
          padding: 48px 24px; text-align: center; color: var(--fg-muted);
        }
        .te-error { color: var(--color-oxide); }
      `}</style>

      <header className="te-header">
        <div>
          <h2 className="te-title">Table Editor</h2>
          <div className="te-subtitle">
            {data ? `${data.table.name} — ${total} linha${total === 1 ? "" : "s"}` : "knowledge_documents"}
          </div>
        </div>
        <div className="te-header-actions">
          <button
            ref={closeRef}
            type="button"
            className="te-back"
            onClick={onClose}
            data-testid="table-editor-back"
            aria-label="Voltar para o chat"
          >
            ← Voltar
          </button>
        </div>
      </header>

      <div className="te-toolbar">
        <input
          type="text"
          placeholder="Filtrar por source (ex: planos.md)"
          value={sourceFilterDraft}
          onChange={(e) => setSourceFilterDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") applyFilter();
          }}
          data-testid="table-editor-source-filter"
          aria-label="Filtrar por source"
        />
        <button type="button" className="te-btn" onClick={applyFilter} data-testid="table-editor-apply-filter">
          Aplicar
        </button>
        {sourceFilter && (
          <button
            type="button"
            className="te-btn"
            onClick={() => {
              setSourceFilterDraft("");
              setSourceFilter("");
              load(0, "");
            }}
            data-testid="table-editor-clear-filter"
          >
            Limpar
          </button>
        )}
        <div className="te-pager">
          {loading ? "carregando..." : `${start}–${end} de ${total}`}
          <button type="button" className="te-btn" onClick={goPrev} disabled={offset === 0 || loading}>
            ← Anterior
          </button>
          <button type="button" className="te-btn" onClick={goNext} disabled={end >= total || loading}>
            Próxima →
          </button>
        </div>
      </div>

      <div className="te-body">
        {error && (
          <div className="te-error" role="alert">
            <p>Erro ao carregar: {error}</p>
            <button type="button" className="te-btn" onClick={() => load(offset, sourceFilter)}>
              Tentar novamente
            </button>
          </div>
        )}

        {!error && loading && (
          <div className="te-table-wrap">
            <table className="te-table">
              <thead>
                <tr>
                  <th>source</th>
                  <th>content</th>
                  <th>embedding</th>
                  <th>created_at</th>
                </tr>
              </thead>
              <tbody>
                {Array.from({ length: 5 }).map((_, i) => (
                  <tr key={i} className="te-skeleton-row">
                    <td colSpan={4} />
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {!error && !loading && rows.length === 0 && (
          <div className="te-empty">Nenhuma linha para exibir.</div>
        )}

        {!error && !loading && rows.length > 0 && data && (
          <div className="te-table-wrap" data-testid="table-editor-table">
            <table className="te-table">
              <thead>
                <tr>
                  {data.table.columns.map((col) => (
                    <th key={col.name}>
                      {col.name}
                      {col.primary_key && <span style={{ marginLeft: 4 }} title="Primary key">🔑</span>}
                      <span className="te-col-type">{col.type}</span>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr key={row.id} data-testid="table-editor-row">
                    <td><span className="te-mono">{truncate(row.id, 8)}</span></td>
                    <td>
                      <span className="te-mono">{row.source}</span>
                      {row.preco_publico && (
                        <span className="te-badge-preco" title="preco_publico: regex de R$ nao bloqueia">preco_publico</span>
                      )}
                    </td>
                    <td>
                      <div className="te-content" title={row.content}>{row.content}</div>
                    </td>
                    <td>
                      <EmbeddingCell summary={row.embedding_summary} />
                    </td>
                    <td><span className="te-mono">{row.created_at ?? "—"}</span></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
