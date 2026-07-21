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
    var gateEl = document.getElementById('acp-gate');
    var inputEl = document.getElementById('acp-input');
    var sendBtn = document.getElementById('acp-send');
    var finderBtn = document.getElementById('acp-open-finder');

    /**
     * Normalize session pid from top.getSessionValue / set_pt.php.
     * Treats 0, "", null, and non-positive values as unbound.
     *
     * @returns {Promise<number|null>}
     */
    async function readPid() {
        var raw;

        // Prefer live session pid from the main shell (iframe under main.php).
        if (typeof top !== 'undefined' && typeof top.getSessionValue === 'function') {
            try {
                if (typeof top.restoreSession === 'function') {
                    top.restoreSession();
                }
                raw = await top.getSessionValue('pid');
            } catch (err) {
                raw = undefined;
            }
        }

        // Fallback when opened top-level (no shell helper): server-rendered session pid.
        if (raw === null || raw === undefined || raw === '') {
            if (config.sessionPid != null && config.sessionPid !== '') {
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
     * Show or hide the unbound-patient gate and sync Send enablement.
     *
     * @param {boolean} unbound
     * @param {number|null} pid
     */
    function showGate(unbound, pid) {
        boundPid = unbound ? null : pid;

        if (gateEl) {
            if (unbound) {
                gateEl.classList.remove('d-none');
            } else {
                gateEl.classList.add('d-none');
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
        if (!sendBtn) {
            return;
        }
        sendBtn.disabled = streaming || boundPid === null;
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
                        handlers.onError(data.message || (strings.streamFail || 'Something went wrong. Try again.'));
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
                            (strings.streamFail || 'Something went wrong. Try again.')
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
        // If the physician switched patients mid-thread, clear transcript.
        if (boundPid !== null && pid !== null && pid !== boundPid) {
            clearTranscript();
        } else if (boundPid !== null && pid === null) {
            clearTranscript();
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
        // Thread bind: first message locks threadPid; mismatch handled server-side too.
        if (boundPid !== null && pid !== boundPid) {
            clearTranscript();
        }
        showGate(false, pid);

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
        body.set('bound_pid', String(boundPid || pid));
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
                throw new Error('HTTP ' + response.status);
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
                onError: function (msg) {
                    gotTerminal = true;
                    setProgress('');
                    var errMsg = msg || (strings.streamFail || 'Something went wrong. Try again.');
                    if (
                        errMsg.indexOf('Patient changed') !== -1 ||
                        errMsg.indexOf('Clear the chat') !== -1
                    ) {
                        patientSwitch = true;
                        clearTranscript();
                        errMsg = strings.patientChanged || errMsg;
                    }
                    appendBubble('system', errMsg);
                }
            });

            if (!gotTerminal) {
                // Stream ended without done/error — still finish cleanly.
                setProgress('');
            }
            if (patientSwitch) {
                // Drop the user turn that was rejected after patient switch.
                transcript = [];
            }
        } catch (err) {
            setProgress('');
            appendBubble(
                'system',
                strings.streamFail || 'Something went wrong. Try again.'
            );
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
        if (finderBtn) {
            finderBtn.addEventListener('click', function () {
                openFinder();
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
    }

    // Expose for tests / debugging
    window.AskCopilot = {
        readPid: readPid,
        showGate: showGate,
        sendMessage: sendMessage,
        consumeSse: consumeSse,
        refreshPatientState: refreshPatientState
    };

    bindUi();
    refreshPatientState();
})();
