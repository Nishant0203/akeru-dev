# AkeruRenderer

Shared client bundle for Akeru agent UIs: SSE streaming, Markdown (via [marked](https://github.com/markedjs/marked)), and optional post-processors (GitHub file links, copy buttons, section highlights).

## Host integration

1. Load **marked** (e.g. from cdnjs), then `akeru-renderer.js`.
2. Load `akeru-renderer.css`.
3. Call `AkeruRenderer.init({ agent, githubBase, postProcessors, theme })`.
4. Use `AkeruRenderer.createMessage(container, role)` and `appendToken` / `finalize` for streamed assistant replies.

See `vidhi/index.html` for a full example.

## Paths

From site root (e.g. GitHub Pages): `/shared/renderer/akeru-renderer.css` and `.js`.
