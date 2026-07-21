<?php

/**
 * Stable terminal appointment status option_ids (list_options list_id=apptstat).
 *
 * Filter by option_id, never by translated titles.
 *
 * @package   OpenEMR
 * @link      https://www.open-emr.org
 * @author    eweinhaus <eweinhaus@users.noreply.github.com>
 * @copyright Copyright (c) 2026 eweinhaus
 * @license   https://github.com/openemr/openemr/blob/master/LICENSE GNU General Public License 3
 */

declare(strict_types=1);

namespace OpenEMR\ClinicalCopilot\Schedule;

final class TerminalAppointmentStatus
{
    /**
     * x canceled, ? no show, ! left w/o visit, > checked out, $ coding done, % canceled <24h
     *
     * @var list<string>
     */
    public const CODES = ['x', '?', '!', '>', '$', '%'];

    public static function isTerminal(string $statusCode): bool
    {
        return in_array($statusCode, self::CODES, true);
    }
}
