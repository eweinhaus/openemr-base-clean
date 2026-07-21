<?php

/**
 * Ask Co-Pilot provider "today's schedule" JSON for the patient picker.
 *
 * GET (session cookie + CSRF). Provider and date are taken only from the
 * authenticated session / configured timezone — never from request params.
 *
 * Query: csrf_token_form
 * Response: application/json (see ProviderDaySchedule::toArray)
 *
 * @package   OpenEMR
 * @link      https://www.open-emr.org
 * @author    eweinhaus <eweinhaus@users.noreply.github.com>
 * @copyright Copyright (c) 2026 eweinhaus
 * @license   https://github.com/openemr/openemr/blob/master/LICENSE GNU General Public License 3
 */

declare(strict_types=1);

require_once("../globals.php");

use OpenEMR\ClinicalCopilot\Schedule\ProviderDayScheduleService;
use OpenEMR\Common\Acl\AccessDeniedHelper;
use OpenEMR\Common\Acl\AccessDeniedResponseFormat;
use OpenEMR\Common\Acl\AclMain;
use OpenEMR\Common\Csrf\CsrfUtils;
use OpenEMR\Common\Session\SessionWrapperFactory;

header('Content-Type: application/json; charset=utf-8');
header('Cache-Control: no-store');

$session = SessionWrapperFactory::getInstance()->getActiveSession();

if (!AclMain::aclCheckCore('patients', 'demo')) {
    AccessDeniedHelper::deny(
        'Ask Co-Pilot schedule access not authorized',
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

$authUserIdRaw = $session->get('authUserID');
if (!is_numeric($authUserIdRaw) || (int) $authUserIdRaw <= 0) {
    http_response_code(403);
    echo json_encode(['error' => 'Unable to process request.'], JSON_THROW_ON_ERROR);
    exit;
}

$authUserId = (int) $authUserIdRaw;

// Intentionally ignore any client-supplied provider_id / date (fail closed).
unset($_GET['provider_id'], $_GET['date'], $_REQUEST['provider_id'], $_REQUEST['date']);

try {
    $service = new ProviderDayScheduleService();
    $schedule = $service->getTodayForProvider($authUserId);
    echo json_encode($schedule->toArray(), JSON_THROW_ON_ERROR);
} catch (Throwable $e) {
    error_log('Ask Co-Pilot schedule error: ' . $e->getMessage());
    http_response_code(500);
    echo json_encode(['error' => 'Unable to process request.'], JSON_THROW_ON_ERROR);
}
