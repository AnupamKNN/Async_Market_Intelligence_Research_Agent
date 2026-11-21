import createPlotlyComponent from "react-plotly.js/factory";

import * as Plotly from "plotly.js/lib/core";
import * as scatter from "plotly.js/lib/scatter";
import * as bar from "plotly.js/lib/bar";

// Register only the chart types used by the application.
Plotly.register([scatter, bar]);

const Plot = createPlotlyComponent(Plotly);

export default Plot;