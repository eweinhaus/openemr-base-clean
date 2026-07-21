/**
 * Ask Co-Pilot iframe client.
 *
 * Reads session pid via top.getSessionValue, gates unbound patients, POSTs
 * messages to stream.php, and parses hybrid SSE (progress / clinical / done / error).
 * All user/model text is inserted via textContent only.
 */
(function () {
    'use strict';

    var config = window.askCopilotConfig || {};
    var strings = config.strings || {};
    var streaming = false;
    var boundPid = null;
    /** @type {Array<{role: string, text: string}>} */
    var transcript = [];

    var messagesEl = document.getElementById('acp-messages');
    var progressEl = document.getElementById('acp-progress');
    var patientLineEl = document.getElementById('acp-patient-line');
    var inputEl = document.getElementById('acp-input');
    var sendBtn = document.getElementById('acp-send');
    var changePatientBtn = document.getElementById('acp-change-patient');
    var pickerEl = document.getElementById('acp-picker');
    var pickerBackdropEl = document.getElementById('acp-picker-backdrop');
    var pickerStatusEl = document.getElementById('acp-picker-status');
    var pickerNextEl = document.getElementById('acp-picker-next');
    var pickerListEl = document.getElementById('acp-picker-list');
    var pickerSearchBtn = document.getElementById('acp-picker-search');
    var pickerCancelBtn = document.getElementById('acp-picker-cancel');

    // Blocking patient picker state. Mode 'gate' = unbound (non-dismissible);
    // mode 'change' = physician-initiated switch (cancelable); null = closed.
    /** @type {'gate'|'change'|null} */
    var pickerMode = null;
    var pickerBusy = false;

    /**
     * Normalize session pid from top.getSessionValue / set_pt.php.
     * Treats 0, "", null, and non-positive values as unbound.
     *
     * @returns {Promise<number|null>}
     */
    async function readPid() {
        var raw;
        var shellPidAvailable =
            typeof top !== 'undefined' && typeof top.getSessionValue === 'function';

        // Prefer live session pid from the main shell (iframe under main.php).
        if (shellPidAvailable) {
            try {
                if (typeof top.restoreSession === 'function') {
                    top.restoreSession();
                }
                raw = await top.getSessionValue('pid');
            } catch (err) {
                raw = undefined;
            }
        }

        // Fallback only when opened top-level (no shell helper): server-rendered session pid.
        // Do not fall back when the shell exists but reports unbound — that would use a stale page-load pid.
        if (raw === null || raw === undefined || raw === '') {
            if (!shellPidAvailable && config.sessionPid != null && config.sessionPid !== '') {
                raw = config.sessionPid;
            } else {
                return null;
            }
        }

        if (raw === null || raw === undefined || raw === '') {
            return null;
        }

        if (typeof raw === 'string') {
            var trimmed = raw.trim();
            if (
                trimmed === '' ||
                trimmed === 'null' ||
                trimmed === 'undefined' ||
                trimmed === '""' ||
                trimmed === "''"
            ) {
                return null;
            }
            try {
                raw = JSON.parse(trimmed);
            } catch (parseErr) {
                raw = trimmed;
            }
        }

        if (raw === null || raw === undefined || raw === '') {
            return null;
        }

        var n = parseInt(raw, 10);
        if (!Number.isFinite(n) || n <= 0) {
            return null;
        }
        return n;
    }

    /**
     * Show or hide the unbound-patient gate (blocking picker popup) and sync
     * composer enablement. Does not overwrite an existing thread lock
     * (boundPid) when still bound — sendMessage / refreshPatientState own
     * lock updates so bound_pid stays meaningful.
     *
     * @param {boolean} unbound
     * @param {number|null} pid
     */
    function showGate(unbound, pid) {
        if (unbound) {
            boundPid = null;
        } else if (boundPid === null && pid) {
            boundPid = pid;
        }

        if (unbound) {
            openPicker('gate');
        } else if (pickerMode === 'gate' && !pickerBusy) {
            // Bound (e.g. picked via Finder or another tab) — drop the gate.
            closePicker();
        }

        if (changePatientBtn) {
            if (!unbound && pid) {
                changePatientBtn.classList.remove('d-none');
            } else {
                changePatientBtn.classList.add('d-none');
            }
        }

        if (patientLineEl) {
            if (!unbound && pid) {
                var prefix = strings.patientPrefix || 'Patient';
                patientLineEl.textContent = prefix + ' #' + String(pid);
            } else {
                patientLineEl.textContent = '';
            }
        }

        updateSendEnabled();
    }

    function updateSendEnabled() {
        if (sendBtn) {
            sendBtn.disabled = streaming || boundPid === null;
        }
        if (inputEl) {
            inputEl.disabled = boundPid === null;
        }
    }

    function setProgress(message) {
        if (!progressEl) {
            return;
        }
        progressEl.textContent = message || '';
    }

    /**
     * Append a chat bubble using textContent only (XSS-safe).
     *
     * @param {'user'|'assistant'|'system'} role
     * @param {string} text
     */
    function appendBubble(role, text) {
        if (!messagesEl) {
            return;
        }
        var bubble = document.createElement('div');
        bubble.className = 'ask-copilot-bubble ask-copilot-bubble-' + role;
        bubble.textContent = text == null ? '' : String(text);
        messagesEl.appendChild(bubble);
        messagesEl.scrollTop = messagesEl.scrollHeight;
    }

    /**
     * Format an SSE/network failure for the system bubble.
     * Includes stable code + correlation id for debugging (no exception dumps).
     *
     * @param {string} message
     * @param {{code?: string, correlation_id?: string, detail?: string}|null} meta
     * @returns {string}
     */
    function formatErrorText(message, meta) {
        var base =
            message && String(message).trim()
                ? String(message).trim()
                : strings.streamFail || 'Something went wrong. Try again.';
        meta = meta || {};
        var parts = [base];
        if (meta.code) {
            parts.push('[' + String(meta.code) + ']');
        }
        if (meta.detail) {
            parts.push('(' + String(meta.detail) + ')');
        }
        if (meta.correlation_id) {
            parts.push('(id: ' + String(meta.correlation_id) + ')');
        }
        return parts.join(' ');
    }

    function clearTranscript() {
        transcript = [];
        if (messagesEl) {
            messagesEl.textContent = '';
        }
        setProgress('');
    }

    /**
     * Keep an open-tab transcript for resend (last 20 entries).
     *
     * @param {'user'|'assistant'} role
     * @param {string} text
     */
    function pushTranscript(role, text) {
        transcript.push({ role: role, text: text == null ? '' : String(text) });
        if (transcript.length > 20) {
            transcript = transcript.slice(-20);
        }
    }

    function openFinder() {
        if (typeof top === 'undefined') {
            return;
        }
        var webroot = top.webroot_url || config.webroot || '';
        var finderUrl = webroot + '/interface/main/finder/dynamic_finder.php';
        if (typeof top.navigateTab === 'function') {
            top.navigateTab(finderUrl, 'fin', function () {
                if (typeof top.activateTabByName === 'function') {
                    top.activateTabByName('fin', true);
                }
            });
        }
    }

    // ------------------------------------------------------------------
    // Blocking patient picker (Wave 1 P2)
    // ------------------------------------------------------------------

    function setPickerStatus(message) {
        if (pickerStatusEl) {
            pickerStatusEl.textContent = message || '';
        }
    }

    function setPickerActionsDisabled(disabled) {
        if (!pickerEl) {
            return;
        }
        var buttons = pickerEl.querySelectorAll('button');
        for (var i = 0; i < buttons.length; i++) {
            buttons[i].disabled = disabled;
        }
    }

    /**
     * Open the picker popup over the dimmed chat pane.
     * 'gate' = unbound, non-dismissible; 'change' = cancelable switch.
     * No-op if already open — the 5s watcher may re-assert an unbound gate.
     *
     * @param {'gate'|'change'} mode
     */
    function openPicker(mode) {
        if (!pickerEl || !pickerBackdropEl) {
            return;
        }
        if (pickerMode !== null) {
            return;
        }
        pickerMode = mode;
        pickerBusy = false;
        pickerBackdropEl.classList.remove('d-none');
        pickerEl.classList.remove('d-none');
        if (pickerCancelBtn) {
            if (mode === 'change') {
                pickerCancelBtn.classList.remove('d-none');
            } else {
                pickerCancelBtn.classList.add('d-none');
            }
        }
        if (typeof pickerEl.focus === 'function') {
            pickerEl.focus();
        }
        loadSchedule();
    }

    function closePicker() {
        if (!pickerEl || !pickerBackdropEl) {
            return;
        }
        pickerMode = null;
        pickerBusy = false;
        pickerBackdropEl.classList.add('d-none');
        pickerEl.classList.add('d-none');
        setPickerStatus('');
    }

    /**
     * Build one clickable patient entry (card or row) with textContent only.
     *
     * @param {{pid: number, name?: string, dob?: string, start_time?: string, title?: string}} appt
     * @param {boolean} isNextCard
     * @returns {HTMLButtonElement}
     */
    function buildPatientButton(appt, isNextCard) {
        var btn = document.createElement('button');
        btn.type = 'button';
        btn.className = isNextCard
            ? 'ask-copilot-picker-card'
            : 'ask-copilot-picker-row';

        if (isNextCard) {
            var badge = document.createElement('span');
            badge.className = 'ask-copilot-picker-badge';
            badge.textContent = strings.nextPatient || 'Next';
            btn.appendChild(badge);
        }

        var time = document.createElement('span');
        time.className = 'ask-copilot-picker-time';
        time.textContent = appt.start_time == null ? '' : String(appt.start_time);
        btn.appendChild(time);

        var name = document.createElement('span');
        name.className = 'ask-copilot-picker-name';
        name.textContent = appt.name == null ? '' : String(appt.name);
        btn.appendChild(name);

        var dob = document.createElement('span');
        dob.className = 'ask-copilot-picker-dob';
        dob.textContent =
            (strings.dobPrefix || 'DOB') +
            ' ' +
            (appt.dob == null ? '' : String(appt.dob));
        btn.appendChild(dob);

        btn.addEventListener('click', function () {
            selectPatient(parseInt(appt.pid, 10));
        });
        return btn;
    }

    /**
     * Render the schedule payload: "Next" card + remaining rows.
     *
     * @param {{next_pid?: number|null, appointments?: Array<object>}} data
     */
    function renderSchedule(data) {
        if (!pickerNextEl || !pickerListEl) {
            return;
        }
        pickerNextEl.textContent = '';
        pickerListEl.textContent = '';

        var appointments = data && Array.isArray(data.appointments) ? data.appointments : [];
        if (appointments.length === 0) {
            setPickerStatus(
                strings.scheduleEmpty || 'No appointments today. Use Search all patients.'
            );
            return;
        }
        setPickerStatus('');

        var nextPid =
            data && data.next_pid != null ? parseInt(data.next_pid, 10) : null;
        var nextIndex = -1;
        if (nextPid !== null && Number.isFinite(nextPid)) {
            for (var i = 0; i < appointments.length; i++) {
                if (parseInt(appointments[i].pid, 10) === nextPid) {
                    nextIndex = i;
                    break;
                }
            }
        }

        if (nextIndex !== -1) {
            pickerNextEl.appendChild(buildPatientButton(appointments[nextIndex], true));
        }

        var heading = document.createElement('div');
        heading.className = 'ask-copilot-picker-list-heading text-muted';
        heading.textContent = strings.appointmentsToday || 'Appointments today';
        var rowsAdded = 0;
        for (var j = 0; j < appointments.length; j++) {
            if (j === nextIndex) {
                continue;
            }
            if (rowsAdded === 0) {
                pickerListEl.appendChild(heading);
            }
            pickerListEl.appendChild(buildPatientButton(appointments[j], false));
            rowsAdded++;
        }
    }

    /** Schedule fetch failed — keep the popup usable via Retry / Finder. */
    function renderScheduleError() {
        if (pickerNextEl) {
            pickerNextEl.textContent = '';
        }
        if (pickerListEl) {
            pickerListEl.textContent = '';
            var retryBtn = document.createElement('button');
            retryBtn.type = 'button';
            retryBtn.className = 'ask-copilot-picker-retry btn btn-outline-secondary btn-sm';
            retryBtn.textContent = strings.retry || 'Retry';
            retryBtn.addEventListener('click', function () {
                loadSchedule();
            });
            pickerListEl.appendChild(retryBtn);
        }
        setPickerStatus(strings.scheduleError || 'Could not load the schedule.');
    }

    /**
     * Fetch today's schedule from the gateway. CSRF goes along as a query
     * param so the backend can require it either way (GET today; if the
     * merged schedule.php demands POST+CSRF this is the single seam to change).
     *
     * @returns {Promise<void>}
     */
    async function loadSchedule() {
        if (!config.scheduleUrl) {
            renderScheduleError();
            return;
        }
        setPickerStatus(strings.scheduleLoading || 'Loading schedule...');
        if (pickerNextEl) {
            pickerNextEl.textContent = '';
        }
        if (pickerListEl) {
            pickerListEl.textContent = '';
        }

        if (typeof top !== 'undefined' && typeof top.restoreSession === 'function') {
            top.restoreSession();
        }

        var url =
            config.scheduleUrl +
            (config.scheduleUrl.indexOf('?') === -1 ? '?' : '&') +
            'csrf_token_form=' +
            encodeURIComponent(config.csrf || '');

        try {
            var response = await fetch(url, {
                method: 'GET',
                credentials: 'same-origin',
                headers: { Accept: 'application/json' }
            });
            if (!response.ok) {
                throw new Error('HTTP ' + response.status);
            }
            var data = await response.json();
            renderSchedule(data);
        } catch (err) {
            renderScheduleError();
        }
    }

    function delay(ms) {
        return new Promise(function (resolve) {
            setTimeout(resolve, ms);
        });
    }

    /**
     * Fast-poll the session pid until it matches the selected patient.
     *
     * @param {number} targetPid
     * @returns {Promise<boolean>} true when bound, false on timeout/close
     */
    async function pollForPid(targetPid) {
        var interval =
            Number(config.pickerPollIntervalMs) > 0
                ? Number(config.pickerPollIntervalMs)
                : 350;
        var timeoutMs =
            Number(config.pickerPollTimeoutMs) > 0
                ? Number(config.pickerPollTimeoutMs)
                : 10000;
        var waited = 0;
        while (waited < timeoutMs) {
            await delay(interval);
            waited += interval;
            if (pickerMode === null) {
                return false;
            }
            var pid = await readPid();
            if (pid === targetPid) {
                return true;
            }
        }
        return false;
    }

    /**
     * Physician clicked a patient: navigate the canonical OpenEMR patient
     * context (top frame set_pid), then fast-poll the session pid until the
     * bind lands. Never binds silently — always reached via a click.
     *
     * @param {number} pid
     * @returns {Promise<void>}
     */
    async function selectPatient(pid) {
        if (pickerBusy || !Number.isFinite(pid) || pid <= 0) {
            return;
        }

        var rtopAvailable = typeof top !== 'undefined' && top.RTop;
        if (!rtopAvailable) {
            // Not under the main shell — degrade to the Finder tab; the
            // patient watcher closes the gate once the session pid binds.
            openFinder();
            setPickerStatus(
                strings.useFinder || 'Select the patient from the search tab.'
            );
            return;
        }

        pickerBusy = true;
        setPickerActionsDisabled(true);
        setPickerStatus(strings.openingChart || 'Opening chart...');

        if (typeof top.restoreSession === 'function') {
            top.restoreSession();
        }
        var webroot = top.webroot_url || config.webroot || '';
        top.RTop.location =
            webroot +
            '/interface/patient_file/summary/demographics.php?set_pid=' +
            encodeURIComponent(String(pid));

        var bound = await pollForPid(pid);
        if (bound) {
            if (pickerMode === 'change' && boundPid !== null && boundPid !== pid) {
                // Confirmed switch: clear the thread for the new patient.
                clearTranscript();
            }
            boundPid = pid;
            pickerBusy = false;
            closePicker();
            showGate(false, pid);
            return;
        }

        // Timeout (or picker closed externally): stay open, allow retry.
        pickerBusy = false;
        setPickerActionsDisabled(false);
        if (pickerMode !== null) {
            setPickerStatus(
                strings.bindTimeout ||
                    'Could not confirm the patient selection. Try again.'
            );
        }
    }

    /** Header "Change patient": confirm when a thread would be cleared. */
    function requestPatientChange() {
        if (pickerMode !== null) {
            return;
        }
        if (transcript.length > 0) {
            var msg =
                strings.confirmSwitch || 'Switching patients clears this chat. Continue?';
            if (!window.confirm(msg)) {
                return;
            }
        }
        openPicker('change');
    }

    /** Light-touch focus trap: keep Tab cycling inside the open dialog. */
    function trapPickerFocus(evt) {
        if (pickerMode === null || evt.key !== 'Tab' || !pickerEl) {
            return;
        }
        var focusable = pickerEl.querySelectorAll('button:not([disabled])');
        if (focusable.length === 0) {
            evt.preventDefault();
            return;
        }
        var first = focusable[0];
        var last = focusable[focusable.length - 1];
        var active = document.activeElement;
        if (evt.shiftKey && (active === first || active === pickerEl)) {
            evt.preventDefault();
            last.focus();
        } else if (!evt.shiftKey && active === last) {
            evt.preventDefault();
            first.focus();
        }
    }

    /**
     * Parse one SSE frame (event + data lines) into {event, data}.
     *
     * @param {string} frame
     * @returns {{event: string, data: object}|null}
     */
    function parseSseFrame(frame) {
        var eventName = 'message';
        var dataLines = [];
        var lines = frame.split('\n');
        for (var i = 0; i < lines.length; i++) {
            var line = lines[i];
            if (line.indexOf('event:') === 0) {
                eventName = line.slice(6).trim();
            } else if (line.indexOf('data:') === 0) {
                dataLines.push(line.slice(5).trim());
            }
        }
        if (dataLines.length === 0) {
            return null;
        }
        var dataRaw = dataLines.join('\n');
        var data;
        try {
            data = JSON.parse(dataRaw);
        } catch (err) {
            data = { message: dataRaw };
        }
        return { event: eventName, data: data };
    }

    /**
     * Consume a fetch Response body as SSE over ReadableStream.
     *
     * @param {Response} response
     * @param {{onProgress?: Function, onClinical?: Function, onDone?: Function, onError?: Function}} handlers
     * @returns {Promise<void>}
     */
    async function consumeSse(response, handlers) {
        handlers = handlers || {};
        if (!response.body || typeof response.body.getReader !== 'function') {
            throw new Error('No response body stream');
        }

        var reader = response.body.getReader();
        var decoder = new TextDecoder();
        var buffer = '';

        while (true) {
            var result = await reader.read();
            if (result.done) {
                break;
            }
            buffer += decoder.decode(result.value, { stream: true });

            var parts = buffer.split('\n\n');
            buffer = parts.pop() || '';

            for (var i = 0; i < parts.length; i++) {
                var frame = parts[i].replace(/^\uFEFF/, '').trim();
                if (!frame || frame.charAt(0) === ':') {
                    continue;
                }
                var parsed = parseSseFrame(frame);
                if (!parsed) {
                    continue;
                }
                var evt = parsed.event;
                var data = parsed.data || {};

                if (evt === 'progress') {
                    if (typeof handlers.onProgress === 'function') {
                        handlers.onProgress(data.message || '');
                    }
                } else if (evt === 'clinical') {
                    if (typeof handlers.onClinical === 'function') {
                        handlers.onClinical(data.text || '');
                    }
                } else if (evt === 'done') {
                    if (typeof handlers.onDone === 'function') {
                        handlers.onDone(data.correlation_id || '');
                    }
                } else if (evt === 'error') {
                    if (typeof handlers.onError === 'function') {
                        handlers.onError(
                            data.message || (strings.streamFail || 'Something went wrong. Try again.'),
                            {
                                code: data.code || '',
                                correlation_id: data.correlation_id || '',
                                detail: data.detail || ''
                            }
                        );
                    }
                }
            }
        }

        // Flush trailing frame without final blank line
        var trailing = buffer.trim();
        if (trailing && trailing.charAt(0) !== ':') {
            var last = parseSseFrame(trailing);
            if (last) {
                if (last.event === 'progress' && typeof handlers.onProgress === 'function') {
                    handlers.onProgress((last.data && last.data.message) || '');
                } else if (last.event === 'clinical' && typeof handlers.onClinical === 'function') {
                    handlers.onClinical((last.data && last.data.text) || '');
                } else if (last.event === 'done' && typeof handlers.onDone === 'function') {
                    handlers.onDone((last.data && last.data.correlation_id) || '');
                } else if (last.event === 'error' && typeof handlers.onError === 'function') {
                    handlers.onError(
                        (last.data && last.data.message) ||
                            (strings.streamFail || 'Something went wrong. Try again.'),
                        {
                            code: (last.data && last.data.code) || '',
                            correlation_id: (last.data && last.data.correlation_id) || '',
                            detail: (last.data && last.data.detail) || ''
                        }
                    );
                }
            }
        }
    }

    /**
     * Refresh patient gate from session pid.
     *
     * @returns {Promise<number|null>}
     */
    async function refreshPatientState() {
        var pid = await readPid();
        // If the physician switched patients mid-thread, clear transcript and re-lock.
        if (boundPid !== null && pid !== null && pid !== boundPid) {
            clearTranscript();
            boundPid = pid;
            if (pickerMode === 'change' && !pickerBusy) {
                // Switch landed outside the picker flow (e.g. via Finder tab)
                // while the change dialog was open — it served its purpose.
                closePicker();
            }
            appendBubble(
                'system',
                strings.patientChanged || 'Patient changed. Clear the chat and try again.'
            );
        } else if (boundPid !== null && pid === null) {
            clearTranscript();
            boundPid = null;
        }
        showGate(pid === null, pid);
        return pid;
    }

    /**
     * Send the composer message through the session-proxy gateway SSE endpoint.
     *
     * @returns {Promise<void>}
     */
    async function sendMessage() {
        if (streaming) {
            return;
        }

        var pid = await readPid();
        if (pid === null) {
            showGate(true, null);
            setProgress(strings.selectPatient || 'Select a patient before chatting.');
            return;
        }
        // Thread bind: first message locks; mid-thread switch clears and asks user to resend.
        // Capture lock before UI updates so bound_pid posted to the gateway stays meaningful.
        var requestBoundPid = boundPid !== null ? boundPid : pid;
        if (boundPid !== null && pid !== boundPid) {
            clearTranscript();
            boundPid = pid;
            showGate(false, pid);
            appendBubble(
                'system',
                strings.patientChanged || 'Patient changed. Clear the chat and try again.'
            );
            return;
        }
        showGate(false, pid);
        boundPid = requestBoundPid;

        var message = inputEl ? String(inputEl.value || '').trim() : '';
        if (!message) {
            setProgress(strings.enterMessage || 'Enter a message.');
            return;
        }

        streaming = true;
        updateSendEnabled();
        setProgress('');
        appendBubble('user', message);
        pushTranscript('user', message);
        if (inputEl) {
            inputEl.value = '';
        }

        if (typeof top !== 'undefined' && typeof top.restoreSession === 'function') {
            top.restoreSession();
        }

        var body = new URLSearchParams();
        body.set('csrf_token_form', config.csrf || '');
        body.set('message', message);
        body.set('bound_pid', String(requestBoundPid));
        body.set('transcript', JSON.stringify(transcript.slice(0, -1)));

        var gotTerminal = false;
        var patientSwitch = false;

        try {
            var response = await fetch(config.streamUrl, {
                method: 'POST',
                credentials: 'same-origin',
                headers: {
                    Accept: 'text/event-stream',
                    'Content-Type': 'application/x-www-form-urlencoded;charset=UTF-8'
                },
                body: body.toString()
            });

            if (!response.ok) {
                var httpErr = new Error(
                    'Ask Co-Pilot stream returned HTTP ' + response.status + '.'
                );
                httpErr.code = 'http_' + response.status;
                throw httpErr;
            }

            await consumeSse(response, {
                onProgress: function (msg) {
                    setProgress(msg);
                },
                onClinical: function (text) {
                    setProgress('');
                    appendBubble('assistant', text);
                    pushTranscript('assistant', text);
                },
                onDone: function () {
                    gotTerminal = true;
                    setProgress('');
                },
                onError: function (msg, meta) {
                    gotTerminal = true;
                    setProgress('');
                    var errMsg = formatErrorText(msg, meta);
                    if (
                        errMsg.indexOf('Patient changed') !== -1 ||
                        errMsg.indexOf('Clear the chat') !== -1 ||
                        (meta && meta.code === 'patient_changed')
                    ) {
                        patientSwitch = true;
                        clearTranscript();
                        errMsg = formatErrorText(
                            strings.patientChanged || msg,
                            meta
                        );
                    }
                    appendBubble('system', errMsg);
                }
            });

            if (!gotTerminal) {
                // Stream ended without done/error (dropped connection, gateway
                // timeout) — tell the user instead of failing silently.
                setProgress('');
                appendBubble(
                    'system',
                    formatErrorText(
                        strings.streamIncomplete ||
                            'Stream ended before a reply finished. Try again.',
                        { code: 'stream_incomplete' }
                    )
                );
            }
            if (patientSwitch) {
                // Drop the user turn that was rejected after patient switch.
                transcript = [];
            }
        } catch (err) {
            setProgress('');
            var catchMsg =
                err && err.message
                    ? String(err.message)
                    : strings.streamFail || 'Something went wrong. Try again.';
            var catchCode =
                err && err.code
                    ? String(err.code)
                    : err && err.name === 'TypeError'
                      ? 'network_error'
                      : 'client_error';
            appendBubble('system', formatErrorText(catchMsg, { code: catchCode }));
        } finally {
            streaming = false;
            await refreshPatientState();
        }
    }

    function bindUi() {
        if (sendBtn) {
            sendBtn.addEventListener('click', function () {
                sendMessage();
            });
        }
        if (inputEl) {
            inputEl.addEventListener('keydown', function (evt) {
                if (evt.key === 'Enter' && !evt.shiftKey) {
                    evt.preventDefault();
                    sendMessage();
                }
            });
        }
        if (changePatientBtn) {
            changePatientBtn.addEventListener('click', function () {
                requestPatientChange();
            });
        }
        if (pickerSearchBtn) {
            pickerSearchBtn.addEventListener('click', function () {
                openFinder();
            });
        }
        if (pickerCancelBtn) {
            pickerCancelBtn.addEventListener('click', function () {
                if (pickerMode === 'change' && !pickerBusy) {
                    closePicker();
                }
            });
        }
        if (pickerBackdropEl) {
            pickerBackdropEl.addEventListener('click', function () {
                // Gate mode is non-dismissible; change mode may back out.
                if (pickerMode === 'change' && !pickerBusy) {
                    closePicker();
                }
            });
        }
        document.addEventListener('keydown', function (evt) {
            if (evt.key === 'Escape' && pickerMode === 'change' && !pickerBusy) {
                closePicker();
                return;
            }
            trapPickerFocus(evt);
        });
    }

    // Expose for tests / debugging
    window.AskCopilot = {
        readPid: readPid,
        showGate: showGate,
        sendMessage: sendMessage,
        consumeSse: consumeSse,
        refreshPatientState: refreshPatientState,
        openPicker: openPicker,
        closePicker: closePicker,
        loadSchedule: loadSchedule,
        selectPatient: selectPatient,
        pushTranscript: pushTranscript,
        getState: function () {
            return {
                boundPid: boundPid,
                pickerMode: pickerMode,
                pickerBusy: pickerBusy,
                streaming: streaming,
                transcriptLength: transcript.length
            };
        }
    };

    bindUi();
    refreshPatientState();

    // Light patient watcher: keep the gate/patient line in sync when the
    // physician switches patients in another tab. Skipped mid-stream so it
    // never clears a transcript while a reply is rendering.
    setInterval(function () {
        if (!streaming) {
            refreshPatientState();
        }
    }, 5000);
})();
