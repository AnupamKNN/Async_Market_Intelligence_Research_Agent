import type { ResearchVisualizations as ResearchVisualizationsData } from "../../services/research";
import ResearchChart from "./ResearchChart";
import "./ResearchChart.css";

interface ResearchVisualizationsProps {
  visualizations?: ResearchVisualizationsData | null;
}

export function ResearchVisualizationsPanel({
  visualizations,
}: ResearchVisualizationsProps) {
  const charts = visualizations?.charts ?? [];
  const warnings = visualizations?.warnings ?? [];

  if (charts.length === 0 && warnings.length === 0) {
    return null;
  }

  return (
    <section
      className="research-visualizations"
      aria-label="Interactive research visualizations"
    >
      {charts.length > 0 && (
        <>
          <div className="research-visualizations-heading">
            <div>
              <h2>Interactive visualizations</h2>
              <p>
                Explore the analytical findings through interactive charts.
              </p>
            </div>

            <span>
              {charts.length} {charts.length === 1 ? "CHART" : "CHARTS"}
            </span>
          </div>

          <div className="research-visualizations-grid">
            {charts.map((chart) => (
              <ResearchChart key={chart.id} chart={chart} />
            ))}
          </div>
        </>
      )}

      {warnings.length > 0 && (
        <div className="research-visualization-warnings" role="status">
          <strong>Visualization notes</strong>

          <ul>
            {warnings.map((warning, index) => (
              <li key={`${index}-${warning}`}>{warning}</li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}