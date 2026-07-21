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

use OpenEMR\ClinicalCopilot\Gateway\CopilotStreamError;
use OpenEMR\ClinicalCopilot\Gateway\FileCorrelationBindStore;
use OpenEMR\ClinicalCopilot\Gateway\SessionGateway;
use OpenEMR\ClinicalCopilot\Gateway\SidecarClient;
use OpenEMR\ClinicalCopilot\Gateway\TranscriptSanitizer;
use OpenEMR\ClinicalCopilot\Logging\DisclosureLog;
use OpenEMR\ClinicalCopilot\Sse\SseEvent;
use OpenEMR\Common\Acl\AclMain;
use OpenEMR\Common\Csrf\CsrfUtils;
use OpenEMR\Common\Session\SessionWrapperFactory;
use OpenEMR\Core\OEGlobalsBag;

const ASK_COPILOT_MESSAGE_MAX_LENGTH = 4000;
const ASK_COPILOT_WEAK_SECRET = 'dev-copilot-secret-change-me';

$session = SessionWrapperFactory::getInstance()->getActiveSession();

CsrfUtils::checkCsrfInput(INPUT_POST, dieOnFail: true);

if (!AclMain::aclCheckCore('patients', 'demo')) {
    header('Content-Type: text/event-stream; charset=utf-8');
    header('Cache-Control: no-cache');
    echo SseEvent::format('error', CopilotStreamError::payload('access_denied'));
    exit;
}

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
    echo SseEvent::format('error', CopilotStreamError::payload('invalid_request'));
    exit;
}

// Release the session lock so the rest of the UI stays responsive while we stream.
session_write_close();

// Streaming turns can exceed max_execution_time (route + draft LLM calls);
// lift the script limit — the sidecar/gateway timeouts bound the turn instead.
@set_time_limit(0);

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

if ($message === '' || mb_strlen($message, 'UTF-8') > ASK_COPILOT_MESSAGE_MAX_LENGTH) {
    $emit('error', CopilotStreamError::payload('invalid_request', $context->correlationId));
    exit;
}

if (!$context->isBound() || $context->pid === null) {
    $emit('error', CopilotStreamError::payload('unbound_patient', $context->correlationId));
    exit;
}

// Fail closed on a broken session with no usable user id — the tool proxy
// would reject the bind anyway (user_id must be > 0), so refuse up front.
if ($context->userId <= 0) {
    $emit('error', CopilotStreamError::payload('invalid_request', $context->correlationId));
    exit;
}

$rawBoundPid = filter_input(INPUT_POST, 'bound_pid', FILTER_UNSAFE_RAW, FILTER_REQUIRE_SCALAR);
if (is_string($rawBoundPid) && trim($rawBoundPid) !== '') {
    $clientBoundPid = (int) trim($rawBoundPid);
    if ($clientBoundPid > 0 && $clientBoundPid !== $context->pid) {
        $emit('error', CopilotStreamError::payload('patient_changed', $context->correlationId));
        exit;
    }
}

$transcript = [];
$rawTranscript = filter_input(INPUT_POST, 'transcript', FILTER_UNSAFE_RAW, FILTER_REQUIRE_SCALAR);
if (is_string($rawTranscript) && $rawTranscript !== '') {
    try {
        $decoded = json_decode($rawTranscript, true, 512, JSON_THROW_ON_ERROR);
        if (is_array($decoded)) {
            $transcript = TranscriptSanitizer::sanitize(array_values($decoded));
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
// Default must cover route + draft LLM calls (up to COPILOT_LLM_TIMEOUT_SECONDS each)
// plus tool round-trips, so a slow-but-successful turn is not aborted mid-stream.
$timeoutRaw = getenv('COPILOT_GATEWAY_TIMEOUT_SECONDS');
$timeoutSeconds = is_numeric($timeoutRaw) ? (float) $timeoutRaw : 120.0;

if (!is_string($secret) || $secret === '' || !is_string($sidecarUrl) || $sidecarUrl === '') {
    error_log('Ask Co-Pilot gateway misconfigured: missing COPILOT_INTERNAL_SECRET or COPILOT_SIDECAR_URL');
    $emit('error', CopilotStreamError::payload('gateway_misconfigured', $context->correlationId));
    exit;
}

if ($secret === ASK_COPILOT_WEAK_SECRET) {
    error_log('Ask Co-Pilot: COPILOT_INTERNAL_SECRET is still the weak default; rotate before public demo');
}

if (!is_dir($bindDir) && !mkdir($bindDir, 0775, true) && !is_dir($bindDir)) {
    error_log('Ask Co-Pilot gateway failed to create bind directory');
    $emit('error', CopilotStreamError::payload('gateway_bind_store', $context->correlationId));
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
    $code = CopilotStreamError::codeFromThrowable($e);
    error_log('Ask Co-Pilot stream error [' . $code . ']: ' . $e->getMessage());
    try {
        $disclosureLog = new DisclosureLog($disclosurePath);
        $disclosureLog->write([
            'event' => 'ask_error',
            'correlation_id' => $context->correlationId,
            'user_id' => $context->userId,
            'pid' => $context->pid,
            'reason' => $code,
        ]);
    } catch (Throwable) {
        // ignore secondary log failures
    }
    $emit('error', CopilotStreamError::payload($code, $context->correlationId));
}
