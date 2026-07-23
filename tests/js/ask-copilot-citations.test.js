/**
 * @jest-environment jsdom
 */

/**
 * Tests for interface/ask_copilot/assets/ask_copilot.js — citation Source
 * controls, in-pane popup, URL allowlist, and clinical+citation SSE buffering
 * (PRD 06 Wave 1 S3).
 *
 * Run with: npm run test:js -- tests/js/ask-copilot-citations.test.js
 *
 * @package   OpenEMR
 * @link      https://www.open-emr.org
 * @license   https://github.com/openemr/openemr/blob/master/LICENSE GNU General Public License 3
 */

const fs = require('fs');
const path = require('path');
const { TextEncoder, TextDecoder } = require('util');
const { ReadableStream } = require('stream/web');

// jsdom does not provide these Web APIs; the SSE client needs them.
global.TextEncoder = TextEncoder;
global.TextDecoder = TextDecoder;
global.ReadableStream = ReadableStream;

const src = fs.readFileSync(
    path.resolve(__dirname, '../../interface/ask_copilot/assets/ask_copilot.js'),
    'utf8'
);

// Mirrors the markup rendered by interface/ask_copilot/index.php.
const FIXTURE_HTML = `
<div class="container-fluid ask-copilot" id="ask-copilot-app">
    <header class="ask-copilot-header">
        <div class="ask-copilot-header-row">
            <h2 class="ask-copilot-title">Ask Co-Pilot</h2>
            <button type="button" id="acp-change-patient" class="btn btn-link btn-sm d-none">Change patient</button>
        </div>
        <div id="acp-patient-line" aria-live="polite"></div>
    </header>
    <div id="acp-messages" aria-live="polite"></div>
    <div id="acp-progress" aria-live="polite"></div>
    <div class="ask-copilot-composer">
        <textarea id="acp-input"></textarea>
        <button type="button" id="acp-send" disabled>Send</button>
    </div>
</div>
<div id="acp-picker-backdrop" class="ask-copilot-picker-backdrop d-none"></div>
<div id="acp-picker" class="ask-copilot-picker d-none" role="dialog" aria-modal="true"
     aria-labelledby="acp-picker-title" tabindex="-1">
    <h3 id="acp-picker-title">Select a patient</h3>
    <div id="acp-picker-status" aria-live="polite"></div>
    <div id="acp-picker-next"></div>
    <div id="acp-picker-list"></div>
    <div class="ask-copilot-picker-footer">
        <button type="button" id="acp-picker-search">Search all patients</button>
        <button type="button" id="acp-picker-cancel" class="d-none">Cancel</button>
    </div>
</div>
<div id="acp-cite-backdrop" class="ask-copilot-cite-backdrop d-none"></div>
<div id="acp-cite" class="ask-copilot-cite d-none" role="dialog" aria-modal="true"
     aria-labelledby="acp-cite-title" tabindex="-1">
    <h3 id="acp-cite-title">Source</h3>
    <div id="acp-cite-body"></div>
    <div class="ask-copilot-cite-footer">
        <a id="acp-cite-open" class="btn btn-link btn-sm d-none" target="_blank" rel="noopener noreferrer">Open label</a>
        <button type="button" id="acp-cite-close" class="btn btn-secondary btn-sm">Close</button>
    </div>
</div>`;

let sessionPid = null;

function jsonResponse(data, ok = true, status = 200) {
    return { ok, status, json: async () => data };
}

/**
 * Build a fetch Response-like object whose body is an SSE ReadableStream.
 *
 * @param {Array<{event: string, data: object}>} frames
 * @returns {{ok: boolean, status: number, body: ReadableStream}}
 */
function sseResponse(frames) {
    const text = frames
        .map(function (f) {
            return 'event: ' + f.event + '\ndata: ' + JSON.stringify(f.data) + '\n\n';
        })
        .join('');
    const stream = new ReadableStream({
        start(controller) {
            controller.enqueue(new TextEncoder().encode(text));
            controller.close();
        }
    });
    return { ok: true, status: 200, body: stream };
}

