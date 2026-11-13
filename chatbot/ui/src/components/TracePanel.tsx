import { Route } from "lucide-react";
import type { TraceStep } from "../lib/types";

export function TracePanel({ steps, stopReason }: { steps: TraceStep[]; stopReason: string }) {
  if (steps.length === 0) {
    return null;
  }
  return (
    <details className="detail-panel detail-panel--trace">
      <summary>
        <Route aria-hidden="true" />
        Các bước truy vấn graph ({steps.length}/5)
      </summary>
      <ol className="trace-list">
        {steps.map((step) => (
          <li key={`${step.iteration}-${step.action}`}>
            <span className={`trace-marker trace-marker--${step.status}`}>{step.iteration}</span>
            <div>
              <strong>{step.action.replaceAll("_", " ")}</strong>
              <p>
                {step.records} bản ghi · {step.new_facts} fact mới · {step.duration_ms} ms
              </p>
            </div>
          </li>
        ))}
      </ol>
      <p className="stop-reason">Dừng: {stopReason.replaceAll("_", " ")}</p>
    </details>
  );
}

