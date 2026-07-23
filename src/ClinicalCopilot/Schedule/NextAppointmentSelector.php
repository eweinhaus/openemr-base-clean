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

    public const MODE_UPCOMING = 'upcoming';

    public const MODE_FIRST_TODAY = 'first_today';

    /**
     * @param list<ScheduleAppointment> $appointments Chronological, already non-terminal
     *
     * @return array{pid: int|null, mode: string|null}
     */
    public static function selectNext(array $appointments, DateTimeImmutable $now): array
    {
        if ($appointments === []) {
            return ['pid' => null, 'mode' => null];
        }

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
                return ['pid' => $appointment->pid, 'mode' => self::MODE_UPCOMING];
            }
        }

        // End-of-day / demo: still surface the first appointment so the picker
        // has a clear default when nothing is within the grace window.
        return ['pid' => $appointments[0]->pid, 'mode' => self::MODE_FIRST_TODAY];
    }

    /**
     * @param list<ScheduleAppointment> $appointments Chronological, already non-terminal
     */
    public static function selectNextPid(array $appointments, DateTimeImmutable $now): ?int
    {
        return self::selectNext($appointments, $now)['pid'];
    }
}
