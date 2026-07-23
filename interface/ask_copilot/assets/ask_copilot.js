/**
 * Ask Co-Pilot iframe client.
 *
 * Reads session pid via top.getSessionValue, gates unbound patients, POSTs
 * messages to stream.php, and parses hybrid SSE (progress / clinical / citation /
 * done / error). Clinical turns buffer until citation arrives (or timeout).
 * All user/model text is inserted via textContent only.
 */
(function () {
    'use strict';

    var config = window.askCopilotConfig || {};
    var strings = config.strings || {};
    var streaming = false;
    var boundPid = null;
    /** @type {string|null} */
    var boundPatientName = config.sessionPatientName || null;
    /** pid → display name from the last schedule fetch */
    var schedulePatientNames = {};
    /** @type {HTMLElement|null} */
    var typingBubbleEl = null;
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
    var citeEl = document.getElementById('acp-cite');
    var citeBackdropEl = document.getElementById('acp-cite-backdrop');
    var citeBodyEl = document.getElementById('acp-cite-body');
    var citeOpenEl = document.getElementById('acp-cite-open');
    var citeCloseBtn = document.getElementById('acp-cite-close');

    // Blocking patient picker state. Mode 'gate' = unbound (non-dismissible);
    // mode 'change' = physician-initiated switch (cancelable); null = closed.
    /** @type {'gate'|'change'|null} */
    var pickerMode = null;
    var pickerBusy = false;

    /** Citation dialog open + Source button to restore focus to (H12). */
    var citeOpen = false;
    /** @type {HTMLElement|null} */
    var citeReturnFocusEl = null;
    /** citation_id → citation payload for the current chat surface (PRD 06). */
    var activeCitations = {};

    // Allowlisted research label hosts for the Open label href (H7).
    var ALLOWED_CITE_HOSTS = {
        'dailymed.nlm.nih.gov': true,
        'www.dailymed.nlm.nih.gov': true,
        'api.fda.gov': true,
        'www.api.fda.gov': true
    };

    /**
     * True only for https URLs on DailyMed / openFDA hosts.
     *
     * @param {string|null|undefined} url
     * @returns {boolean}
     */
    function isAllowlistedHttpsUrl(url) {
        if (url == null || typeof url !== 'string' || url === '') {
            return false;
        }
        try {
            var parsed = new URL(url);
            if (parsed.protocol !== 'https:') {
                return false;
            }
            var host = String(parsed.hostname || '').toLowerCase();
            return Object.prototype.hasOwnProperty.call(ALLOWED_CITE_HOSTS, host);
        } catch (err) {
            return false;
        }
    }

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
            boundPatientName = null;
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
                updatePatientLine(pid, boundPatientName);
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
        var displayText = text == null ? '' : String(text);
        if (role === 'assistant') {
            displayText = humanizeIsoDatesInText(displayText);
        }
        bubble.textContent = displayText;
        messagesEl.appendChild(bubble);
        messagesEl.scrollTop = messagesEl.scrollHeight;
    }

    /**
     * Show a lightweight assistant "thinking" bubble while a reply streams.
     */
    function showTypingIndicator() {
        removeTypingIndicator();
        if (!messagesEl) {
            return;
        }
        typingBubbleEl = document.createElement('div');
        typingBubbleEl.className =
            'ask-copilot-bubble ask-copilot-bubble-assistant ask-copilot-typing';
        typingBubbleEl.setAttribute('aria-busy', 'true');
        typingBubbleEl.textContent = strings.typing || '…';
        messagesEl.appendChild(typingBubbleEl);
        messagesEl.scrollTop = messagesEl.scrollHeight;
    }

    function removeTypingIndicator() {
        if (typingBubbleEl && typingBubbleEl.parentNode) {
            typingBubbleEl.parentNode.removeChild(typingBubbleEl);
        }
        typingBubbleEl = null;
    }

    /**
     * Resolve a human-readable patient name for the header line.
     *
     * @param {number} pid
     * @param {string|null|undefined} knownName
     * @returns {Promise<void>}
     */
    async function updatePatientLine(pid, knownName) {
        if (!patientLineEl || !pid) {
            if (patientLineEl) {
                patientLineEl.textContent = '';
            }
            return;
        }

        var name =
            knownName != null && String(knownName).trim() !== ''
                ? String(knownName).trim()
                : schedulePatientNames[pid] || null;

        if (!name && config.patientUrl) {
            name = await fetchPatientName(pid);
        }

        if (name) {
            boundPatientName = name;
            patientLineEl.textContent = name;
            return;
        }

        var prefix = strings.patientPrefix || 'Patient';
        patientLineEl.textContent = prefix + ' #' + String(pid);
    }

    /**
     * Fetch display name for the session-bound patient (patient.php).
     *
     * @param {number} pid
     * @returns {Promise<string|null>}
     */
    async function fetchPatientName(pid) {
        if (!config.patientUrl || !Number.isFinite(pid) || pid <= 0) {
            return null;
        }

        if (typeof top !== 'undefined' && typeof top.restoreSession === 'function') {
            top.restoreSession();
        }

        var url =
            config.patientUrl +
            (config.patientUrl.indexOf('?') === -1 ? '?' : '&') +
            'csrf_token_form=' +
            encodeURIComponent(config.csrf || '');

        try {
            var response = await fetch(url, {
                method: 'GET',
                credentials: 'same-origin',
                headers: { Accept: 'application/json' }
            });
            if (!response.ok) {
                return null;
            }
            var data = await response.json();
            if (
                data &&
                parseInt(data.pid, 10) === pid &&
                data.name != null &&
                String(data.name).trim() !== ''
            ) {
                return String(data.name).trim();
            }
        } catch (err) {
            return null;
        }

        return null;
    }

    function cacheSchedulePatientNames(data) {
        schedulePatientNames = {};
        var appointments =
            data && Array.isArray(data.appointments) ? data.appointments : [];
        for (var i = 0; i < appointments.length; i++) {
            var appt = appointments[i];
            if (!appt || appt.pid == null) {
                continue;
            }
            var apptPid = parseInt(appt.pid, 10);
            if (!Number.isFinite(apptPid) || apptPid <= 0) {
                continue;
            }
            if (appt.name != null && String(appt.name).trim() !== '') {
                schedulePatientNames[apptPid] = String(appt.name).trim();
            }
        }
    }

    /**
     * Append a cite-field row (label + value) via textContent only.
     *
     * @param {HTMLElement} parent
     * @param {string} label
     * @param {string} value
     */
    function appendCiteRow(parent, label, value) {
        if (value == null || String(value) === '') {
            return;
        }
        var row = document.createElement('div');
        row.className = 'ask-copilot-cite-row';
        var lab = document.createElement('span');
        lab.className = 'ask-copilot-cite-label';
        lab.textContent = label;
        var val = document.createElement('span');
        val.className = 'ask-copilot-cite-value';
        val.textContent = String(value);
        row.appendChild(lab);
        row.appendChild(val);
        parent.appendChild(row);
    }

    /**
     * Build citation_id → citation map from a batch list.
     *
     * @param {Array<object>|null|undefined} list
     * @returns {Object<string, object>}
     */
    function citationMapFromList(list) {
        var map = {};
        if (!Array.isArray(list)) {
            return map;
        }
        for (var i = 0; i < list.length; i++) {
            var c = normalizeCitation(list[i]);
            if (c && c.citation_id != null && String(c.citation_id) !== '') {
                map[String(c.citation_id)] = c;
            }
        }
        return map;
    }

    /**
     * Merge a citation batch into the in-memory lookup used by Source clicks.
     *
     * @param {Array<object>|null|undefined} list
     */
    function registerCitations(list) {
        var map = citationMapFromList(list);
        var keys = Object.keys(map);
        for (var i = 0; i < keys.length; i++) {
            activeCitations[keys[i]] = map[keys[i]];
        }
    }

    /**
     * Normalize SSE / test citation objects for the in-pane dialog.
     *
     * @param {object|null|undefined} raw
     * @returns {object|null}
     */
    function normalizeCitation(raw) {
        if (raw == null || typeof raw !== 'object') {
            return null;
        }
        var locator = raw.locator;
        if (locator == null || typeof locator !== 'object') {
            locator = {
                table: raw.table != null ? String(raw.table) : '',
                id: raw.id != null ? String(raw.id) : '',
                url: raw.url != null ? String(raw.url) : ''
            };
        } else {
            locator = {
                table: locator.table == null ? '' : String(locator.table),
                id: locator.id == null ? '' : String(locator.id),
                url: locator.url == null ? '' : String(locator.url),
                fhir_uuid:
                    locator.fhir_uuid == null ? '' : String(locator.fhir_uuid)
            };
        }
        return {
            citation_id: raw.citation_id,
            source_type: raw.source_type,
            title: raw.title,
            excerpt: raw.excerpt,
            retrieved_at: raw.retrieved_at,
            locator: locator
        };
    }

    /**
     * NotebookLM-style citation number from citation_id (c1 → 1).
     *
     * @param {string|null|undefined} citeId
     * @returns {string}
     */
    function citationDisplayNumber(citeId) {
        if (citeId == null || String(citeId) === '') {
            return '';
        }
        var match = String(citeId).match(/^c(\d+)$/i);
        return match ? match[1] : String(citeId);
    }

    function friendlySourceType(sourceType) {
        if (sourceType === 'chart') {
            return strings.sourceChart || 'Patient chart';
        }
        if (sourceType === 'research') {
            return strings.sourceResearch || 'Drug label';
        }
        if (sourceType === 'note') {
            return strings.sourceNote || 'Clinical note';
        }
        return strings.sourceLabel || 'Source';
    }

    function friendlyTableName(table) {
        var map = {
            prescriptions: 'Prescriptions',
            lists: 'Problem or allergy list',
            procedure_result: 'Lab results',
            form_encounter: 'Visit',
            form_clinical_notes: 'Clinical notes',
            openfda: 'Drug label (openFDA)',
            dailymed: 'Drug label (DailyMed)'
        };
        if (table == null || String(table) === '') {
            return '';
        }
        var key = String(table);
        return Object.prototype.hasOwnProperty.call(map, key) ? map[key] : key;
    }

    function formatDisplayDate(raw) {
        if (raw == null || String(raw).trim() === '') {
            return '';
        }
        var text = String(raw).trim();
        var dateOnly = text.match(/^(\d{4})-(\d{2})-(\d{2})$/);
        if (dateOnly) {
            var d = new Date(
                Number(dateOnly[1]),
                Number(dateOnly[2]) - 1,
                Number(dateOnly[3])
            );
            if (!isNaN(d.getTime())) {
                return d.toLocaleDateString('en-US', {
                    month: 'short',
                    day: 'numeric',
                    year: 'numeric'
                });
            }
        }
        var parsed = Date.parse(text);
        if (Number.isFinite(parsed)) {
            return new Date(parsed).toLocaleDateString('en-US', {
                month: 'short',
                day: 'numeric',
                year: 'numeric'
            });
        }
        return text;
    }

    /**
     * Replace ISO date tokens (2026-01-18) in assistant/citation copy.
     *
     * @param {string|null|undefined} text
     * @returns {string}
     */
    function humanizeIsoDatesInText(text) {
        if (text == null || text === '') {
            return '';
        }
        return String(text).replace(/\b(\d{4})-(\d{2})-(\d{2})\b/g, function (match) {
            return formatDisplayDate(match);
        });
    }

    function formatRetrievedAt(raw) {
        return formatDisplayDate(raw);
    }

    /**
     * Plain-text fallback for the citation dialog (WebDriver getText-safe).
     *
     * @param {object} citation
     * @returns {string}
     */
    function formatCitationPlainText(citation) {
        var lines = [];
        if (citation.title) {
            lines.push(humanizeIsoDatesInText(String(citation.title)));
        }
        var excerpt = citation.excerpt ? String(citation.excerpt) : '';
        if (excerpt && excerpt !== citation.title) {
            lines.push(humanizeIsoDatesInText(excerpt));
        }
        if (citation.source_type) {
            lines.push(
                (strings.citeFrom || 'From') +
                    ': ' +
                    friendlySourceType(citation.source_type)
            );
        }
        var locator = citation.locator || {};
        var recordType = friendlyTableName(locator.table);
        if (recordType) {
            lines.push((strings.citeRecordType || 'Record type') + ': ' + recordType);
        }
        if (locator.id) {
            lines.push((strings.citeRecordId || 'Record ID') + ': ' + String(locator.id));
        }
        if (citation.retrieved_at) {
            lines.push(
                (strings.citeRetrieved || 'Retrieved') +
                    ': ' +
                    formatRetrievedAt(citation.retrieved_at)
            );
        }
        return lines.join('\n');
    }

    /**
     * Structured citation body for the in-pane dialog (textContent-only rows).
     *
     * @param {HTMLElement} parent
     * @param {object} citation
     */
    function renderCitationBody(parent, citation) {
        if (!parent) {
            return;
        }
        parent.textContent = '';

        var title = citation.title ? String(citation.title).trim() : '';
        var excerpt = citation.excerpt ? String(citation.excerpt).trim() : '';

        if (title) {
            appendCiteRow(
                parent,
                strings.citeSummary || 'Summary',
                humanizeIsoDatesInText(title)
            );
        }
        if (excerpt && excerpt !== title) {
            appendCiteRow(
                parent,
                strings.citeDetail || 'Details',
                humanizeIsoDatesInText(excerpt)
            );
        }
        if (citation.source_type) {
            appendCiteRow(
                parent,
                strings.citeFrom || 'From',
                friendlySourceType(citation.source_type)
            );
        }

        var locator = citation.locator || {};
        var recordType = friendlyTableName(locator.table);
        if (recordType) {
            appendCiteRow(parent, strings.citeRecordType || 'Record type', recordType);
        }
        if (locator.id) {
            appendCiteRow(parent, strings.citeRecordId || 'Record ID', String(locator.id));
        }
        if (citation.retrieved_at) {
            appendCiteRow(
                parent,
                strings.citeRetrieved || 'Retrieved',
                formatRetrievedAt(citation.retrieved_at)
            );
        }

        if (!parent.hasChildNodes()) {
            parent.textContent = formatCitationPlainText(citation);
        }
    }

    function lookupCitation(citeId) {
        if (citeId == null || String(citeId) === '') {
            return null;
        }
        var key = String(citeId);
        if (Object.prototype.hasOwnProperty.call(activeCitations, key)) {
            return activeCitations[key];
        }
        return null;
    }

    /**
     * Attach a Source control for one verified claim segment.
     *
     * @param {HTMLElement} line
     * @param {string} citeId
     * @param {object} citation
     */
    function attachSourceControl(line, citeId, citation) {
        registerCitations([citation]);
        var displayNum = citationDisplayNumber(citeId);
        var srcBtn = document.createElement('button');
        srcBtn.type = 'button';
        srcBtn.className =
            'btn btn-link btn-sm ask-copilot-cite-ref ask-copilot-source';
        srcBtn.setAttribute('data-cite-id', citeId);
        try {
            srcBtn.setAttribute('data-citation-json', JSON.stringify(citation));
        } catch (jsonErr) {
            // ignore — lookupCitation still works when registry is warm
        }
        srcBtn.textContent = displayNum || '?';
        srcBtn.setAttribute(
            'aria-label',
            (strings.sourceLabel || 'Source') + ' ' + (displayNum || citeId)
        );
        srcBtn.addEventListener('click', function (evt) {
            evt.preventDefault();
            var payload = lookupCitation(citeId);
            if (!payload) {
                var raw = srcBtn.getAttribute('data-citation-json');
                if (raw) {
                    try {
                        payload = normalizeCitation(JSON.parse(raw));
                    } catch (parseErr) {
                        payload = null;
                    }
                }
            }
            if (payload) {
                openCitation(payload, srcBtn);
            }
        });
        line.appendChild(srcBtn);
    }

    /**
     * Build one segment row (summary, claim, or assembly).
     *
     * @param {{kind?: string, text?: string, citation_id?: string}} seg
     * @param {Object<string, object>} map
     * @returns {HTMLElement}
     */
    function renderSegmentLine(seg, map) {
        var line = document.createElement('div');
        line.className = 'ask-copilot-segment';
        if (seg.kind === 'summary') {
            line.className += ' ask-copilot-segment-summary';
        }

        var textSpan = document.createElement('span');
        textSpan.className = 'ask-copilot-segment-text';
        textSpan.textContent =
            seg.text == null ? '' : humanizeIsoDatesInText(String(seg.text));
        line.appendChild(textSpan);

        var citeId =
            seg.citation_id != null && String(seg.citation_id) !== ''
                ? String(seg.citation_id)
                : '';
        if (seg.kind === 'claim' && citeId && map[citeId]) {
            attachSourceControl(line, citeId, map[citeId]);
        }

        return line;
    }

    /** Empty-domain assembly lines shown inside the collapsed sources panel. */
    var COLLAPSED_ASSEMBLY_TEXTS = {
        'No allergies on file.': true,
        'No recent notes on file.': true
    };

    /**
     * @param {{kind?: string, text?: string}} seg
     * @returns {boolean}
     */
    function isCollapsedAssemblySegment(seg) {
        if (!seg || seg.kind !== 'assembly') {
            return false;
        }
        var text = seg.text == null ? '' : String(seg.text);
        return Object.prototype.hasOwnProperty.call(COLLAPSED_ASSEMBLY_TEXTS, text);
    }

    /**
     * Localized label for the collapsed-sources toggle.
     *
     * @param {number} count
     * @returns {string}
     */
    function formatShowVerifiedSources(count) {
        var template = strings.showVerifiedSources;
        if (template && String(template).indexOf('{count}') !== -1) {
            return String(template).replace('{count}', String(count));
        }
        return 'Show verified sources (' + count + ')';
    }

    /**
     * Render an assistant turn: summary visible; verified claims and select
     * empty-domain assembly lines collapsed; other assembly/disclaimer visible
     * after the collapse block.
     *
     * @param {Array<{kind?: string, text?: string, citation_id?: string}>} segments
     * @param {Object<string, object>} citationMap
     */
    function renderAssistantTurn(segments, citationMap) {
        if (!messagesEl) {
            return;
        }
        var bubble = document.createElement('div');
        bubble.className = 'ask-copilot-bubble ask-copilot-bubble-assistant';
        var segs = Array.isArray(segments) ? segments : [];
        var map = citationMap || {};
        var claims = [];
        var panelAssemblies = [];
        var assemblies = [];

        for (var i = 0; i < segs.length; i++) {
            var seg = segs[i] || {};
            if (seg.kind === 'summary') {
                bubble.appendChild(renderSegmentLine(seg, map));
            } else if (seg.kind === 'claim') {
                claims.push(seg);
            } else if (isCollapsedAssemblySegment(seg)) {
                panelAssemblies.push(seg);
            } else if (seg.kind === 'assembly') {
                assemblies.push(seg);
            } else {
                bubble.appendChild(renderSegmentLine(seg, map));
            }
        }

        if (claims.length > 0) {
            var toggle = document.createElement('button');
            toggle.type = 'button';
            toggle.className =
                'btn btn-link btn-sm ask-copilot-sources-toggle';
            toggle.setAttribute('aria-expanded', 'false');
            toggle.textContent = formatShowVerifiedSources(claims.length);

            var panel = document.createElement('div');
            panel.className = 'ask-copilot-sources-panel';
            panel.hidden = true;

            for (var j = 0; j < claims.length; j++) {
                panel.appendChild(renderSegmentLine(claims[j], map));
            }
            for (var p = 0; p < panelAssemblies.length; p++) {
                panel.appendChild(renderSegmentLine(panelAssemblies[p], map));
            }

            toggle.addEventListener('click', function () {
                var opening = panel.hidden;
                panel.hidden = !opening;
                toggle.setAttribute(
                    'aria-expanded',
                    opening ? 'true' : 'false'
                );
                toggle.textContent = opening
                    ? strings.hideSources || 'Hide sources'
                    : formatShowVerifiedSources(claims.length);
            });

            bubble.appendChild(toggle);
            bubble.appendChild(panel);
        } else {
            assemblies = panelAssemblies.concat(assemblies);
        }

        for (var k = 0; k < assemblies.length; k++) {
            bubble.appendChild(renderSegmentLine(assemblies[k], map));
        }

        messagesEl.appendChild(bubble);
        messagesEl.scrollTop = messagesEl.scrollHeight;
    }

    /**
     * Open the in-pane citation dialog. Mutually exclusive with the picker (H11).
     * Gate mode wins when unbound — refuse opening cite over the gate.
     *
     * @param {object} citation
     * @param {HTMLElement|null} [returnFocusEl]
     */
    function openCitation(citation, returnFocusEl) {
        var normalized = normalizeCitation(citation);
        var bodyEl = document.getElementById('acp-cite-body');
        if (!citeEl || !citeBackdropEl || !bodyEl || !normalized) {
            return;
        }
        if (pickerMode === 'gate') {
            return;
        }
        if (pickerMode !== null) {
            closePicker();
        }

        citeReturnFocusEl = returnFocusEl || null;

        var locator = normalized.locator || {};
        var citeTitleEl = document.getElementById('acp-cite-title');
        var displayNum = citationDisplayNumber(normalized.citation_id);
        if (citeTitleEl) {
            citeTitleEl.textContent = displayNum
                ? (strings.sourceLabel || 'Source') + ' ' + displayNum
                : strings.sourceLabel || 'Source';
        }

        renderCitationBody(bodyEl, normalized);
        if (!bodyEl.hasChildNodes() || bodyEl.textContent.trim() === '') {
            bodyEl.textContent =
                normalized.citation_id != null
                    ? (strings.sourceLabel || 'Source') +
                      ' ' +
                      String(normalized.citation_id)
                    : strings.streamFail || 'Source details unavailable.';
        }

        var url = locator.url == null ? '' : String(locator.url);
        if (citeOpenEl) {
            if (isAllowlistedHttpsUrl(url)) {
                citeOpenEl.setAttribute('href', url);
                citeOpenEl.classList.remove('d-none');
            } else {
                citeOpenEl.setAttribute('href', '#');
                citeOpenEl.classList.add('d-none');
            }
        }

        citeBackdropEl.classList.remove('d-none');
        citeEl.classList.remove('d-none');
        citeOpen = true;
        if (typeof citeEl.focus === 'function') {
            citeEl.focus();
        }
    }

    function closeCitation() {
        if (!citeEl || !citeBackdropEl) {
            citeOpen = false;
            citeReturnFocusEl = null;
            return;
        }
        citeOpen = false;
        citeBackdropEl.classList.add('d-none');
        citeEl.classList.add('d-none');
        var bodyEl = document.getElementById('acp-cite-body');
        if (bodyEl) {
            bodyEl.textContent = '';
        }
        if (citeOpenEl) {
            citeOpenEl.setAttribute('href', '#');
            citeOpenEl.classList.add('d-none');
        }
        var returnEl = citeReturnFocusEl;
        citeReturnFocusEl = null;
        if (returnEl && typeof returnEl.focus === 'function') {
            returnEl.focus();
        }
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
        closeCitation();
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
        // H11: citation dialog and picker are mutually exclusive.
        closeCitation();
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

    function formatPickerDob(dob) {
        if (dob == null || String(dob).trim() === '') {
            return '';
        }
        var formatted = formatDisplayDate(String(dob).trim());
        if (formatted === '') {
            return '';
        }
        return (strings.dobPrefix || 'DOB') + ' ' + formatted;
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

        var patientName = appt.name == null ? '' : String(appt.name);
        var startTime = appt.start_time == null ? '' : String(appt.start_time);
        var dobLine = formatPickerDob(appt.dob);
        var visitTitle = appt.title == null ? '' : String(appt.title).trim();

        if (isNextCard) {
            var meta = document.createElement('div');
            meta.className = 'ask-copilot-picker-card-meta';

            var badge = document.createElement('span');
            badge.className = 'ask-copilot-picker-badge';
            badge.textContent = strings.nextPatientBadge || 'Next up';
            meta.appendChild(badge);

            if (startTime !== '') {
                var timeSep = document.createElement('span');
                timeSep.className = 'ask-copilot-picker-card-meta-sep';
                timeSep.textContent = '·';
                meta.appendChild(timeSep);

                var time = document.createElement('span');
                time.className = 'ask-copilot-picker-time';
                time.textContent = startTime;
                meta.appendChild(time);
            }
            btn.appendChild(meta);

            var name = document.createElement('span');
            name.className = 'ask-copilot-picker-card-name';
            name.textContent = patientName;
            btn.appendChild(name);

            if (dobLine !== '') {
                var dob = document.createElement('span');
                dob.className = 'ask-copilot-picker-dob';
                dob.textContent = dobLine;
                btn.appendChild(dob);
            }

            if (visitTitle !== '') {
                var title = document.createElement('span');
                title.className = 'ask-copilot-picker-card-visit';
                title.textContent = visitTitle;
                btn.appendChild(title);
            }

            btn.setAttribute(
                'aria-label',
                (strings.selectNextPatient || 'Select next patient') +
                    (patientName ? ' ' + patientName : '') +
                    (startTime ? ' at ' + startTime : '')
            );
        } else {
            var time = document.createElement('span');
            time.className = 'ask-copilot-picker-time';
            time.textContent = startTime;
            btn.appendChild(time);

            var rowName = document.createElement('span');
            rowName.className = 'ask-copilot-picker-name';
            rowName.textContent = patientName;
            btn.appendChild(rowName);

            if (dobLine !== '') {
                var rowDob = document.createElement('span');
                rowDob.className = 'ask-copilot-picker-dob';
                rowDob.textContent = dobLine;
                btn.appendChild(rowDob);
            }
        }

        btn.addEventListener('click', function () {
            selectPatient(
                parseInt(appt.pid, 10),
                appt.name == null ? null : String(appt.name)
            );
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
            var nextHeading = document.createElement('div');
            nextHeading.className = 'ask-copilot-picker-next-heading';
            nextHeading.textContent = strings.nextPatientHeading || 'Next patient';
            pickerNextEl.appendChild(nextHeading);

            var nextMode =
                data && data.next_pid_mode != null
                    ? String(data.next_pid_mode)
                    : '';
            var nextHint = document.createElement('div');
            nextHint.className = 'ask-copilot-picker-next-hint text-muted';
            if (nextMode === 'first_today') {
                nextHint.textContent =
                    strings.nextPatientFallbackHint ||
                    'First on today\u2019s schedule \u2014 select to start';
            } else {
                nextHint.textContent =
                    strings.nextPatientHint || 'Up next in your schedule today';
            }
            pickerNextEl.appendChild(nextHint);

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
            cacheSchedulePatientNames(data);
            renderSchedule(data);
            triggerPrefetch();
        } catch (err) {
            renderScheduleError();
        }
    }

    /**
     * Kick background brief prefetch for today's schedule (fire-and-forget).
     * Never blocks the picker; errors are swallowed.
     */
    function triggerPrefetch() {
        if (!config.prefetchUrl || streaming) {
            return;
        }

        if (typeof top !== 'undefined' && typeof top.restoreSession === 'function') {
            top.restoreSession();
        }

        fetch(config.prefetchUrl, {
            method: 'POST',
            credentials: 'same-origin',
            headers: {
                Accept: 'application/json',
                'Content-Type': 'application/x-www-form-urlencoded'
            },
            body: 'csrf_token_form=' + encodeURIComponent(config.csrf || '')
        }).catch(function () {
            // Prefetch is best-effort; do not surface failures in the UI.
        });
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
     * Bind session pid via Ask Co-Pilot bind.php (no chart navigation).
     *
     * @param {number} pid
     * @returns {Promise<object>}
     */
    async function bindPatientSession(pid) {
        if (!config.bindUrl || !Number.isFinite(pid) || pid <= 0) {
            throw new Error('Ask Co-Pilot bind URL unavailable.');
        }

        if (typeof top !== 'undefined' && typeof top.restoreSession === 'function') {
            top.restoreSession();
        }

        var response = await fetch(config.bindUrl, {
            method: 'POST',
            credentials: 'same-origin',
            headers: {
                Accept: 'application/json',
                'Content-Type': 'application/x-www-form-urlencoded;charset=UTF-8'
            },
            body: new URLSearchParams({
                csrf_token_form: config.csrf || '',
                pid: String(pid)
            }).toString()
        });

        if (!response.ok) {
            throw new Error('Ask Co-Pilot bind returned HTTP ' + response.status + '.');
        }

        var data = await response.json();
        if (!data || parseInt(data.pid, 10) !== pid) {
            throw new Error('Ask Co-Pilot bind returned unexpected payload.');
        }

        return data;
    }

    /**
     * Sync the OpenEMR shell patient context without leaving Ask Co-Pilot.
     *
     * @param {number} pid
     * @param {string|null|undefined} displayName
     * @param {object|null|undefined} bindResult
     */
    function syncShellPatientContext(pid, displayName, bindResult) {
        if (typeof top === 'undefined') {
            return;
        }

        var payload = bindResult && typeof bindResult === 'object' ? bindResult : {};
        var name =
            displayName != null && String(displayName).trim() !== ''
                ? String(displayName).trim()
                : payload.name != null
                  ? String(payload.name)
                  : '';
        var pubpid =
            payload.pubpid != null && String(payload.pubpid) !== ''
                ? String(payload.pubpid)
                : String(pid);
        var dobStr =
            payload.dob_display != null ? String(payload.dob_display) : '';

        // left_nav.setPatient navigates to the Encounters tab for a new pid.
        // Only sync labels when the shell already has this patient selected.
        if (
            top.left_nav &&
            typeof top.left_nav.setPatient === 'function' &&
            top.app_view_model &&
            top.app_view_model.application_data
        ) {
            var currentPatient = top.app_view_model.application_data.patient();
            if (
                currentPatient !== null &&
                typeof currentPatient.pid === 'function' &&
                currentPatient.pid() === pid
            ) {
                try {
                    top.left_nav.setPatient(name, pid, pubpid, '', dobStr);
                } catch (err) {
                    // Non-fatal — session bind is authoritative for Co-Pilot.
                }
            }
        }

        if (typeof top.activateTabByName === 'function') {
            top.activateTabByName('acp', true);
        }
    }

    /**
     * Physician clicked a patient: bind session pid in place, then fast-poll
     * until the bind lands. Never binds silently — always reached via a click.
     *
     * @param {number} pid
     * @param {string|null|undefined} [displayName]
     * @returns {Promise<void>}
     */
    async function selectPatient(pid, displayName) {
        if (pickerBusy || !Number.isFinite(pid) || pid <= 0) {
            return;
        }

        if (!config.bindUrl) {
            openFinder();
            setPickerStatus(
                strings.useFinder || 'Select the patient from the search tab.'
            );
            return;
        }

        pickerBusy = true;
        setPickerActionsDisabled(true);
        setPickerStatus(strings.openingChart || 'Selecting patient...');

        if (typeof top !== 'undefined' && typeof top.restoreSession === 'function') {
            top.restoreSession();
        }

        var bindResult = null;
        try {
            bindResult = await bindPatientSession(pid);
        } catch (bindErr) {
            pickerBusy = false;
            setPickerActionsDisabled(false);
            if (pickerMode !== null) {
                setPickerStatus(
                    strings.bindTimeout ||
                        'Could not confirm the patient selection. Try again.'
                );
            }
            return;
        }

        syncShellPatientContext(pid, displayName, bindResult);

        var bound = await pollForPid(pid);
        if (bound) {
            if (pickerMode === 'change' && boundPid !== null && boundPid !== pid) {
                // Confirmed switch: clear the thread for the new patient.
                clearTranscript();
            }
            boundPid = pid;
            boundPatientName =
                bindResult && bindResult.name != null && String(bindResult.name).trim() !== ''
                    ? String(bindResult.name).trim()
                    : displayName != null && String(displayName).trim() !== ''
                      ? String(displayName).trim()
                      : schedulePatientNames[pid] || null;
            pickerBusy = false;
            closePicker();
            showGate(false, pid);
            await updatePatientLine(pid, boundPatientName);
            if (typeof top !== 'undefined' && typeof top.activateTabByName === 'function') {
                top.activateTabByName('acp', true);
            }
            var autoBrief =
                strings.autoBriefMessage || 'Brief me on this patient.';
            await sendMessage(autoBrief);
            triggerPrefetch();
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

    /** Light-touch focus trap for the citation dialog. */
    function trapCiteFocus(evt) {
        if (!citeOpen || evt.key !== 'Tab' || !citeEl) {
            return;
        }
        var focusable = citeEl.querySelectorAll(
            'button:not([disabled]), a[href]:not(.d-none)'
        );
        if (focusable.length === 0) {
            evt.preventDefault();
            return;
        }
        var first = focusable[0];
        var last = focusable[focusable.length - 1];
        var active = document.activeElement;
        if (evt.shiftKey && (active === first || active === citeEl)) {
            evt.preventDefault();
            last.focus();
        } else if (!evt.shiftKey && active === last) {
            evt.preventDefault();
            first.focus();
        }
    }

    /**
     * Dispatch a parsed SSE event to the matching handler.
     *
     * @param {string} evt
     * @param {object} data
     * @param {{onProgress?: Function, onClinical?: Function, onCitation?: Function, onDone?: Function, onError?: Function}} handlers
     */
    function dispatchSseEvent(evt, data, handlers) {
        data = data || {};
        if (evt === 'progress') {
            if (typeof handlers.onProgress === 'function') {
                handlers.onProgress(data.message || '');
            }
        } else if (evt === 'clinical') {
            if (typeof handlers.onClinical === 'function') {
                handlers.onClinical({
                    text: data.text || '',
                    segments: Array.isArray(data.segments) ? data.segments : []
                });
            }
        } else if (evt === 'citation') {
            if (typeof handlers.onCitation === 'function') {
                handlers.onCitation({
                    citations: Array.isArray(data.citations) ? data.citations : []
                });
            }
        } else if (evt === 'done') {
            if (typeof handlers.onDone === 'function') {
                handlers.onDone(data.correlation_id || '');
            }
        } else if (evt === 'error') {
            if (typeof handlers.onError === 'function') {
                handlers.onError(
                    data.message ||
                        (strings.streamFail || 'Something went wrong. Try again.'),
                    {
                        code: data.code || '',
                        correlation_id: data.correlation_id || '',
                        detail: data.detail || ''
                    }
                );
            }
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
     * @param {{onProgress?: Function, onClinical?: Function, onCitation?: Function, onDone?: Function, onError?: Function}} handlers
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
                dispatchSseEvent(parsed.event, parsed.data, handlers);
            }
        }

        // Flush trailing frame without final blank line
        var trailing = buffer.trim();
        if (trailing && trailing.charAt(0) !== ':') {
            var last = parseSseFrame(trailing);
            if (last) {
                dispatchSseEvent(last.event, last.data, handlers);
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
     * @param {string|null|undefined} [overrideMessage] When set, sends this text
     *   instead of the composer value (used after patient picker selection).
     * @returns {Promise<void>}
     */
    async function sendMessage(overrideMessage) {
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

        var message =
            overrideMessage != null && String(overrideMessage).trim() !== ''
                ? String(overrideMessage).trim()
                : inputEl
                  ? String(inputEl.value || '').trim()
                  : '';
        if (!message) {
            setProgress(strings.enterMessage || 'Enter a message.');
            return;
        }

        streaming = true;
        updateSendEnabled();
        setProgress('');
        appendBubble('user', message);
        showTypingIndicator();
        pushTranscript('user', message);
        if (inputEl && overrideMessage == null) {
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

        // Buffer clinical until citation arrives (or timeout / done) — PRD 06.
        /** @type {{text: string, segments: Array<object>}|null} */
        var pendingClinical = null;
        /** @type {Array<object>|null} null = not yet received */
        var pendingCitations = null;
        var clinicalRendered = false;
        var citationTimer = null;
        var citationTimeoutMs =
            Number(config.citationTimeoutMs) > 0
                ? Number(config.citationTimeoutMs)
                : 2500;

        function clearClinicalBuffer() {
            pendingClinical = null;
            pendingCitations = null;
            if (citationTimer !== null) {
                clearTimeout(citationTimer);
                citationTimer = null;
            }
        }

        function flushClinicalRender() {
            if (clinicalRendered || !pendingClinical) {
                return;
            }
            clinicalRendered = true;
            if (citationTimer !== null) {
                clearTimeout(citationTimer);
                citationTimer = null;
            }
            removeTypingIndicator();
            setProgress('');
            var text = pendingClinical.text || '';
            var segments = pendingClinical.segments;
            var hasCitationBatch = pendingCitations !== null;
            var map = hasCitationBatch
                ? citationMapFromList(pendingCitations)
                : null;

            if (
                hasCitationBatch &&
                Array.isArray(segments) &&
                segments.length > 0
            ) {
                if (map) {
                    registerCitations(pendingCitations);
                }
                renderAssistantTurn(segments, map);
            } else if (text) {
                appendBubble('assistant', text);
            } else if (Array.isArray(segments) && segments.length > 0) {
                renderAssistantTurn(segments, map || {});
            } else {
                appendBubble(
                    'assistant',
                    strings.streamFail || 'Something went wrong. Try again.'
                );
            }
            var transcriptText = text;
            if (
                (!transcriptText || String(transcriptText).trim() === '') &&
                Array.isArray(segments) &&
                segments.length > 0
            ) {
                var joined = [];
                for (var si = 0; si < segments.length; si++) {
                    if (segments[si] && segments[si].text) {
                        joined.push(String(segments[si].text));
                    }
                }
                transcriptText = joined.join('\n');
            }
            pushTranscript('assistant', transcriptText);
            pendingClinical = null;
            pendingCitations = null;
        }

        function tryRenderBuffered() {
            if (pendingClinical && pendingCitations !== null) {
                flushClinicalRender();
            }
        }

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
                onClinical: function (payload) {
                    pendingClinical = {
                        text: (payload && payload.text) || '',
                        segments:
                            payload && Array.isArray(payload.segments)
                                ? payload.segments
                                : []
                    };
                    if (citationTimer !== null) {
                        clearTimeout(citationTimer);
                    }
                    citationTimer = setTimeout(function () {
                        flushClinicalRender();
                    }, citationTimeoutMs);
                    tryRenderBuffered();
                },
                onCitation: function (data) {
                    pendingCitations =
                        data && Array.isArray(data.citations)
                            ? data.citations
                            : [];
                    registerCitations(pendingCitations);
                    tryRenderBuffered();
                },
                onDone: function () {
                    gotTerminal = true;
                    flushClinicalRender();
                    setProgress('');
                },
                onError: function (msg, meta) {
                    gotTerminal = true;
                    clinicalRendered = true;
                    clearClinicalBuffer();
                    removeTypingIndicator();
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

            // Stream ended without done/error but clinical may still be pending
            // (e.g. hung connection after clinical) — flush plain if needed.
            flushClinicalRender();

            if (!gotTerminal && !clinicalRendered) {
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
            } else if (!gotTerminal && clinicalRendered) {
                // Clinical painted via timeout; stream never sent done — still OK.
                setProgress('');
            }
            if (patientSwitch) {
                // Drop the user turn that was rejected after patient switch.
                transcript = [];
            }
        } catch (err) {
            clinicalRendered = true;
            clearClinicalBuffer();
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
            removeTypingIndicator();
            streaming = false;
            updateSendEnabled();
            await refreshPatientState();
        }
    }

    function bindUi() {
        if (messagesEl) {
            messagesEl.addEventListener('click', function (evt) {
                var target = evt.target;
                if (!target || typeof target.closest !== 'function') {
                    return;
                }
                var srcBtn = target.closest('.ask-copilot-cite-ref, .ask-copilot-source');
                if (!srcBtn || !messagesEl.contains(srcBtn)) {
                    return;
                }
                var citeId = srcBtn.getAttribute('data-cite-id');
                var citation = lookupCitation(citeId);
                if (citation) {
                    openCitation(citation, srcBtn);
                }
            });
        }
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
        if (citeCloseBtn) {
            citeCloseBtn.addEventListener('click', function () {
                closeCitation();
            });
        }
        if (citeBackdropEl) {
            citeBackdropEl.addEventListener('click', function () {
                closeCitation();
            });
        }
        document.addEventListener('keydown', function (evt) {
            if (evt.key === 'Escape' && citeOpen) {
                closeCitation();
                return;
            }
            if (evt.key === 'Escape' && pickerMode === 'change' && !pickerBusy) {
                closePicker();
                return;
            }
            trapCiteFocus(evt);
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
        triggerPrefetch: triggerPrefetch,
        bindPatientSession: bindPatientSession,
        syncShellPatientContext: syncShellPatientContext,
        selectPatient: selectPatient,
        pushTranscript: pushTranscript,
        isAllowlistedHttpsUrl: isAllowlistedHttpsUrl,
        normalizeCitation: normalizeCitation,
        registerCitations: registerCitations,
        lookupCitation: lookupCitation,
        renderAssistantTurn: renderAssistantTurn,
        renderCitationBody: renderCitationBody,
        formatCitationPlainText: formatCitationPlainText,
        formatDisplayDate: formatDisplayDate,
        formatPickerDob: formatPickerDob,
        humanizeIsoDatesInText: humanizeIsoDatesInText,
        citationDisplayNumber: citationDisplayNumber,
        showTypingIndicator: showTypingIndicator,
        removeTypingIndicator: removeTypingIndicator,
        updatePatientLine: updatePatientLine,
        openCitation: openCitation,
        openSourceByElement: function (btn) {
            if (!btn) {
                return;
            }
            var citeId = btn.getAttribute('data-cite-id');
            var payload = lookupCitation(citeId);
            if (!payload) {
                var raw = btn.getAttribute('data-citation-json');
                if (raw) {
                    try {
                        payload = normalizeCitation(JSON.parse(raw));
                    } catch (parseErr) {
                        payload = null;
                    }
                }
            }
            if (payload) {
                openCitation(payload, btn);
            }
        },
        closeCitation: closeCitation,
        getState: function () {
            return {
                boundPid: boundPid,
                pickerMode: pickerMode,
                pickerBusy: pickerBusy,
                streaming: streaming,
                transcriptLength: transcript.length,
                citeOpen: citeOpen
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
