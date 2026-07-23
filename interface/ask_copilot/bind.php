<?php

/**
 * Ask Co-Pilot session patient bind (JSON).
 *
 * POST (session cookie + CSRF). Sets the authenticated session pid without
 * navigating away from the Ask Co-Pilot tab.
 *
 * @package   OpenEMR
 * @link      https://www.open-emr.org
 * @author    eweinhaus <eweinhaus@users.noreply.github.com>
 * @copyright Copyright (c) 2026 eweinhaus
 * @license   https://github.com/openemr/openemr/blob/master/LICENSE GNU General Public License 3
 */

declare(strict_types=1);

require_once("../globals.php");

require_once($GLOBALS['srcdir'] . '/pid.inc.php');

use OpenEMR\ClinicalCopilot\ClinicalDisplayDate;
use OpenEMR\ClinicalCopilot\PatientDisplayName;
use OpenEMR\Common\Acl\AccessDeniedHelper;
use OpenEMR\Common\Acl\AccessDeniedResponseFormat;
use OpenEMR\Common\Acl\AclMain;
use OpenEMR\Common\Csrf\CsrfUtils;
use OpenEMR\Common\Database\QueryUtils;
use OpenEMR\Common\Session\SessionWrapperFactory;
use OpenEMR\Core\OEGlobalsBag;

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
        'Ask Co-Pilot bind access not authorized',
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

$pidRaw = $_POST['pid'] ?? $_POST['set_pid'] ?? null;
if (!is_numeric($pidRaw) || (int) $pidRaw <= 0) {
    http_response_code(400);
    echo json_encode(['error' => 'Unable to process request.'], JSON_THROW_ON_ERROR);
    exit;
}

$pid = (int) $pidRaw;

try {
    $rows = QueryUtils::fetchRecords(
        'SELECT fname, lname, pubpid, DOB FROM patient_data WHERE pid = ? LIMIT 1',
        [$pid],
    );
    $row = $rows[0] ?? null;
    if (!is_array($row)) {
        http_response_code(404);
        echo json_encode(['error' => 'Unable to process request.'], JSON_THROW_ON_ERROR);
        exit;
    }

    if ((int) ($session->get('pid') ?? 0) !== $pid) {
        setpid($pid);
    }

    $name = PatientDisplayName::fromParts(
        is_string($row['fname'] ?? null) ? $row['fname'] : (string) ($row['fname'] ?? ''),
        is_string($row['lname'] ?? null) ? $row['lname'] : (string) ($row['lname'] ?? ''),
    );

    $dobDisplay = ClinicalDisplayDate::format($row['DOB'] ?? '');
    $dobLabel = $dobDisplay !== ''
        ? xl('DOB') . ' ' . $dobDisplay
        : '';

    echo json_encode([
        'pid' => $pid,
        'name' => $name !== '' ? $name : null,
        'pubpid' => is_string($row['pubpid'] ?? null) && $row['pubpid'] !== ''
            ? (string) $row['pubpid']
            : (string) $pid,
        'dob_display' => $dobLabel !== '' ? $dobLabel : null,
    ], JSON_THROW_ON_ERROR);
} catch (Throwable $e) {
    error_log('Ask Co-Pilot bind error: ' . $e->getMessage());
    http_response_code(500);
    echo json_encode(['error' => 'Unable to process request.'], JSON_THROW_ON_ERROR);
}
