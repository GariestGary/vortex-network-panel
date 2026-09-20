# Local CodeMirror 6 bundle

`codemirror-json-editor.js` is a prebuilt, browser-ready CodeMirror 6 JSON editor bundle, served only from `/static/vendor/` in production.

- Source: https://github.com/paul-norman/codemirror6-prebuilt
- Upstream CodeMirror packages: MIT licensed
- Bundle: `dist/json.min.js`, downloaded during development and committed to this repository.

No production runtime fetches or Node/npm installation are required. To update it, use a development machine with Node/npm to rebuild an equivalent JSON bundle, or replace this file with a verified prebuilt bundle from the source project.
