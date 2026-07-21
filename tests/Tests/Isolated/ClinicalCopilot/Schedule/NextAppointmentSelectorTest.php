<?php

/**
 * Isolated unit tests for next-appointment pid selection (15-minute grace).
 *
 * @package   OpenEMR
 * @link      https://www.open-emr.org
 * @author    eweinhaus <eweinhaus@users.noreply.github.com>
 * @copyright Copyright (c) 2026 eweinhaus
 * @license   https://github.com/openemr/openemr/blob/master/LICENSE GNU General Public License 3
 */

declare(strict_types=1);

namespace OpenEMR\Tests\Isolated\ClinicalCopilot\Schedule;

use DateTimeImmutable;
use DateTimeZone;
use OpenEMR\ClinicalCopilot\Schedule\NextAppointmentSelector;
use OpenEMR\ClinicalCopilot\Schedule\ScheduleAppointment;
use PHPUnit\Framework\Attributes\DataProvider;
use PHPUnit\Framework\Attributes\Small;
use PHPUnit\Framework\TestCase;

#[Small]
class NextAppointmentSelectorTest extends TestCase
{
    public function testReturnsNullWhenScheduleEmpty(): void
    {
        $now = new DateTimeImmutable('2026-07-21 14:00:00', new DateTimeZone('America/Chicago'));

        $this->assertNull(NextAppointmentSelector::selectNextPid([], $now));
    }

    public function testPicksEarliestAtOrAfterGraceWindow(): void
    {
        $now = new DateTimeImmutable('2026-07-21 14:00:00', new DateTimeZone('America/Chicago'));
        $appointments = [
            $this->appt(1, '13:40'), // 20 min ago — outside grace
            $this->appt(2, '13:50'), // 10 min ago — inside grace
            $this->appt(3, '14:30'),
        ];

        $this->assertSame(2, NextAppointmentSelector::selectNextPid($appointments, $now));
    }

    public function testGraceBoundaryExactlyFifteenMinutesIsEligible(): void
    {
        $now = new DateTimeImmutable('2026-07-21 14:00:00', new DateTimeZone('America/Chicago'));
        $appointments = [
            $this->appt(5, '13:45'), // exactly now - 15
            $this->appt(6, '14:15'),
        ];

        $this->assertSame(5, NextAppointmentSelector::selectNextPid($appointments, $now));
    }

    public function testGraceBoundaryOneSecondBeforeFifteenMinutesIsExcluded(): void
    {
        $now = new DateTimeImmutable('2026-07-21 14:00:00', new DateTimeZone('America/Chicago'));
        $appointments = [
            $this->appt(5, '13:44'), // 16 min ago
            $this->appt(6, '14:15'),
        ];

        $this->assertSame(6, NextAppointmentSelector::selectNextPid($appointments, $now));
    }

    public function testReturnsNullWhenAllAppointmentsArePastGrace(): void
    {
        $now = new DateTimeImmutable('2026-07-21 16:00:00', new DateTimeZone('America/Chicago'));
        $appointments = [
            $this->appt(1, '09:00'),
            $this->appt(2, '10:30'),
        ];

        $this->assertNull(NextAppointmentSelector::selectNextPid($appointments, $now));
    }

    public function testUsesAppointmentDateFromNowNotCallerDateString(): void
    {
        $now = new DateTimeImmutable('2026-07-21 14:00:00', new DateTimeZone('America/Chicago'));
        $appointments = [$this->appt(9, '14:00')];

        $this->assertSame(9, NextAppointmentSelector::selectNextPid($appointments, $now));
    }

    #[DataProvider('timezoneProvider')]
    public function testRespectsTimezoneOfNow(string $timezoneId, string $nowLocal, string $startTime, int $expectedPid): void
    {
        $now = new DateTimeImmutable($nowLocal, new DateTimeZone($timezoneId));
        $appointments = [
            $this->appt(1, '08:00'),
            $this->appt($expectedPid, $startTime),
        ];

        $this->assertSame($expectedPid, NextAppointmentSelector::selectNextPid($appointments, $now));
    }

    /**
     * @return array<string, array{string, string, string, int}>
     *
     * @codeCoverageIgnore Data providers run before coverage instrumentation starts.
     */
    public static function timezoneProvider(): array
    {
        return [
            'chicago afternoon' => ['America/Chicago', '2026-07-21 14:00:00', '14:30', 7],
            'utc morning' => ['UTC', '2026-07-21 09:00:00', '09:10', 7],
        ];
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
