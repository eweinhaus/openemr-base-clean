<?php

/**
 * Ask Co-Pilot brief prefetch kick (JSON).
 *
 * POST (session cookie + CSRF). Server computes top-three schedule pids only —
 * never accepts a client pid list.
 *
 * Response: 202 JSON { "queued": [pid...], "skipped"?: "reason?" }
 *
 * @package   OpenEMR
 * @link      https://www.open-emr.org
 * @author    eweinhaus <eweinhaus@users.noreply.github.com>
 * @copyright Copyright (c) 2026 eweinhaus
 * @license   https://github.com/openemr/openemr/blob/master/LICENSE GNU General Public License 3
 */

declare(strict_types=1);

require_once("../globals.php");

use OpenEMR\ClinicalCopilot\Gateway\FileCorrelationBindStore;
use OpenEMR\ClinicalCopilot\Gateway\PrefetchBriefService;
use OpenEMR\ClinicalCopilot\Gateway\SidecarClient;
use OpenEMR\ClinicalCopilot\Schedule\ProviderDayScheduleService;
use OpenEMR\Common\Acl\AccessDeniedHelper;
use OpenEMR\Common\Acl\AccessDeniedResponseFormat;
use OpenEMR\Common\Acl\AclMain;
use OpenEMR\Common\Csrf\CsrfUtils;
use OpenEMR\Common\Session\SessionWrapperFactory;
use OpenEMR\Core\OEGlobalsBag;

const ASK_COPILOT_WEAK_SECRET = 'dev-copilot-secret-change-me';

header('Content-Type: application/json; charset=utf-8');
header('Cache-Control: no-store');

if ($_SERVER['REQUEST_METHOD'] !== 'POST') {
    http_response_code(405);
    echo json_encode(['error' => 'Unable to process request.'], JSON_THROW_ON_ERROR);
    exit;
}

$session = SessionWrapperFactory::getInstance()->getActiveSession();

if (!AclMain::aclCheckCore('patients', 'demo')) {
    AccessDeniedHelper::deny(
        'Ask Co-Pilot prefetch access not authorized',
        format: AccessDeniedResponseFormat::Json,
    );
}

try {
    CsrfUtils::checkCsrfInput(INPUT_POST, session: $session, dieOnFail: false);
} catch (Throwable) {
    http_response_code(403);
    echo json_encode(['error' => 'Unable to process request.'], JSON_THROW_ON_ERROR);
    exit;
}

$authUserIdRaw = $session->get('authUserID');
if (!is_numeric($authUserIdRaw) || (int) $authUserIdRaw <= 0) {
    http_response_code(403);
    echo json_encode(['error' => 'Unable to process request.'], JSON_THROW_ON_ERROR);
    exit;
}

$authUserId = (int) $authUserIdRaw;
$authUser = $session->get('authUser');
$username = is_string($authUser) ? trim($authUser) : '';
if ($username === '') {
    http_response_code(403);
    echo json_encode(['error' => 'Unable to process request.'], JSON_THROW_ON_ERROR);
    exit;
}

// Intentionally ignore any client-supplied pid list (fail closed).
unset($_POST['pid'], $_POST['pids'], $_REQUEST['pid'], $_REQUEST['pids']);

session_write_close();

$secret = getenv('COPILOT_INTERNAL_SECRET');
$sidecarUrl = getenv('COPILOT_SIDECAR_URL');

if (!is_string($secret) || $secret === '' || !is_string($sidecarUrl) || $sidecarUrl === '') {
    error_log('Ask Co-Pilot prefetch misconfigured: missing COPILOT_INTERNAL_SECRET or COPILOT_SIDECAR_URL');
    http_response_code(503);
    echo json_encode([
        'queued' => [],
        'skipped' => 'gateway_misconfigured',
    ], JSON_THROW_ON_ERROR);
    exit;
}

if ($secret === ASK_COPILOT_WEAK_SECRET) {
    error_log('Ask Co-Pilot: COPILOT_INTERNAL_SECRET is still the weak default; rotate before public demo');
}

$globalsBag = OEGlobalsBag::getInstance();
$siteDir = $globalsBag->getString('OE_SITE_DIR');
$bindDir = $siteDir . '/documents/copilot_binds';

if (!is_dir($bindDir) && !mkdir($bindDir, 0775, true) && !is_dir($bindDir)) {
    error_log('Ask Co-Pilot prefetch failed to create bind directory');
    http_response_code(500);
    echo json_encode(['error' => 'Unable to process request.'], JSON_THROW_ON_ERROR);
    exit;
}

try {
    $bindStore = new FileCorrelationBindStore($bindDir);
    $sidecarClient = new SidecarClient($sidecarUrl, $secret, 5.0);
    $scheduleService = new ProviderDayScheduleService();
    $service = new PrefetchBriefService($scheduleService, $bindStore, $sidecarClient);
    $result = $service->queueTodayTopThree($authUserId, $username);

    http_response_code(202);
    echo json_encode($result, JSON_THROW_ON_ERROR);
} catch (Throwable $e) {
    error_log('Ask Co-Pilot prefetch error: ' . $e->getMessage());
    http_response_code(500);
    echo json_encode(['error' => 'Unable to process request.'], JSON_THROW_ON_ERROR);
}
