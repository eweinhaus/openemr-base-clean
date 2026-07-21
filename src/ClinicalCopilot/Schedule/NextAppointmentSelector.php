<?php

/**
 * Picks next_pid from a chronological eligible appointment list.
 *
 * "Next" = earliest appointment with start_time >= now - 15 minutes.
 *
 * @package   OpenEMR
 * @link      https://www.open-emr.org
 * @author    eweinhaus <eweinhaus@users.noreply.github.com>
 * @copyright Copyright (c) 2026 eweinhaus
 * @license   https://github.com/openemr/openemr/blob/master/LICENSE GNU General Public License 3
 */

declare(strict_types=1);

namespace OpenEMR\ClinicalCopilot\Schedule;

use DateTimeImmutable;

final class NextAppointmentSelector
{
    public const GRACE_MINUTES = 15;

    /**
     * @param list<ScheduleAppointment> $appointments Chronological, already non-terminal
     */
    public static function selectNextPid(array $appointments, DateTimeImmutable $now): ?int
    {
        $threshold = $now->modify('-' . self::GRACE_MINUTES . ' minutes');
        $day = $now->format('Y-m-d');

        foreach ($appointments as $appointment) {
            $start = DateTimeImmutable::createFromFormat(
                'Y-m-d H:i',
                $day . ' ' . $appointment->startTime,
                $now->getTimezone(),
            );
            if ($start === false) {
                continue;
            }
            if ($start >= $threshold) {
                return $appointment->pid;
            }
        }

        return null;
    }
}
