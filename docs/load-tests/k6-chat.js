/**
 * Clinical Co-Pilot — k6 load script (sidecar /v1/chat SSE)
 *
 * Env:
 *   BASE_URL  - sidecar origin, e.g. http://127.0.0.1:8080
 *   SECRET    - X-Copilot-Internal-Secret
 *   VUS       - concurrent virtual users (default 10; use 50 for stress)
 *   DURATION  - optional; default 30s
 *   PID       - patient id in JSON body (default 6)
 *
 * Expect single-worker saturation on the 2 GB MVP host — that is a valid result.
 *
 *   BASE_URL=http://127.0.0.1:8080 SECRET=dev-secret-change-me VUS=10 \
 *     k6 run docs/load-tests/k6-chat.js
 */

import http from 'k6/http';
import { check, sleep } from 'k6';
import { Rate, Trend } from 'k6/metrics';

const BASE_URL = __ENV.BASE_URL || 'http://127.0.0.1:8080';
const SECRET = __ENV.SECRET || '';
const VUS = Number(__ENV.VUS || 10);
const DURATION = __ENV.DURATION || '30s';
const PID = Number(__ENV.PID || 6);

const sseErrors = new Rate('copilot_sse_error_frames');
const chatDuration = new Trend('copilot_chat_duration_ms', true);

export const options = {
  scenarios: {
    concurrent_chat: {
      executor: 'constant-vus',
      vus: VUS,
      duration: DURATION,
    },
  },
  thresholds: {
    // Soft thresholds — do not pretend the single worker will hold p95 under 50 VUs.
    http_req_failed: ['rate<0.5'],
  },
};

function correlationId() {
  return `k6-${__VU}-${__ITER}-${Date.now()}`;
}

export default function () {
  if (!SECRET) {
    throw new Error('Set SECRET to COPILOT_INTERNAL_SECRET');
  }

  const corr = correlationId();
  const url = `${BASE_URL.replace(/\/$/, '')}/v1/chat`;
  const payload = JSON.stringify({
    correlation_id: corr,
    user_id: 1,
    username: 'k6-load',
    pid: PID,
    message: 'Show recent labs',
    transcript: [],
  });

  const res = http.post(url, payload, {
    headers: {
      'Content-Type': 'application/json',
      Accept: 'text/event-stream',
      'X-Copilot-Internal-Secret': SECRET,
      'X-Correlation-Id': corr,
    },
    timeout: '120s',
  });

  chatDuration.add(res.timings.duration);

  const okStatus = check(res, {
    'status is 200 or 401': (r) => r.status === 200 || r.status === 401,
    'not 5xx': (r) => r.status < 500,
  });

  // Auth misconfig should fail closed (401), not look like clinical success.
  if (res.status === 401) {
    check(res, {
      'unauthorized body': (r) => String(r.body).includes('unauthorized'),
    });
    sleep(1);
    return;
  }

  const body = String(res.body || '');
  const sawErrorFrame = /event:\s*error/.test(body);
  sseErrors.add(sawErrorFrame ? 1 : 0);

  check(res, {
    'request completed': () => okStatus,
    'has SSE event framing or empty on early close': () =>
      body.length === 0 || body.includes('event:') || body.includes('data:'),
  });

  sleep(1);
}
