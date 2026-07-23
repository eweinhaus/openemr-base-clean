<?php

/**
 * Top-N patient ids for brief prefetch in Ask Co-Pilot picker display order.
 *
 * Mirrors interface/ask_copilot/assets/ask_copilot.js renderSchedule: next card
 * first, then remaining appointments (skip the next row in the list).
 *
 * @package   OpenEMR
 * @link      https://www.open-emr.org
 * @author    eweinhaus <eweinhaus@users.noreply.github.com>
 * @copyright Copyright (c) 2026 eweinhaus
 * @license   https://github.com/openemr/openemr/blob/master/LICENSE GNU General Public License 3
 */

declare(strict_types=1);

namespace OpenEMR\ClinicalCopilot\Schedule;

final class SchedulePrefetchSelector
{
    /**
     * Unique pids in picker display order, capped at $limit.
     *
     * @return list<int>
     */
    public static function topPids(ProviderDaySchedule $schedule, int $limit = 3): array
    {
        $appointments = $schedule->appointments;
        if ($appointments === []) {
            return [];
        }

        $pids = [];
        $nextPid = $schedule->nextPid;
        $nextIndex = -1;

        if ($nextPid !== null) {
            foreach ($appointments as $i => $appointment) {
                if ($appointment->pid === $nextPid) {
                    $nextIndex = $i;
                    break;
                }
            }
        }

        if ($nextIndex >= 0) {
            $pids[] = $appointments[$nextIndex]->pid;
        }

        foreach ($appointments as $j => $appointment) {
            if ($j === $nextIndex) {
                continue;
            }
            if (!in_array($appointment->pid, $pids, true)) {
                $pids[] = $appointment->pid;
            }
            if (count($pids) >= $limit) {
                break;
            }
        }

        return $pids;
    }
}