/**
 * SSE body that emits clinical, then waits (caller advances timers / closes).
 * Used for clinical-only timeout buffering tests.
 *
 * @param {{text: string, segments?: Array<object>}} clinical
 * @returns {{ok: boolean, status: number, body: ReadableStream, emitDone: Function}}
 */
function sseResponseClinicalThenHang(clinical) {
    let controllerRef = null;
    const stream = new ReadableStream({
        start(controller) {
            controllerRef = controller;
            const frame =
                'event: clinical\ndata: ' + JSON.stringify(clinical) + '\n\n';
            controller.enqueue(new TextEncoder().encode(frame));
        }
    });
    return {
        ok: true,
        status: 200,
        body: stream,
        emitDone: function (correlationId) {
            if (!controllerRef) {
                return;
            }
            const frame =
                'event: done\ndata: ' +
                JSON.stringify({ correlation_id: correlationId || 'x' }) +
                '\n\n';
            controllerRef.enqueue(new TextEncoder().encode(frame));
            controllerRef.close();
        },
        close: function () {
            if (controllerRef) {
                controllerRef.close();
            }
        }
    };
}

function loadApp(configOverrides = {}) {
    document.body.innerHTML = FIXTURE_HTML;
    window.askCopilotConfig = Object.assign(
        {
            webroot: '/openemr',
            csrf: 'test-csrf',
            streamUrl: '/openemr/interface/ask_copilot/stream.php',
            scheduleUrl: '/openemr/interface/ask_copilot/schedule.php',
            sessionPid: null,
            pickerPollIntervalMs: 100,
            pickerPollTimeoutMs: 1000,
            citationTimeoutMs: 2500,
            strings: {
                sourceLabel: 'Source',
                openLabel: 'Open label',
                citeClose: 'Close'
            }
        },
        configOverrides
    );
    // eslint-disable-next-line no-new-func
    new Function('window', src)(window);
    return window.AskCopilot;
}

function el(id) {
    return document.getElementById(id);
}

function citeVisible() {
    return !el('acp-cite').classList.contains('d-none');
}

async function flush() {
    for (let i = 0; i < 10; i++) {
        await jest.advanceTimersByTimeAsync(0);
    }
}

function pressEscape() {
    document.dispatchEvent(
        new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true })
    );
}

const SAMPLE_SEGMENTS = [
    { kind: 'claim', text: 'LDL 142 mg/dL', citation_id: 'c1' },
    { kind: 'claim', text: 'On simvastatin 20 mg', citation_id: 'c2' },
    { kind: 'assembly', text: 'Not medical advice.' }
];

const SAMPLE_CITATIONS = [
    {
        citation_id: 'c1',
        source_type: 'chart',
        title: 'Lab result',
        excerpt: 'LDL 142 mg/dL',
        locator: { table: 'procedure_result', id: '42', url: null }
    },
    {
        citation_id: 'c2',
        source_type: 'research',
        title: 'Simvastatin label',
        excerpt: 'Simvastatin — https://dailymed.nlm.nih.gov/dailymed/drugInfo.cfm?setid=abc',
        locator: {
            table: 'dailymed',
            id: 'abc',
            url: 'https://dailymed.nlm.nih.gov/dailymed/drugInfo.cfm?setid=abc'
        }
    }
];

beforeEach(() => {
    jest.useFakeTimers();
    sessionPid = 5;
    window.getSessionValue = jest.fn(async () => sessionPid);
    window.restoreSession = jest.fn();
    window.navigateTab = jest.fn((url, name, cb) => {
        if (typeof cb === 'function') {
            cb();
        }
    });
    window.activateTabByName = jest.fn();
    window.webroot_url = '/openemr';
    window.RTop = {};
    window.confirm = jest.fn(() => true);
    window.fetch = jest.fn().mockResolvedValue(jsonResponse({
        date: '2026-07-21',
        timezone: 'America/Chicago',
        next_pid: null,
        appointments: []
    }));
});

