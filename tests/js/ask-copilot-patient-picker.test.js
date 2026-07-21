/**
 * @jest-environment jsdom
 */

/**
 * Tests for interface/ask_copilot/assets/ask_copilot.js — blocking patient
 * picker popup (Wave 1 P2).
 *
 * Run with: npm run test:js -- tests/js/ask-copilot-patient-picker.test.js
 *
 * @package   OpenEMR
 * @link      https://www.open-emr.org
 * @license   https://github.com/openemr/openemr/blob/master/LICENSE GNU General Public License 3
 */

const fs = require('fs');
const path = require('path');

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
</div>`;

const SCHEDULE = {
    date: '2026-07-21',
    timezone: 'America/Chicago',
    next_pid: 6,
    appointments: [
        {
            pid: 6,
            name: 'Jane Doe',
            dob: '1980-04-12',
            start_time: '14:30',
            title: 'Office Visit',
            status: 'Pending'
        },
        {
            pid: 7,
            name: 'John Roe',
            dob: '1975-01-02',
            start_time: '15:00',
            title: 'Follow-up',
            status: 'Pending'
        }
    ]
};

// Session pid the mocked shell reports; mutate per test.
let sessionPid = null;

function jsonResponse(data, ok = true, status = 200) {
    return { ok, status, json: async () => data };
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
            strings: {}
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

function pickerVisible() {
    return !el('acp-picker').classList.contains('d-none');
}

function backdropVisible() {
    return !el('acp-picker-backdrop').classList.contains('d-none');
}

// Flush pending microtasks + zero-delay timers under fake timers. The
// async init chain (readPid -> showGate -> openPicker -> fetch -> render)
// spans several microtask ticks, so flush a batch of them.
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

beforeEach(() => {
    jest.useFakeTimers();
    sessionPid = null;
    // jsdom: window.top === window, so shell helpers mock straight onto window.
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
    window.fetch = jest.fn().mockResolvedValue(jsonResponse(SCHEDULE));
});

afterEach(() => {
    jest.clearAllTimers();
    jest.useRealTimers();
    delete window.AskCopilot;
    delete window.askCopilotConfig;
    delete window.RTop;
});

// ---------------------------------------------------------------------------
// Unbound: blocking popup
// ---------------------------------------------------------------------------
describe('unbound patient gate', () => {

    test('opens blocking picker with dimmed backdrop when no patient bound', async () => {
        loadApp();
        await flush();

        expect(pickerVisible()).toBe(true);
        expect(backdropVisible()).toBe(true);
        expect(el('acp-send').disabled).toBe(true);
        expect(el('acp-input').disabled).toBe(true);
        // Gate mode is non-cancelable.
        expect(el('acp-picker-cancel').classList.contains('d-none')).toBe(true);
        expect(window.AskCopilot.getState().pickerMode).toBe('gate');
    });

    test('Escape does not dismiss the gate popup', async () => {
        loadApp();
        await flush();

        pressEscape();
        expect(pickerVisible()).toBe(true);
    });

    test('backdrop click does not dismiss the gate popup', async () => {
        loadApp();
        await flush();

        el('acp-picker-backdrop').dispatchEvent(
            new MouseEvent('click', { bubbles: true })
        );
        expect(pickerVisible()).toBe(true);
    });

    test('fetches the schedule with same-origin credentials', async () => {
        loadApp();
        await flush();

        expect(window.fetch).toHaveBeenCalledTimes(1);
        const [url, opts] = window.fetch.mock.calls[0];
        expect(url).toContain('/interface/ask_copilot/schedule.php');
        expect(url).toContain('csrf_token_form=test-csrf');
        expect(opts.credentials).toBe('same-origin');
    });
});

// ---------------------------------------------------------------------------
// Schedule rendering
// ---------------------------------------------------------------------------
describe('schedule rendering', () => {

    test('renders next patient card with name, time, and DOB', async () => {
        loadApp();
        await flush();

        const nextWrap = el('acp-picker-next');
        const card = nextWrap.querySelector('button');
        expect(card).not.toBeNull();
        expect(card.textContent).toContain('Jane Doe');
        expect(card.textContent).toContain('14:30');
        expect(card.textContent).toContain('1980-04-12');
    });

    test('renders remaining appointments as clickable rows (next patient excluded)', async () => {
        loadApp();
        await flush();

        const list = el('acp-picker-list');
        const rows = list.querySelectorAll('button');
        expect(rows).toHaveLength(1);
        expect(rows[0].textContent).toContain('John Roe');
        expect(list.textContent).not.toContain('Jane Doe');
    });

    test('when next_pid is missing, all appointments render in the list', async () => {
        window.fetch = jest.fn().mockResolvedValue(
            jsonResponse(Object.assign({}, SCHEDULE, { next_pid: null }))
        );
        loadApp();
        await flush();

        expect(el('acp-picker-next').querySelector('button')).toBeNull();
        expect(el('acp-picker-list').querySelectorAll('button')).toHaveLength(2);
    });

    test('renders patient strings via textContent only (XSS-safe)', async () => {
        const evil = '<img src=x onerror="window.xssFired=true">';
        window.fetch = jest.fn().mockResolvedValue(jsonResponse({
            date: '2026-07-21',
            timezone: 'America/Chicago',
            next_pid: 9,
            appointments: [
                { pid: 9, name: evil, dob: evil, start_time: evil, title: 't', status: 's' }
            ]
        }));
        loadApp();
        await flush();

        expect(el('acp-picker').querySelector('img')).toBeNull();
        expect(window.xssFired).toBeUndefined();
        expect(el('acp-picker-next').textContent).toContain(evil);
    });

    test('empty schedule still offers Search all patients', async () => {
        window.fetch = jest.fn().mockResolvedValue(jsonResponse(
            { date: '2026-07-21', timezone: 'America/Chicago', next_pid: null, appointments: [] }
        ));
        loadApp();
        await flush();

        expect(pickerVisible()).toBe(true);
        expect(el('acp-picker-status').textContent).not.toBe('');
        expect(el('acp-picker-search').classList.contains('d-none')).toBe(false);
    });

    test('schedule fetch failure shows retryable error and keeps Search available', async () => {
        window.fetch = jest.fn()
            .mockRejectedValueOnce(new Error('network down'))
            .mockResolvedValueOnce(jsonResponse(SCHEDULE));
        loadApp();
        await flush();

        expect(pickerVisible()).toBe(true);
        expect(el('acp-picker-status').textContent).not.toBe('');
        expect(el('acp-picker-search').classList.contains('d-none')).toBe(false);

        const retryBtn = el('acp-picker-list').querySelector('button');
        expect(retryBtn).not.toBeNull();
        retryBtn.click();
        await flush();

        expect(el('acp-picker-next').textContent).toContain('Jane Doe');
    });

    test('HTTP error response is handled like a failure', async () => {
        window.fetch = jest.fn().mockResolvedValue(jsonResponse({}, false, 500));
        loadApp();
        await flush();

        expect(pickerVisible()).toBe(true);
        expect(el('acp-picker-status').textContent).not.toBe('');
    });
});

// ---------------------------------------------------------------------------
// Patient selection
// ---------------------------------------------------------------------------
describe('patient selection', () => {

    test('clicking next patient navigates RTop and binds after fast poll', async () => {
        loadApp();
        await flush();

        el('acp-picker-next').querySelector('button').click();
        await flush();

        expect(String(window.RTop.location)).toContain(
            '/interface/patient_file/summary/demographics.php?set_pid=6'
        );
        expect(el('acp-picker-status').textContent).not.toBe('');
        expect(pickerVisible()).toBe(true);

        sessionPid = 6;
        await jest.advanceTimersByTimeAsync(300);

        expect(pickerVisible()).toBe(false);
        expect(backdropVisible()).toBe(false);
        expect(el('acp-send').disabled).toBe(false);
        expect(el('acp-input').disabled).toBe(false);
        expect(el('acp-patient-line').textContent).toContain('6');
        expect(window.AskCopilot.getState().boundPid).toBe(6);
    });

    test('poll timeout leaves popup open with retryable error', async () => {
        loadApp();
        await flush();

        el('acp-picker-next').querySelector('button').click();
        await flush();

        // pid never binds — run past the 1000ms test timeout.
        await jest.advanceTimersByTimeAsync(1500);

        expect(pickerVisible()).toBe(true);
        expect(el('acp-picker-status').textContent).not.toBe('');
        // Controls re-enabled so the physician can retry.
        expect(el('acp-picker-next').querySelector('button').disabled).toBe(false);
        expect(window.AskCopilot.getState().pickerBusy).toBe(false);
    });

    test('degrades to Finder when top.RTop is unavailable', async () => {
        delete window.RTop;
        loadApp();
        await flush();

        el('acp-picker-next').querySelector('button').click();
        await flush();

        expect(window.navigateTab).toHaveBeenCalled();
        expect(String(window.navigateTab.mock.calls[0][0]))
            .toContain('/interface/main/finder/dynamic_finder.php');
        // Popup stays; the pid watcher closes it once bound.
        expect(pickerVisible()).toBe(true);
    });

    test('Search all patients opens the Finder tab', async () => {
        loadApp();
        await flush();

        el('acp-picker-search').click();

        expect(window.navigateTab).toHaveBeenCalled();
        expect(String(window.navigateTab.mock.calls[0][0]))
            .toContain('/interface/main/finder/dynamic_finder.php');
    });
});

// ---------------------------------------------------------------------------
// Bound: no popup + Change patient
// ---------------------------------------------------------------------------
describe('bound patient', () => {

    test('no popup when already bound; Change patient visible; composer enabled', async () => {
        sessionPid = 5;
        loadApp();
        await flush();

        expect(pickerVisible()).toBe(false);
        expect(backdropVisible()).toBe(false);
        expect(window.fetch).not.toHaveBeenCalled();
        expect(el('acp-change-patient').classList.contains('d-none')).toBe(false);
        expect(el('acp-send').disabled).toBe(false);
        expect(el('acp-input').disabled).toBe(false);
        expect(el('acp-patient-line').textContent).toContain('5');
    });

    test('Change patient with empty transcript opens cancelable picker without confirm', async () => {
        sessionPid = 5;
        loadApp();
        await flush();

        el('acp-change-patient').click();
        await flush();

        expect(window.confirm).not.toHaveBeenCalled();
        expect(pickerVisible()).toBe(true);
        expect(el('acp-picker-cancel').classList.contains('d-none')).toBe(false);
        expect(window.AskCopilot.getState().pickerMode).toBe('change');
    });

    test('Change patient with non-empty transcript asks for confirmation', async () => {
        sessionPid = 5;
        const app = loadApp();
        await flush();
        app.pushTranscript('user', 'hello');

        window.confirm = jest.fn(() => false);
        el('acp-change-patient').click();
        await flush();

        expect(window.confirm).toHaveBeenCalled();
        expect(pickerVisible()).toBe(false);
        expect(app.getState().transcriptLength).toBe(1);

        window.confirm = jest.fn(() => true);
        el('acp-change-patient').click();
        await flush();

        expect(pickerVisible()).toBe(true);
        // Confirming only opens the picker; thread survives until an actual switch.
        expect(app.getState().transcriptLength).toBe(1);
    });

    test('Cancel and Escape close the change-patient picker without clearing thread', async () => {
        sessionPid = 5;
        const app = loadApp();
        await flush();
        app.pushTranscript('user', 'hello');

        el('acp-change-patient').click();
        await flush();
        el('acp-picker-cancel').click();
        expect(pickerVisible()).toBe(false);
        expect(app.getState().transcriptLength).toBe(1);
        expect(app.getState().boundPid).toBe(5);

        el('acp-change-patient').click();
        await flush();
        pressEscape();
        expect(pickerVisible()).toBe(false);
        expect(app.getState().transcriptLength).toBe(1);
    });

    test('switching to a new patient clears the thread and rebinds', async () => {
        sessionPid = 5;
        const app = loadApp();
        await flush();
        app.pushTranscript('user', 'hello');

        el('acp-change-patient').click();
        await flush();

        // Pick Jane Doe (pid 6) from the next-patient card.
        el('acp-picker-next').querySelector('button').click();
        await flush();
        sessionPid = 6;
        await jest.advanceTimersByTimeAsync(300);

        expect(pickerVisible()).toBe(false);
        expect(app.getState().boundPid).toBe(6);
        expect(app.getState().transcriptLength).toBe(0);
        expect(el('acp-patient-line').textContent).toContain('6');
    });
});
