<?php

/**
 * Ask Co-Pilot chat chrome (iframe tab).
 *
 * Empty transcript on load; patient gate via Finder; streams replies from
 * session-proxy SSE at stream.php. XSS-safe client rendering.
 *
 * @package   OpenEMR
 * @link      https://www.open-emr.org
 * @license   https://github.com/openemr/openemr/blob/master/LICENSE GNU General Public License 3
 */

require_once("../globals.php");

use OpenEMR\Common\Csrf\CsrfUtils;
use OpenEMR\Common\Session\SessionWrapperFactory;
use OpenEMR\Core\Header;
use OpenEMR\Core\OEGlobalsBag;

$session = SessionWrapperFactory::getInstance()->getActiveSession();
$globalsBag = OEGlobalsBag::getInstance();
$webroot = $globalsBag->getWebRoot();
$assetVersion = $globalsBag->getString('v_js_includes');
$csrfToken = CsrfUtils::collectCsrfToken($session);
$streamUrl = $webroot . '/interface/ask_copilot/stream.php';
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
            <h2 class="ask-copilot-title"><?php echo xlt('Ask Co-Pilot'); ?></h2>
            <div id="acp-patient-line" class="ask-copilot-patient-line text-muted" aria-live="polite"></div>
        </header>

        <div id="acp-gate" class="alert alert-warning ask-copilot-gate d-none" role="alert">
            <span id="acp-gate-message"><?php echo text(xl('Select a patient before chatting.')); ?></span>
            <button type="button" id="acp-open-finder" class="btn btn-sm btn-primary ml-2">
                <?php echo xlt('Select patient'); ?>
            </button>
        </div>

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

    <script>
        window.askCopilotConfig = {
            webroot: <?php echo js_escape($webroot); ?>,
            csrf: <?php echo js_escape($csrfToken); ?>,
            streamUrl: <?php echo js_escape($streamUrl); ?>,
            sessionPid: <?php echo $sessionPid > 0 ? (int) $sessionPid : 'null'; ?>,
            strings: {
                selectPatient: <?php echo xlj('Select a patient before chatting.'); ?>,
                enterMessage: <?php echo xlj('Enter a message.'); ?>,
                streamFail: <?php echo xlj('Something went wrong. Try again.'); ?>,
                patientChanged: <?php echo xlj('Patient changed. Clear the chat and try again.'); ?>,
                patientPrefix: <?php echo xlj('Patient'); ?>
            }
        };
    </script>
    <script src="<?php echo attr($webroot); ?>/interface/ask_copilot/assets/ask_copilot.js?v=<?php echo attr($assetBust); ?>"></script>
</body>
</html>
