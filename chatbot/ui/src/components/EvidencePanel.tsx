import { BookOpen, ExternalLink } from "lucide-react";
import type { Citation } from "../lib/types";

export function EvidencePanel({ sources }: { sources: Citation[] }) {
  if (sources.length === 0) {
    return null;
  }
  return (
    <details className="detail-panel">
      <summary>
        <BookOpen aria-hidden="true" />
        Nguồn bằng chứng ({sources.length})
      </summary>
      <ol className="source-list">
        {sources.map((source) => (
          <li key={source.paper_id}>
            <a href={source.url} target="_blank" rel="noreferrer">
              <span>{source.title}</span>
              <ExternalLink aria-hidden="true" />
            </a>
            <small>{source.paper_id}</small>
          </li>
        ))}
      </ol>
    </details>
  );
}