afterEach(() => {
    jest.clearAllTimers();
    jest.useRealTimers();
    delete window.AskCopilot;
    delete window.askCopilotConfig;
    delete window.RTop;
});

// ---------------------------------------------------------------------------
// URL allowlist
// ---------------------------------------------------------------------------
describe('isAllowlistedHttpsUrl', () => {

    test('accepts DailyMed and openFDA https hosts (incl. www)', () => {
        const app = loadApp();
        expect(
            app.isAllowlistedHttpsUrl(
                'https://dailymed.nlm.nih.gov/dailymed/drugInfo.cfm?setid=abc'
            )
        ).toBe(true);
        expect(
            app.isAllowlistedHttpsUrl('https://www.dailymed.nlm.nih.gov/x')
        ).toBe(true);
        expect(app.isAllowlistedHttpsUrl('https://api.fda.gov/drug/label.json')).toBe(true);
        expect(app.isAllowlistedHttpsUrl('https://www.api.fda.gov/drug/label.json')).toBe(true);
    });

    test('rejects javascript:, http:, and non-allowlisted hosts', () => {
        const app = loadApp();
        expect(app.isAllowlistedHttpsUrl('javascript:alert(1)')).toBe(false);
        expect(app.isAllowlistedHttpsUrl('http://dailymed.nlm.nih.gov/x')).toBe(false);
        expect(app.isAllowlistedHttpsUrl('https://evil.example/phish')).toBe(false);
        expect(app.isAllowlistedHttpsUrl('https://dailymed.nlm.nih.gov.evil.com/x')).toBe(false);
        expect(app.isAllowlistedHttpsUrl('')).toBe(false);
        expect(app.isAllowlistedHttpsUrl(null)).toBe(false);
    });
});

// ---------------------------------------------------------------------------
// renderAssistantTurn — Source only on claim segments
// ---------------------------------------------------------------------------
describe('renderAssistantTurn', () => {

    test('creates Source controls only for claim segments with known citations', async () => {
        const app = loadApp();
        await flush();

        const map = {};
        SAMPLE_CITATIONS.forEach(function (c) {
            map[c.citation_id] = c;
        });
        app.renderAssistantTurn(SAMPLE_SEGMENTS, map);

        const sources = el('acp-messages').querySelectorAll('.ask-copilot-source');
        expect(sources).toHaveLength(2);
        expect(sources[0].getAttribute('data-cite-id')).toBe('c1');
        expect(sources[1].getAttribute('data-cite-id')).toBe('c2');
        expect(sources[0].className).toContain('btn-link');
        expect(sources[0].textContent).toBe('Source');

        const segments = el('acp-messages').querySelectorAll('.ask-copilot-segment');
        expect(segments).toHaveLength(3);
        expect(segments[2].querySelector('.ask-copilot-source')).toBeNull();
        expect(segments[2].textContent).toContain('Not medical advice.');
    });

    test('does not render Source for orphan citation_id', async () => {
        const app = loadApp();
        await flush();

        app.renderAssistantTurn(
            [{ kind: 'claim', text: 'Orphan claim', citation_id: 'c99' }],
            { c1: SAMPLE_CITATIONS[0] }
        );

        expect(el('acp-messages').querySelector('.ask-copilot-source')).toBeNull();
        expect(el('acp-messages').textContent).toContain('Orphan claim');
    });

    test('renders claim text via textContent only (XSS-safe)', async () => {
        const app = loadApp();
        await flush();
        window.xssFired = undefined;

        const evil = '<img src=x onerror="window.xssFired=true">';
        app.renderAssistantTurn(
            [{ kind: 'claim', text: evil, citation_id: 'c1' }],
            {
                c1: {
                    citation_id: 'c1',
                    source_type: 'chart',
                    title: evil,
                    excerpt: evil,
                    locator: { table: 't', id: '1', url: null }
                }
            }
        );

        expect(el('acp-messages').querySelector('img')).toBeNull();
        expect(window.xssFired).toBeUndefined();
        expect(el('acp-messages').textContent).toContain(evil);
    });
});

