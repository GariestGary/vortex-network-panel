import { basicSetup } from "codemirror";
import { indentWithTab } from "@codemirror/commands";
import { json } from "@codemirror/lang-json";
import { indentUnit } from "@codemirror/language";
import { EditorState } from "@codemirror/state";
import { EditorView, highlightActiveLine, highlightActiveLineGutter, keymap } from "@codemirror/view";
import { oneDark } from "@codemirror/theme-one-dark";

export function create(textarea) {
  const host = document.createElement("div");
  host.className = "codemirror";
  textarea.parentNode.insertBefore(host, textarea);
  textarea.hidden = true;
  let view;
  const state = EditorState.create({
    doc: textarea.value,
    extensions: [
      basicSetup,
      json(),
      oneDark,
      indentUnit.of("  "),
      keymap.of([indentWithTab]),
      highlightActiveLine(),
      highlightActiveLineGutter(),
      EditorView.lineWrapping,
      EditorView.updateListener.of((update) => {
        if (update.docChanged) textarea.value = update.state.doc.toString();
      }),
    ],
  });
  view = new EditorView({ state, parent: host });
  return {
    getValue: () => view.state.doc.toString(),
    setValue: (value) => view.dispatch({ changes: { from: 0, to: view.state.doc.length, insert: value } }),
    focus: () => view.focus(),
    requestMeasure: () => view.requestMeasure(),
    get dom() { return view.dom; },
  };
}
