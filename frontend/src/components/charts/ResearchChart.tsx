import { lazy, Suspense, useMemo } from "react";
import type { PlotParams } from "react-plotly.js";

import type { ResearchChart as ResearchChartSpec } from "../../services/research";
import "./ResearchChart.css";

// Plotly is loaded only when a chart is rendered.
const Plot = lazy(() => import("./PlotlyRenderer"));

const SERIES_COLORS = [
  "#4F46E5",
  "#0D9488",
  "#E59A35",
  "#D66A85",
  "#4385C5",
];

const TOP_PRODUCT_COLORS = [
  "#4F46E5",
  "#0D9488",
  "#E59A35",
  "#D66A85",
  "#4385C5",
  "#7C5AC7",
  "#299D8F",
  "#C47745",
  "#477DB5",
  "#A65D91",
];

const SEASONALITY_COLORS = [
  "#4F46E5",
  "#0D9488",
  "#E59A35",
  "#D66A85",
  "#4385C5",
  "#8B6CC7",
  "#299D8F",
  "#CB8450",
  "#5276B8",
  "#B45E82",
  "#6C9B65",
  "#A18BCA",
];

function getBarColors(
  chartId: string,
  series: ResearchChartSpec["series"][number],
  fallbackColor: string,
): string | string[] {
  switch (chartId) {
    case "top-products":
      return series.data.map(
        (_, index) =>
          TOP_PRODUCT_COLORS[
            index % TOP_PRODUCT_COLORS.length
          ],
      );

    case "sales-seasonality":
      return series.data.map(
        (_, index) =>
          SEASONALITY_COLORS[
            index % SEASONALITY_COLORS.length
          ],
      );

    case "monthly-sales-anomalies":
      return series.data.map((point) => {
        if (point.metadata.direction === "high") {
          return "#E05252";
        }

        if (point.metadata.direction === "low") {
          return "#4385C5";
        }

        return "#9295A5";
      });

    default:
      return fallbackColor;
  }
}

function escapePlotlyText(value: string): string {
  return value
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function formatMetadataLabel(value: string): string {
  return escapePlotlyText(
    value
      .replace(/_/g, " ")
      .replace(/([a-z])([A-Z])/g, "$1 $2"),
  );
}

interface ResearchChartProps {
  chart: ResearchChartSpec;
}

export default function ResearchChart({
  chart,
}: ResearchChartProps) {
  const isHorizontalBar = chart.chart_type === "bar";

  const hasValues = chart.series.some((series) =>
    series.data.some((point) => point.y !== null),
  );

  const plotData = useMemo<PlotParams["data"]>(() => {
    const traces: PlotParams["data"] = [];

    chart.series.forEach((series, seriesIndex) => {
      const renderAs = series.render_as ?? chart.chart_type;
      const color = SERIES_COLORS[seriesIndex % SERIES_COLORS.length];

      const metadataKeys = Array.from(
        new Set(
          series.data.flatMap((point) =>
            Object.keys(point.metadata),
          ),
        ),
      );

      const customdata = series.data.map((point) =>
        metadataKeys.map((key) => {
          const value = point.metadata[key] ?? "—";

          return typeof value === "string"
            ? escapePlotlyText(value)
            : value;
        }),
      );

      const metadataHoverTemplate = metadataKeys
        .map(
          (key, index) =>
            `<br>${formatMetadataLabel(key)}: %{customdata[${index}]}`,
        )
        .join("");

      const hovertemplate = isHorizontalBar
        ? `%{y}<br><b>%{fullData.name}</b>: %{x}${metadataHoverTemplate}<extra></extra>`
        : `%{x}<br><b>%{fullData.name}</b>: %{y}${metadataHoverTemplate}<extra></extra>`;

      if (renderAs === "bar") {
        traces.push({
          type: "bar",
          orientation: "h",
          name: series.name,
          x: series.data.map((point) => point.y),
          y: series.data.map((point) => point.x),
          customdata,
          marker: {
            color: getBarColors(chart.id, series, color),
            line: {
              color: "rgba(255,255,255,0.85)",
              width: 1,
            },
          },
          hovertemplate,
        });
        return;
      }

      traces.push({
        type: "scatter",
        mode: renderAs === "scatter" ? "markers" : "lines+markers",
        name: series.name,
        x: series.data.map((point) => point.x),
        y: series.data.map((point) => point.y),
        customdata,
        connectgaps: false,
        line: {
          color,
          width: 2.5,
          shape: "linear",
        },
        marker: {
          color,
          size: 7,
        },
        hovertemplate,
      });
    });

    return traces;
  }, [chart, isHorizontalBar]);

  const layout = useMemo<NonNullable<PlotParams["layout"]>>(
    () => ({
      autosize: true,
      height: 360,
      margin: {
        l: isHorizontalBar ? 175 : 62,
        r: 24,
        t: 20,
        b: isHorizontalBar ? 55 : 75,
      },
      paper_bgcolor: "rgba(0,0,0,0)",
      plot_bgcolor: "rgba(0,0,0,0)",
      font: {
        family: "Inter, sans-serif",
        size: 10,
        color: "#625d70",
      },
      showlegend: chart.series.length > 1,
      legend: {
        orientation: "h",
        x: 0,
        y: -0.25,
        font: { size: 10 },
      },
      hovermode: "closest",
      bargap: 0.3,
      barmode: "group",
      xaxis: {
        title: {
          text: isHorizontalBar
            ? chart.y_axis_title
            : chart.x_axis_title,
        },
        automargin: true,
        gridcolor: isHorizontalBar ? "#ece9f2" : "rgba(0,0,0,0)",
        zerolinecolor: "#ded9e9",
        tickfont: { size: 10 },
      },
      yaxis: {
        title: {
          text: isHorizontalBar
            ? chart.x_axis_title
            : chart.y_axis_title,
        },
        automargin: true,
        autorange: isHorizontalBar ? "reversed" : undefined,
        gridcolor: isHorizontalBar ? "rgba(0,0,0,0)" : "#ece9f2",
        zerolinecolor: "#ded9e9",
        tickfont: { size: 10 },
      },
    }),
    [chart, isHorizontalBar],
  );

  const config = useMemo<NonNullable<PlotParams["config"]>>(
    () => ({
      responsive: true,
      displaylogo: false,
      displayModeBar: "hover",
      scrollZoom: false,
      toImageButtonOptions: {
        format: "png",
        filename: `research-chart-${chart.id}`,
        scale: 2,
      },
    }),
    [chart.id],
  );

  return (
    <article className="research-chart-card">
      <div className="research-chart-heading">
        <div>
          <h3>{chart.title}</h3>
          {chart.description && <p>{chart.description}</p>}
        </div>
      </div>

      {!hasValues ? (
        <div className="research-chart-empty" role="status">
          No plottable data points are available for this chart.
        </div>
      ) : (
        <div className="research-chart-plot">
          <Suspense
            fallback={
              <div className="research-chart-loading" role="status">
                Loading interactive chart...
              </div>
            }
          >
            <Plot
              data={plotData}
              layout={layout}
              config={config}
              useResizeHandler
              style={{
                width: "100%",
                height: "100%",
              }}
            />
          </Suspense>
        </div>
      )}
    </article>
  );
}