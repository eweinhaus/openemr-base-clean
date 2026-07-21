<?php

/**
 * Ask Co-Pilot session-proxy SSE gateway.
 *
 * Validates session + CSRF, binds pid from session only, mints a correlation id,
 * records a disclosure stub line, and proxies hybrid SSE from the internal sidecar.
 *
 * POST body: csrf_token_form, message, optional transcript (JSON), optional bound_pid
 * Response: text/event-stream (progress → clinical → done / error)
 *
 * @package   OpenEMR
 * @link      https://www.open-emr.org
 * @author    eweinhaus <eweinhaus@users.noreply.github.com>
 * @copyright Copyright (c) 2026 eweinhaus
 * @license   https://github.com/openemr/openemr/blob/master/LICENSE GNU General Public License 3
 */

require_once("../globals.php");

use OpenEMR\ClinicalCopilot\Gateway\FileCorrelationBindStore;
use OpenEMR\ClinicalCopilot\Gateway\SessionGateway;
use OpenEMR\ClinicalCopilot\Gateway\SidecarClient;
use OpenEMR\ClinicalCopilot\Logging\DisclosureLog;
use OpenEMR\ClinicalCopilot\Sse\SseEvent;
use OpenEMR\Common\Csrf\CsrfUtils;
use OpenEMR\Common\Session\SessionWrapperFactory;
use OpenEMR\Core\OEGlobalsBag;
use Throwable;

const ASK_COPILOT_MESSAGE_MAX_LENGTH = 4000;
const ASK_COPILOT_TRANSCRIPT_MAX_ENTRIES = 20;

$session = SessionWrapperFactory::getInstance()->getActiveSession();

CsrfUtils::checkCsrfInput(INPUT_POST, dieOnFail: true);

$authUserId = $session->get('authUserID');
$authUser = $session->get('authUser');
$sessionPid = $session->get('pid');
// Client-supplied pid is intentionally ignored for binding (fail-closed).
$ignoredClientPid = filter_input(INPUT_POST, 'pid', FILTER_UNSAFE_RAW, FILTER_REQUIRE_SCALAR);

try {
    $context = SessionGateway::fromSessionValues(
        $authUserId,
        $authUser,
        $sessionPid,
        is_string($ignoredClientPid) ? $ignoredClientPid : null,
    );
} catch (Throwable) {
    header('Content-Type: text/event-stream; charset=utf-8');
    header('Cache-Control: no-cache');
    echo SseEvent::format('error', ['message' => 'Unable to process request.']);
    exit;
}

// Release the session lock so the rest of the UI stays responsive while we stream.
session_write_close();

header('Content-Type: text/event-stream; charset=utf-8');
header('Cache-Control: no-cache');
header('X-Accel-Buffering: no');
header('Connection: keep-alive');
@ini_set('output_buffering', 'off');
@ini_set('zlib.output_compression', '0');
while (ob_get_level() > 0) {
    ob_end_flush();
}
flush();

/**
 * Emit one SSE frame and flush.
 *
 * @param array<string, mixed> $data
 */
$emit = static function (string $event, array $data): void {
    echo SseEvent::format($event, $data);
    if (function_exists('ob_flush')) {
        @ob_flush();
    }
    flush();
};

$rawMessage = filter_input(INPUT_POST, 'message', FILTER_UNSAFE_RAW, FILTER_REQUIRE_SCALAR);
$message = is_string($rawMessage) ? trim($rawMessage) : '';

if ($message === '' || strlen($message) > ASK_COPILOT_MESSAGE_MAX_LENGTH) {
    $emit('error', ['message' => 'Unable to process request.']);
    exit;
}

if (!$context->isBound() || $context->pid === null) {
    $emit('error', ['message' => 'Select a patient before chatting.']);
    exit;
}

$rawBoundPid = filter_input(INPUT_POST, 'bound_pid', FILTER_UNSAFE_RAW, FILTER_REQUIRE_SCALAR);
if (is_string($rawBoundPid) && trim($rawBoundPid) !== '') {
    $clientBoundPid = (int) trim($rawBoundPid);
    if ($clientBoundPid > 0 && $clientBoundPid !== $context->pid) {
        $emit('error', ['message' => 'Patient changed. Clear the chat and try again.']);
        exit;
    }
}

$transcript = [];
$rawTranscript = filter_input(INPUT_POST, 'transcript', FILTER_UNSAFE_RAW, FILTER_REQUIRE_SCALAR);
if (is_string($rawTranscript) && $rawTranscript !== '') {
    try {
        $decoded = json_decode($rawTranscript, true, 512, JSON_THROW_ON_ERROR);
        if (is_array($decoded)) {
            $transcript = array_slice(array_values($decoded), -ASK_COPILOT_TRANSCRIPT_MAX_ENTRIES);
        }
    } catch (Throwable) {
        $transcript = [];
    }
}

$globalsBag = OEGlobalsBag::getInstance();
$siteDir = $globalsBag->getString('OE_SITE_DIR');
$bindDir = $siteDir . '/documents/copilot_binds';
$disclosurePath = $siteDir . '/documents/copilot_disclosure.log';

$secret = getenv('COPILOT_INTERNAL_SECRET');
$sidecarUrl = getenv('COPILOT_SIDECAR_URL');
$timeoutRaw = getenv('COPILOT_GATEWAY_TIMEOUT_SECONDS');
$timeoutSeconds = is_numeric($timeoutRaw) ? (float) $timeoutRaw : 45.0;

if (!is_string($secret) || $secret === '' || !is_string($sidecarUrl) || $sidecarUrl === '') {
    error_log('Ask Co-Pilot gateway misconfigured: missing COPILOT_INTERNAL_SECRET or COPILOT_SIDECAR_URL');
    $emit('error', ['message' => 'Something went wrong. Try again.']);
    exit;
}

if (!is_dir($bindDir) && !mkdir($bindDir, 0775, true) && !is_dir($bindDir)) {
    error_log('Ask Co-Pilot gateway failed to create bind directory');
    $emit('error', ['message' => 'Something went wrong. Try again.']);
    exit;
}

try {
    $bindStore = new FileCorrelationBindStore($bindDir);
    $bindStore->put($context->correlationId, $context->pid, $context->userId);

    $disclosureLog = new DisclosureLog($disclosurePath);
    $disclosureLog->write([
        'event' => 'ask_start',
        'correlation_id' => $context->correlationId,
        'user_id' => $context->userId,
        'pid' => $context->pid,
    ]);

    $client = new SidecarClient($sidecarUrl, $secret, $timeoutSeconds);
    $client->streamChat([
        'correlation_id' => $context->correlationId,
        'user_id' => $context->userId,
        'username' => $context->username,
        'pid' => $context->pid,
        'message' => $message,
        'transcript' => $transcript,
    ]);
} catch (Throwable $e) {
    error_log('Ask Co-Pilot stream error: ' . $e->getMessage());
    try {
        $disclosureLog = new DisclosureLog($disclosurePath);
        $disclosureLog->write([
            'event' => 'ask_error',
            'correlation_id' => $context->correlationId,
            'user_id' => $context->userId,
            'pid' => $context->pid,
            'reason' => 'sidecar_error',
        ]);
    } catch (Throwable) {
        // ignore secondary log failures
    }
    $emit('error', ['message' => 'Something went wrong. Try again.']);
}
