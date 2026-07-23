<?php

/**
 * Isolated unit tests for schedule prefetch pid selection (picker display order).
 *
 * @package   OpenEMR
 * @link      https://www.open-emr.org
 * @author    eweinhaus <eweinhaus@users.noreply.github.com>
 * @copyright Copyright (c) 2026 eweinhaus
 * @license   https://github.com/openemr/openemr/blob/master/LICENSE GNU General Public License 3
 */

declare(strict_types=1);

namespace OpenEMR\Tests\Isolated\ClinicalCopilot\Schedule;

use OpenEMR\ClinicalCopilot\Schedule\NextAppointmentSelector;
use OpenEMR\ClinicalCopilot\Schedule\ProviderDaySchedule;
use OpenEMR\ClinicalCopilot\Schedule\ScheduleAppointment;
use OpenEMR\ClinicalCopilot\Schedule\SchedulePrefetchSelector;
use PHPUnit\Framework\Attributes\Small;
use PHPUnit\Framework\TestCase;

#[Small]
class SchedulePrefetchSelectorTest extends TestCase
{
    public function testNextCardPlusTwoListRowsReturnsThreePidsInDisplayOrder(): void
    {
        $appointments = [
            $this->appt(6, '09:00'),
            $this->appt(8, '10:00'),
            $this->appt(2, '11:00'),
        ];
        $schedule = $this->schedule(nextPid: 8, appointments: $appointments);

        $this->assertSame([8, 6, 2], SchedulePrefetchSelector::topPids($schedule));
    }

    public function testNextPidFirstAndNotDuplicatedWhenSamePidAppearsAgainInList(): void
    {
        $appointments = [
            $this->appt(5, '09:00'),
            $this->appt(5, '10:00'),
            $this->appt(7, '11:00'),
        ];
        $schedule = $this->schedule(nextPid: 5, appointments: $appointments);

        $this->assertSame([5, 7], SchedulePrefetchSelector::topPids($schedule));
    }

    public function testDuplicatePidOnScheduleReturnsOneEntry(): void
    {
        $appointments = [
            $this->appt(4, '09:00'),
            $this->appt(4, '10:00'),
        ];
        $schedule = $this->schedule(nextPid: null, appointments: $appointments);

        $this->assertSame([4], SchedulePrefetchSelector::topPids($schedule));
    }

    public function testOneAppointmentReturnsOnePid(): void
    {
        $appointments = [$this->appt(9, '14:00')];
        $schedule = $this->schedule(nextPid: 9, appointments: $appointments);

        $this->assertSame([9], SchedulePrefetchSelector::topPids($schedule));
    }

    public function testEmptyAppointmentsReturnsEmptyList(): void
    {
        $schedule = $this->schedule(nextPid: null, appointments: []);

        $this->assertSame([], SchedulePrefetchSelector::topPids($schedule));
    }

    /**
     * @param list<ScheduleAppointment> $appointments
     */
    private function schedule(?int $nextPid, array $appointments): ProviderDaySchedule
    {
        return new ProviderDaySchedule(
            date: '2026-07-21',
            timezone: 'America/Chicago',
            nextPid: $nextPid,
            nextPidMode: $nextPid !== null ? NextAppointmentSelector::MODE_UPCOMING : null,
            appointments: $appointments,
        );
    }

    private function appt(int $pid, string $startTime): ScheduleAppointment
    {
        return new ScheduleAppointment(
            pid: $pid,
            name: 'Patient ' . $pid,
            dob: '1980-01-01',
            startTime: $startTime,
            title: 'Office Visit',
            status: 'Pending',
        );
    }
}
