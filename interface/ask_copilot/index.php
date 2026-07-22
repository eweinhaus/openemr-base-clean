<?php

/**
 * Ask Co-Pilot chat chrome (iframe tab).
 *
 * Empty transcript on load; unbound patients get a blocking schedule picker
 * popup (today's appointments + Finder fallback). Streams replies from
 * session-proxy SSE at stream.php. XSS-safe client rendering.
 *
 * @package   OpenEMR
 * @link      https://www.open-emr.org
 * @license   https://github.com/openemr/openemr/blob/master/LICENSE GNU General Public License 3
 */

require_once("../globals.php");

use OpenEMR\Common\Acl\AccessDeniedHelper;
use OpenEMR\Common\Acl\AclMain;
use OpenEMR\Common\Csrf\CsrfUtils;
use OpenEMR\Common\Session\SessionWrapperFactory;
use OpenEMR\Core\Header;
use OpenEMR\Core\OEGlobalsBag;

$session = SessionWrapperFactory::getInstance()->getActiveSession();

if (!AclMain::aclCheckCore('patients', 'demo')) {
    AccessDeniedHelper::deny('Ask Co-Pilot access not authorized');
}

$globalsBag = OEGlobalsBag::getInstance();
$webroot = $globalsBag->getWebRoot();
$assetVersion = $globalsBag->getString('v_js_includes');
$csrfToken = CsrfUtils::collectCsrfToken($session);
$streamUrl = $webroot . '/interface/ask_copilot/stream.php';
$scheduleUrl = $webroot . '/interface/ask_copilot/schedule.php';
// Session pid for gate fallback when this page is top-level (not under main.php iframe).
$sessionPidRaw = $session->get('pid');
$sessionPid = is_numeric($sessionPidRaw) ? (int) $sessionPidRaw : 0;
$assetDir = __DIR__ . '/assets';
$assetBust = $assetVersion . '.' . (string) (@filemtime($assetDir . '/ask_copilot.js') ?: 0);
?>
<!DOCTYPE html>
<html>
<head>
    <title><?php echo xlt('Ask Co-Pilot'); ?></title>
    <?php Header::setupHeader(); ?>
    <link rel="stylesheet" href="<?php echo attr($webroot); ?>/interface/ask_copilot/assets/ask_copilot.css?v=<?php echo attr($assetBust); ?>">
