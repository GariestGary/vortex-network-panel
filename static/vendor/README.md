# Local CodeMirror 6 bundle

`codemirror-json-editor.js` is a prebuilt, browser-ready CodeMirror 6 JSON editor bundle, served only from `/static/vendor/` in production.

- Source: https://github.com/paul-norman/codemirror6-prebuilt
- Upstream CodeMirror packages: MIT licensed
- Bundle: `dist/json.min.js`, downloaded during development and committed to this repository.

No production runtime fetches or Node/npm installation are required. To update it, use a development machine with Node/npm to rebuild an equivalent JSON bundle, or replace this file with a verified prebuilt bundle from the source project.

To rebuild on a development machine only: cd tools && npm install && npm run build:codemirror. The committed bundle is what production serves.

## Local loading animation

lottie-light.min.js is the SVG-only Lottie Web 5.12.2 player (MIT), bundled locally from the npm package. loading-spinner.json is a small in-repository single-colour 1-second looping Lottie spinner. Both are served from /static/vendor/; production makes no CDN/runtime request and does not need Node/npm.
