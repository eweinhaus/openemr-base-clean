<?php

/**
 * Ask Co-Pilot session patient display name (JSON).
 *
 * GET (session cookie + CSRF). Returns the name for the authenticated session
 * pid only — no client-supplied pid parameter.
 *
 * @package   OpenEMR
 * @link      https://www.open-emr.org
 * @author    eweinhaus <eweinhaus@users.noreply.github.com>
 * @copyright Copyright (c) 2026 eweinhaus
 * @license   https://github.com/openemr/openemr/blob/master/LICENSE GNU General Public License 3
 */

declare(strict_types=1);

require_once("../globals.php");

use OpenEMR\ClinicalCopilot\PatientDisplayName;
use OpenEMR\Common\Acl\AccessDeniedHelper;
use OpenEMR\Common\Acl\AccessDeniedResponseFormat;
use OpenEMR\Common\Acl\AclMain;
use OpenEMR\Common\Csrf\CsrfUtils;
use OpenEMR\Common\Database\QueryUtils;
use OpenEMR\Common\Session\SessionWrapperFactory;

header('Content-Type: application/json; charset=utf-8');
header('Cache-Control: no-store');

$session = SessionWrapperFactory::getInstance()->getActiveSession();

if (!AclMain::aclCheckCore('patients', 'demo')) {
    AccessDeniedHelper::deny(
        'Ask Co-Pilot patient access not authorized',
        format: AccessDeniedResponseFormat::Json,
    );
}

try {
    CsrfUtils::checkCsrfInput(INPUT_GET, session: $session, dieOnFail: false);
} catch (Throwable) {
    http_response_code(403);
    echo json_encode(['error' => 'Unable to process request.'], JSON_THROW_ON_ERROR);
    exit;
}

$pidRaw = $session->get('pid');
$pid = is_numeric($pidRaw) ? (int) $pidRaw : 0;
if ($pid <= 0) {
    echo json_encode(['pid' => null, 'name' => null], JSON_THROW_ON_ERROR);
    exit;
}

try {
    $rows = QueryUtils::fetchRecords(
        'SELECT fname, lname FROM patient_data WHERE pid = ? LIMIT 1',
        [$pid],
    );
    $row = $rows[0] ?? null;
    if (!is_array($row)) {
        echo json_encode(['pid' => $pid, 'name' => null], JSON_THROW_ON_ERROR);
        exit;
    }

    $name = PatientDisplayName::fromParts(
        is_string($row['fname'] ?? null) ? $row['fname'] : (string) ($row['fname'] ?? ''),
        is_string($row['lname'] ?? null) ? $row['lname'] : (string) ($row['lname'] ?? ''),
    );

    echo json_encode([
        'pid' => $pid,
        'name' => $name !== '' ? $name : null,
    ], JSON_THROW_ON_ERROR);
} catch (Throwable $e) {
    error_log('Ask Co-Pilot patient error: ' . $e->getMessage());
    http_response_code(500);
    echo json_encode(['error' => 'Unable to process request.'], JSON_THROW_ON_ERROR);
}
