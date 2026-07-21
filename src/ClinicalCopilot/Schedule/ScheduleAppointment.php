<?php

/**
 * Immutable appointment row for the Ask Co-Pilot provider day schedule.
 *
 * @package   OpenEMR
 * @link      https://www.open-emr.org
 * @author    eweinhaus <eweinhaus@users.noreply.github.com>
 * @copyright Copyright (c) 2026 eweinhaus
 * @license   https://github.com/openemr/openemr/blob/master/LICENSE GNU General Public License 3
 */

declare(strict_types=1);

namespace OpenEMR\ClinicalCopilot\Schedule;

final readonly class ScheduleAppointment
{
    public function __construct(
        public int $pid,
        public string $name,
        public string $dob,
        public string $startTime,
        public string $title,
        public string $status,
    ) {
    }

    /**
     * @return array{
     *     pid: int,
     *     name: string,
     *     dob: string,
     *     start_time: string,
     *     title: string,
     *     status: string
     * }
     */
    public function toArray(): array
    {
        return [
            'pid' => $this->pid,
            'name' => $this->name,
            'dob' => $this->dob,
            'start_time' => $this->startTime,
            'title' => $this->title,
            'status' => $this->status,
        ];
    }
}
