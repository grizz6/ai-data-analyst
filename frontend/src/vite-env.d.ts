/// <reference types="vite/client" />

// The prebuilt Plotly bundles ship without type definitions of their own;
// they expose the same API as plotly.js.
declare module "plotly.js-cartesian-dist-min" {
  import Plotly from "plotly.js";
  export default Plotly;
}