</head>
<body class="body_top">
    <div class="container-fluid ask-copilot" id="ask-copilot-app">
        <header class="ask-copilot-header">
            <div class="ask-copilot-header-row">
                <h2 class="ask-copilot-title"><?php echo xlt('Ask Co-Pilot'); ?></h2>
                <button type="button" id="acp-change-patient" class="btn btn-link btn-sm ask-copilot-change-patient d-none">
                    <?php echo xlt('Change patient'); ?>
                </button>
            </div>
            <div id="acp-patient-line" class="ask-copilot-patient-line text-muted" aria-live="polite"></div>
        </header>

        <div id="acp-messages" class="ask-copilot-messages" aria-live="polite"></div>

        <div id="acp-progress" class="ask-copilot-progress text-muted small" aria-live="polite"></div>

        <div class="ask-copilot-composer">
            <label class="sr-only" for="acp-input"><?php echo xlt('Message'); ?></label>
            <textarea
                id="acp-input"
                class="form-control"
                rows="3"
                placeholder="<?php echo attr(xl('Message')); ?>"
            ></textarea>
            <button type="button" id="acp-send" class="btn btn-primary" disabled>
                <?php echo xlt('Send'); ?>
            </button>
        </div>
    </div>

    <div id="acp-picker-backdrop" class="ask-copilot-picker-backdrop d-none"></div>
    <div
        id="acp-picker"
        class="ask-copilot-picker d-none"
        role="dialog"
        aria-modal="true"
        aria-labelledby="acp-picker-title"
        tabindex="-1"
    >
        <h3 id="acp-picker-title" class="ask-copilot-picker-title"><?php echo xlt('Select a patient'); ?></h3>
        <div id="acp-picker-status" class="ask-copilot-picker-status text-muted" aria-live="polite"></div>
        <div id="acp-picker-next" class="ask-copilot-picker-next"></div>
        <div id="acp-picker-list" class="ask-copilot-picker-list"></div>
        <div class="ask-copilot-picker-footer">
            <button type="button" id="acp-picker-search" class="btn btn-outline-secondary btn-sm">
                <?php echo xlt('Search all patients'); ?>
            </button>
            <button type="button" id="acp-picker-cancel" class="btn btn-link btn-sm d-none">
                <?php echo xlt('Cancel'); ?>
            </button>
        </div>
    </div>

    <div id="acp-cite-backdrop" class="ask-copilot-cite-backdrop d-none"></div>
    <div
        id="acp-cite"
        class="ask-copilot-cite d-none"
        role="dialog"
        aria-modal="true"
        aria-labelledby="acp-cite-title"
        tabindex="-1"
    >
        <h3 id="acp-cite-title" class="ask-copilot-cite-title"><?php echo xlt('Source'); ?></h3>
        <div id="acp-cite-body" class="ask-copilot-cite-body"></div>
        <div class="ask-copilot-cite-footer">
            <a
                id="acp-cite-open"
                class="btn btn-link btn-sm d-none"
                target="_blank"
                rel="noopener noreferrer"
                href="#"
            ><?php echo xlt('Open label'); ?></a>
            <button type="button" id="acp-cite-close" class="btn btn-secondary btn-sm">
                <?php echo xlt('Close'); ?>
            </button>
        </div>
    </div>

    <script>
        window.askCopilotConfig = {
            webroot: <?php echo js_escape($webroot); ?>,
            csrf: <?php echo js_escape($csrfToken); ?>,
            streamUrl: <?php echo js_escape($streamUrl); ?>,
            scheduleUrl: <?php echo js_escape($scheduleUrl); ?>,
            sessionPid: <?php echo $sessionPid > 0 ? (int) $sessionPid : 'null'; ?>,
            strings: {
                selectPatient: <?php echo xlj('Select a patient before chatting.'); ?>,
                enterMessage: <?php echo xlj('Enter a message.'); ?>,
                streamFail: <?php echo xlj('Something went wrong. Try again.'); ?>,
                streamIncomplete: <?php echo xlj('Stream ended before a reply finished. Try again.'); ?>,
                patientChanged: <?php echo xlj('Patient changed. Clear the chat and try again.'); ?>,
                patientPrefix: <?php echo xlj('Patient'); ?>,
                nextPatient: <?php echo xlj('Next'); ?>,
                appointmentsToday: <?php echo xlj('Appointments today'); ?>,
                scheduleLoading: <?php echo xlj('Loading schedule...'); ?>,
                scheduleEmpty: <?php echo xlj('No appointments today. Use Search all patients.'); ?>,
                scheduleError: <?php echo xlj('Could not load the schedule.'); ?>,
                retry: <?php echo xlj('Retry'); ?>,
                openingChart: <?php echo xlj('Opening chart...'); ?>,
                bindTimeout: <?php echo xlj('Could not confirm the patient selection. Try again.'); ?>,
                useFinder: <?php echo xlj('Select the patient from the search tab.'); ?>,
                confirmSwitch: <?php echo xlj('Switching patients clears this chat. Continue?'); ?>,
                dobPrefix: <?php echo xlj('DOB'); ?>,
                sourceLabel: <?php echo xlj('Source'); ?>,
                openLabel: <?php echo xlj('Open label'); ?>,
                citeClose: <?php echo xlj('Close'); ?>,
                chartLocator: <?php echo xlj('Chart locator:'); ?>,
                researchLocator: <?php echo xlj('Research locator:'); ?>
            }
        };
    </script>
    <script src="<?php echo attr($webroot); ?>/interface/ask_copilot/assets/ask_copilot.js?v=<?php echo attr($assetBust); ?>"></script>
</body>
</html>