// ---------------------------------------------------------------------------
// Citation dialog
// ---------------------------------------------------------------------------
describe('citation dialog', () => {

    test('Source click fills dialog via textContent and shows Open label when allowlisted', async () => {
        const app = loadApp();
        await flush();

        const map = { c2: SAMPLE_CITATIONS[1] };
        app.renderAssistantTurn(
            [{ kind: 'claim', text: 'Dose text', citation_id: 'c2' }],
            map
        );

        const sourceBtn = el('acp-messages').querySelector('.ask-copilot-source');
        sourceBtn.focus();
        sourceBtn.click();

        expect(citeVisible()).toBe(true);
        const body = el('acp-cite-body');
        expect(body.textContent).toContain('research');
        expect(body.textContent).toContain('Simvastatin label');
        expect(body.textContent).toContain('Simvastatin —');
        expect(body.querySelector('img')).toBeNull();

        const openLink = el('acp-cite-open');
        expect(openLink.classList.contains('d-none')).toBe(false);
        expect(openLink.getAttribute('href')).toBe(SAMPLE_CITATIONS[1].locator.url);
        expect(openLink.getAttribute('target')).toBe('_blank');
        expect(openLink.getAttribute('rel')).toContain('noopener');
        expect(openLink.getAttribute('rel')).toContain('noreferrer');
    });

    test('hides Open label for non-allowlisted or missing URL', async () => {
        const app = loadApp();
        await flush();

        app.openCitation({
            citation_id: 'c1',
            source_type: 'chart',
            title: 'Lab',
            excerpt: 'LDL 142',
            retrieved_at: '2026-07-22T12:00:00Z',
            locator: {
                table: 'procedure_result',
                id: '42',
                url: 'https://evil.example/x',
                fhir_uuid: 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee',
            }
        });

        expect(citeVisible()).toBe(true);
        expect(el('acp-cite-open').classList.contains('d-none')).toBe(true);
        expect(el('acp-cite-body').textContent).toContain('chart');
        expect(el('acp-cite-body').textContent).toContain('procedure_result');
        expect(el('acp-cite-body').textContent).toContain('42');
        expect(el('acp-cite-body').textContent).toContain('2026-07-22T12:00:00Z');
        expect(el('acp-cite-body').textContent).toContain(
            'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'
        );
    });

    test('Escape and Close restore focus to the Source button', async () => {
        const app = loadApp();
        await flush();

        const map = { c1: SAMPLE_CITATIONS[0] };
        app.renderAssistantTurn(
            [{ kind: 'claim', text: 'LDL', citation_id: 'c1' }],
            map
        );
        const sourceBtn = el('acp-messages').querySelector('.ask-copilot-source');
        sourceBtn.focus();
        sourceBtn.click();
        expect(citeVisible()).toBe(true);

        pressEscape();
        expect(citeVisible()).toBe(false);
        expect(document.activeElement).toBe(sourceBtn);

        sourceBtn.click();
        expect(citeVisible()).toBe(true);
        el('acp-cite-close').click();
        expect(citeVisible()).toBe(false);
        expect(document.activeElement).toBe(sourceBtn);
    });
});

