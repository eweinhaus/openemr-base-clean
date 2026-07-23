# Clinical Co-Pilot — API collection (Bruno)

Importable Bruno collection for graders and operators. Covers the **hybrid** surface:

1. **Browser → OpenEMR gateway** (session cookie + CSRF)
2. **Sidecar → OpenEMR internal** (`X-Copilot-Internal-Secret`, RFC1918/loopback only)
3. **OpenEMR gateway → LangGraph sidecar** (`X-Copilot-Internal-Secret`, SSE)

## Import

Open [Bruno](https://www.usebruno.com/) → **Open Collection** → select `docs/api/bruno/` (folder with `bruno.json`).

Environments:

| Env | OpenEMR base | Sidecar base |
| --- | --- | --- |
| `local` | `http://localhost:8300` | `http://127.0.0.1:8080` (standalone) or compose service DNS |
| `public-do` | `https://142.93.255.212` | **not public** — SSH / docker-network only |

Compose stacks typically **do not publish** the sidecar on a host port. Local Bruno against `/v1/chat` needs either a published port, `docker compose port`, or curl from inside the network. Graders exercising the physician path should use **gateway** `stream.php`, not the sidecar directly.

## Auth by surface

### Gateway (browser session + CSRF)

| Endpoint | Method | Auth |
| --- | --- | --- |
| `/interface/ask_copilot/stream.php` | POST (SSE) | OpenEMR session cookie + `csrf_token_form` in body |
| `/interface/ask_copilot/schedule.php` | GET (JSON) | OpenEMR session cookie + `csrf_token_form` query param |

- Obtain CSRF from a logged-in Ask Co-Pilot page (`config.csrf` in the UI) or an authenticated form token.
- Session cookie: log in at the base URL (`admin` / `pass` on demo), then copy `OpenEMR` / PHP session cookies into Bruno.
- Client-supplied `pid` is **ignored** for binding; the gateway binds from session only.

### Internal (service secret)

| Endpoint | Method | Auth |
| --- | --- | --- |
| `/interface/ask_copilot/tool_proxy.php` | POST (JSON) | Header `X-Copilot-Internal-Secret` + valid correlation bind; source IP must be loopback/RFC1918 (or escape env) |
| `/interface/ask_copilot/disclosure.php` | POST (JSON) | Same secret + bind |

Wrong secret → **401** `{ "ok": false, "error": "unauthorized" }`. Public `REMOTE_ADDR` → **403** `forbidden`.

### Sidecar

| Endpoint | Method | Auth |
| --- | --- | --- |
| `/health` | GET | none |
| `/ready` | GET | none — **HTTP 503** when `ready: false` (body still includes soft fields) |
| `/v1/chat` | POST (SSE) | Header `X-Copilot-Internal-Secret` |

Wrong/missing secret on `/v1/chat` → **401** `{ "error": "unauthorized" }`.

## Base URLs (quick reference)

| Target | URL |
| --- | --- |
| Local OpenEMR | http://localhost:8300/ |
| Public DO demo | https://142.93.255.212/ |
| Sidecar (local standalone example) | http://127.0.0.1:8080 |
| Sidecar (compose) | `http://copilot-sidecar:8080` on the Docker network |

Demo login: `admin` / `pass`. Self-signed HTTPS on the DO IP may warn in browsers/Bruno — expect to continue / disable TLS verify for smoke only.
