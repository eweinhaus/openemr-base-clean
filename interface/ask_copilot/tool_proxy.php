<?php

/**
 * Internal chart-tool proxy for the Co-Pilot sidecar (no browser CSRF).
 *
 * Auth: X-Copilot-Internal-Secret. Pid fail-closed via correlation bind store.
 *
 * @package   OpenEMR
 * @link      https://www.open-emr.org
 * @author    eweinhaus <eweinhaus@users.noreply.github.com>
 * @copyright Copyright (c) 2026 eweinhaus
 * @license   https://github.com/openemr/openemr/blob/master/LICENSE GNU General Public License 3
 */

// Sidecar has no OpenEMR browser session — skip interactive auth.
$ignoreAuth = true;
if (empty($_GET['site'])) {
    $_GET['site'] = 'default';
}

require_once("../globals.php");

use OpenEMR\ClinicalCopilot\Chart\ChartToolDispatcher;
use OpenEMR\ClinicalCopilot\Chart\LabsChartService;
use OpenEMR\ClinicalCopilot\Chart\MedsChartService;
use OpenEMR\ClinicalCopilot\Chart\NotesChartService;
use OpenEMR\ClinicalCopilot\Chart\PatientContextService;
use OpenEMR\ClinicalCopilot\Gateway\FileCorrelationBindStore;
use OpenEMR\ClinicalCopilot\Gateway\ToolProxyService;
use OpenEMR\ClinicalCopilot\Logging\DisclosureLog;
use OpenEMR\Core\OEGlobalsBag;

header('Content-Type: application/json; charset=utf-8');
header('Cache-Control: no-store');

$secret = getenv('COPILOT_INTERNAL_SECRET');
if (!is_string($secret) || $secret === '') {
    http_response_code(500);
    echo json_encode(['ok' => false, 'error' => 'misconfigured'], JSON_THROW_ON_ERROR);
    exit;
}

$providedSecret = $_SERVER['HTTP_X_COPILOT_INTERNAL_SECRET'] ?? '';
$correlationId = $_SERVER['HTTP_X_CORRELATION_ID'] ?? '';
if (!is_string($providedSecret)) {
    $providedSecret = '';
}
if (!is_string($correlationId)) {
    $correlationId = '';
}

$raw = file_get_contents('php://input');
$body = [];
if (is_string($raw) && $raw !== '') {
    try {
        $decoded = json_decode($raw, true, 512, JSON_THROW_ON_ERROR);
        if (is_array($decoded)) {
            $body = $decoded;
        }
    } catch (Throwable) {
        http_response_code(400);
        echo json_encode(['ok' => false, 'error' => 'invalid_json'], JSON_THROW_ON_ERROR);
        exit;
    }
}

$globalsBag = OEGlobalsBag::getInstance();
$siteDir = $globalsBag->getString('OE_SITE_DIR');
$bindDir = $siteDir . '/documents/copilot_binds';
$disclosurePath = $siteDir . '/documents/copilot_disclosure.log';

if (!is_dir($bindDir) && !mkdir($bindDir, 0775, true) && !is_dir($bindDir)) {
    http_response_code(500);
    echo json_encode(['ok' => false, 'error' => 'bind_store_unavailable'], JSON_THROW_ON_ERROR);
    exit;
}

try {
    $bindStore = new FileCorrelationBindStore($bindDir);
    $disclosureLog = new DisclosureLog($disclosurePath);
    $chartDispatcher = new ChartToolDispatcher(
        new PatientContextService(),
        new LabsChartService(),
        new MedsChartService(),
        new NotesChartService(),
    );
    $service = new ToolProxyService($bindStore, $secret, $disclosureLog, $chartDispatcher);
    $result = $service->handle($body, $providedSecret, $correlationId);
} catch (Throwable $e) {
    error_log('Ask Co-Pilot tool_proxy error: ' . $e->getMessage());
    http_response_code(500);
    echo json_encode(['ok' => false, 'error' => 'server_error'], JSON_THROW_ON_ERROR);
    exit;
}

$error = $result['error'] ?? null;
if (($result['ok'] ?? false) !== true) {
    $status = match ($error) {
        'unauthorized' => 401,
        'bind_missing', 'pid_mismatch', 'user_mismatch' => 403,
        'invalid_request', 'not_implemented' => 400,
        default => 400,
    };
    http_response_code($status);
}

echo json_encode($result, JSON_THROW_ON_ERROR);