// ---------------------------------------------------------------------------
// SSE buffering: clinical + citation
// ---------------------------------------------------------------------------
describe('SSE clinical+citation buffering', () => {

    async function sendWithSse(framesOrResponse) {
        const app = loadApp({ citationTimeoutMs: 2500 });
        await flush();

        window.fetch = jest.fn().mockImplementation(function (url) {
            if (String(url).indexOf('stream.php') !== -1) {
                return Promise.resolve(
                    Array.isArray(framesOrResponse)
                        ? sseResponse(framesOrResponse)
                        : framesOrResponse
                );
            }
            return Promise.resolve(jsonResponse({
                date: '2026-07-21',
                timezone: 'America/Chicago',
                next_pid: null,
                appointments: []
            }));
        });

        el('acp-input').value = 'summarize';
        await app.sendMessage();
        await flush();
        return app;
    }

    test('clinical + citation renders linked Source controls', async () => {
        await sendWithSse([
            { event: 'progress', data: { message: 'Pulling labs…' } },
            {
                event: 'clinical',
                data: {
                    text: 'LDL 142 mg/dL\nOn simvastatin 20 mg\nNot medical advice.',
                    segments: SAMPLE_SEGMENTS
                }
            },
            { event: 'citation', data: { citations: SAMPLE_CITATIONS } },
            { event: 'done', data: { correlation_id: 'corr-1' } }
        ]);

        const sources = el('acp-messages').querySelectorAll('.ask-copilot-source');
        expect(sources).toHaveLength(2);
        expect(el('acp-messages').textContent).toContain('LDL 142 mg/dL');
        expect(window.AskCopilot.getState().transcriptLength).toBe(2);
    });

    test('clinical-only then timeout renders plain text without Source', async () => {
        const hung = sseResponseClinicalThenHang({
            text: 'Plain clinical fallback',
            segments: SAMPLE_SEGMENTS
        });
        const app = loadApp({ citationTimeoutMs: 2500 });
        await flush();

        window.fetch = jest.fn().mockImplementation(function (url) {
            if (String(url).indexOf('stream.php') !== -1) {
                return Promise.resolve(hung);
            }
            return Promise.resolve(jsonResponse({
                date: '2026-07-21',
                timezone: 'America/Chicago',
                next_pid: null,
                appointments: []
            }));
        });

        el('acp-input').value = 'summarize';
        const sendPromise = app.sendMessage();
        await flush();

        // Still buffering — no assistant bubble yet.
        expect(el('acp-messages').querySelector('.ask-copilot-bubble-assistant')).toBeNull();

        await jest.advanceTimersByTimeAsync(2500);
        await flush();

        const assistant = el('acp-messages').querySelector('.ask-copilot-bubble-assistant');
        expect(assistant).not.toBeNull();
        expect(assistant.textContent).toBe('Plain clinical fallback');
        expect(assistant.querySelector('.ask-copilot-source')).toBeNull();

        hung.emitDone('corr-timeout');
        await sendPromise;
        await flush();

        // Still a single plain assistant bubble (no double-render).
        expect(el('acp-messages').querySelectorAll('.ask-copilot-bubble-assistant')).toHaveLength(1);
    });

    test('transcript stores plain text only (no citation markup)', async () => {
        const app = await sendWithSse([
            {
                event: 'clinical',
                data: {
                    text: 'LDL 142 mg/dL\nNot medical advice.',
                    segments: [
                        { kind: 'claim', text: 'LDL 142 mg/dL', citation_id: 'c1' },
                        { kind: 'assembly', text: 'Not medical advice.' }
                    ]
                }
            },
            { event: 'citation', data: { citations: [SAMPLE_CITATIONS[0]] } },
            { event: 'done', data: { correlation_id: 'corr-2' } }
        ]);

        const state = app.getState();
        expect(state.transcriptLength).toBe(2);
        // Resend payload must remain role/text — verify via a second send's fetch body.
        window.fetch = jest.fn().mockResolvedValue(
            sseResponse([{ event: 'done', data: { correlation_id: 'x' } }])
        );
        el('acp-input').value = 'follow-up';
        await app.sendMessage();
        await flush();

        const streamCall = window.fetch.mock.calls.find(function (c) {
            return String(c[0]).indexOf('stream.php') !== -1;
        });
        expect(streamCall).toBeTruthy();
        const body = new URLSearchParams(streamCall[1].body);
        const transcript = JSON.parse(body.get('transcript'));
        expect(transcript[0]).toEqual({ role: 'user', text: 'summarize' });
        expect(transcript[1]).toEqual({
            role: 'assistant',
            text: 'LDL 142 mg/dL\nNot medical advice.'
        });
        expect(JSON.stringify(transcript)).not.toContain('citation_id');
        expect(JSON.stringify(transcript)).not.toContain('Source');
    });
});
