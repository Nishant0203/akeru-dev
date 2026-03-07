# akeru.dev frontend – Vanik chat

Single-page Vanik chat for akeru.dev. Star icon opens the panel; session is created with `POST /sessions` (201 Created), then SSE is opened to stream events.

## Setup

- Set **`window.VANIK_API_URL`** to the session gateway base URL (e.g. `https://api.akeru.dev` or `http://localhost:8000`) before loading the app, or leave unset to use same-origin.
- Deploy the contents of `web/` to your static host (e.g. akeru.dev root or a path).

## Behaviour

- **Star click** → `POST /sessions` → open **EventSource** to `/sessions/{id}/sse`.
- **Token** events → append to streaming text.
- **Thinking** `visible: true` → show “Thinking…” indicator; `visible: false` → hide it.
- **Gate** event → render option cards; click sends selection as next message.
- **Done** event → close SSE consumption for that turn, show input bar.
- **Error / clarify** → show message banner, show input.

## CORS

The session gateway must allow the frontend origin (e.g. `https://akeru.dev`) and expose CORS for GET (SSE) and POST.
