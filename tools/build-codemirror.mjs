import { build } from "esbuild";

await build({
  entryPoints: ["codemirror-json-editor.entry.js"],
  bundle: true,
  format: "iife",
  globalName: "VortexCodeMirror",
  minify: true,
  target: ["es2020"],
  outfile: "../static/vendor/codemirror-json-editor.js",
  legalComments: "inline",
});
