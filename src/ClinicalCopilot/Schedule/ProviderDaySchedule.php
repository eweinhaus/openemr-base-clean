<?php

/**
 * Immutable provider day schedule response for Ask Co-Pilot patient picker.
 *
 * @package   OpenEMR
 * @link      https://www.open-emr.org
 * @author    eweinhaus <eweinhaus@users.noreply.github.com>
 * @copyright Copyright (c) 2026 eweinhaus
 * @license   https://github.com/openemr/openemr/blob/master/LICENSE GNU General Public License 3
 */

declare(strict_types=1);

namespace OpenEMR\ClinicalCopilot\Schedule;

final readonly class ProviderDaySchedule
{
    /**
     * @param list<ScheduleAppointment> $appointments
     */
    public function __construct(
        public string $date,
        public string $timezone,
        public ?int $nextPid,
        public ?string $nextPidMode,
        public array $appointments,
    ) {
    }

    /**
     * @return array{
     *     date: string,
     *     timezone: string,
     *     next_pid: int|null,
     *     next_pid_mode: string|null,
     *     appointments: list<array{
     *         pid: int,
     *         name: string,
     *         dob: string,
     *         start_time: string,
     *         title: string,
     *         status: string
     *     }>
     * }
     */
    public function toArray(): array
    {
        return [
            'date' => $this->date,
            'timezone' => $this->timezone,
            'next_pid' => $this->nextPid,
            'next_pid_mode' => $this->nextPidMode,
            'appointments' => array_map(
                static fn (ScheduleAppointment $appointment): array => $appointment->toArray(),
                $this->appointments,
            ),
        ];
    }
}
