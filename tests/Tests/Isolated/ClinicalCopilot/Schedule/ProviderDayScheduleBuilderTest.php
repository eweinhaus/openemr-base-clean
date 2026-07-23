<?php

/**
 * Isolated unit tests for assembling a provider day schedule from query rows.
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
use InvalidArgumentException;
use OpenEMR\ClinicalCopilot\Schedule\NextAppointmentSelector;
use OpenEMR\ClinicalCopilot\Schedule\ProviderDayScheduleBuilder;
use OpenEMR\ClinicalCopilot\Schedule\TerminalAppointmentStatus;
use PHPUnit\Framework\Attributes\DataProvider;
use PHPUnit\Framework\Attributes\Small;
use PHPUnit\Framework\TestCase;

#[Small]
class ProviderDayScheduleBuilderTest extends TestCase
{
    private ProviderDayScheduleBuilder $builder;

    protected function setUp(): void
    {
        $this->builder = new ProviderDayScheduleBuilder();
    }

    public function testFailsClosedOnNonPositiveProviderId(): void
    {
        $now = new DateTimeImmutable('2026-07-21 10:00:00', new DateTimeZone('America/Chicago'));

        $this->expectException(InvalidArgumentException::class);
        $this->builder->build(0, [], '2026-07-21', 'America/Chicago', $now);
    }

    public function testFailsClosedOnNegativeProviderId(): void
    {
        $now = new DateTimeImmutable('2026-07-21 10:00:00', new DateTimeZone('America/Chicago'));

        $this->expectException(InvalidArgumentException::class);
        $this->builder->build(-3, [], '2026-07-21', 'America/Chicago', $now);
    }

    public function testEmptyRowsYieldEmptyScheduleAndNullNextPid(): void
    {
        $now = new DateTimeImmutable('2026-07-21 10:00:00', new DateTimeZone('America/Chicago'));

        $schedule = $this->builder->build(42, [], '2026-07-21', 'America/Chicago', $now);

        $this->assertSame('2026-07-21', $schedule->date);
        $this->assertSame('America/Chicago', $schedule->timezone);
        $this->assertNull($schedule->nextPid);
        $this->assertSame([], $schedule->appointments);
        $payload = $schedule->toArray();
        $this->assertNull($payload['next_pid']);
        $this->assertSame([], $payload['appointments']);
    }

    public function testOrdersChronologicallyByStartTime(): void
    {
        $now = new DateTimeImmutable('2026-07-21 08:00:00', new DateTimeZone('America/Chicago'));
        $rows = [
            $this->row(3, 'Jane', 'C', '1980-01-03', '15:00:00', 'Follow-up', '^', '^ Pending'),
            $this->row(1, 'Jane', 'A', '1980-01-01', '09:00:00', 'Office Visit', '-', '- None'),
            $this->row(2, 'Jane', 'B', '1980-01-02', '11:30:00', 'Lab', '@', '@ Arrived'),
        ];

        $schedule = $this->builder->build(7, $rows, '2026-07-21', 'America/Chicago', $now);

        $this->assertSame([1, 2, 3], array_map(static fn ($a) => $a->pid, $schedule->appointments));
        $this->assertSame(['09:00', '11:30', '15:00'], array_map(static fn ($a) => $a->startTime, $schedule->appointments));
    }

    public function testFiltersTerminalStatuses(): void
    {
        $now = new DateTimeImmutable('2026-07-21 08:00:00', new DateTimeZone('America/Chicago'));
        $rows = [
            $this->row(1, 'Keep', 'Me', '1980-01-01', '09:00:00', 'Visit', '^', '^ Pending'),
            $this->row(2, 'Cancel', 'Ed', '1980-01-02', '10:00:00', 'Visit', 'x', 'x Canceled'),
            $this->row(3, 'No', 'Show', '1980-01-03', '11:00:00', 'Visit', '?', '? No show'),
            $this->row(4, 'Left', 'Early', '1980-01-04', '12:00:00', 'Visit', '!', '! Left w/o visit'),
            $this->row(5, 'Checked', 'Out', '1980-01-05', '13:00:00', 'Visit', '>', '> Checked out'),
            $this->row(6, 'Coded', 'Done', '1980-01-06', '14:00:00', 'Visit', '$', '$ Coding done'),
            $this->row(7, 'Late', 'Cancel', '1980-01-07', '15:00:00', 'Visit', '%', '% Canceled < 24h'),
            $this->row(8, 'Also', 'Keep', '1980-01-08', '16:00:00', 'Visit', '@', '@ Arrived'),
        ];

        $schedule = $this->builder->build(7, $rows, '2026-07-21', 'America/Chicago', $now);

        $this->assertSame([1, 8], array_map(static fn ($a) => $a->pid, $schedule->appointments));
    }

    #[DataProvider('terminalStatusProvider')]
    public function testTerminalStatusHelperRecognizesCodes(string $code, bool $expected): void
    {
        $this->assertSame($expected, TerminalAppointmentStatus::isTerminal($code));
    }

    /**
     * @return array<string, array{string, bool}>
     *
     * @codeCoverageIgnore Data providers run before coverage instrumentation starts.
     */
    public static function terminalStatusProvider(): array
    {
        return [
            'canceled' => ['x', true],
            'no show' => ['?', true],
            'left without visit' => ['!', true],
            'checked out' => ['>', true],
            'coding done' => ['$', true],
            'canceled under 24h' => ['%', true],
            'pending' => ['^', false],
            'none' => ['-', false],
            'arrived' => ['@', false],
            'empty' => ['', false],
        ];
    }

    public function testDropsNonPositivePids(): void
    {
        $now = new DateTimeImmutable('2026-07-21 08:00:00', new DateTimeZone('America/Chicago'));
        $rows = [
            $this->row(0, 'Zero', 'Pid', '1980-01-01', '09:00:00', 'Visit', '^', '^ Pending'),
            $this->row(-1, 'Neg', 'Pid', '1980-01-02', '10:00:00', 'Visit', '^', '^ Pending'),
            $this->row(6, 'Good', 'Pid', '1980-01-03', '11:00:00', 'Visit', '^', '^ Pending'),
        ];

        $schedule = $this->builder->build(7, $rows, '2026-07-21', 'America/Chicago', $now);

        $this->assertCount(1, $schedule->appointments);
        $this->assertSame(6, $schedule->appointments[0]->pid);
        $this->assertSame(6, $schedule->nextPid);
    }

    public function testMapsNameDobTitleStatusAndNormalizesStartTime(): void
    {
        $now = new DateTimeImmutable('2026-07-21 08:00:00', new DateTimeZone('America/Chicago'));
        $rows = [
            $this->row(6, 'Jane', 'Doe', '1980-04-12', '14:30:00', 'Office Visit', '^', '^ Pending'),
        ];

        $schedule = $this->builder->build(7, $rows, '2026-07-21', 'America/Chicago', $now);
        $appt = $schedule->appointments[0];

        $this->assertSame(6, $appt->pid);
        $this->assertSame('Jane Doe', $appt->name);
        $this->assertSame('1980-04-12', $appt->dob);
        $this->assertSame('14:30', $appt->startTime);
        $this->assertSame('Office Visit', $appt->title);
        $this->assertSame('Pending', $appt->status);
    }

    public function testStripsSyntheaNumericSuffixesFromDisplayName(): void
    {
        $now = new DateTimeImmutable('2026-07-21 08:00:00', new DateTimeZone('America/Chicago'));
        $rows = [
            $this->row(6, 'Gonzalo160', 'Wisozk929', '1980-04-12', '09:00:00', 'Visit', '^', '^ Pending'),
        ];

        $schedule = $this->builder->build(7, $rows, '2026-07-21', 'America/Chicago', $now);

        $this->assertSame('Gonzalo Wisozk', $schedule->appointments[0]->name);
    }

    public function testNextPidUsesFifteenMinuteGrace(): void
    {
        $now = new DateTimeImmutable('2026-07-21 14:00:00', new DateTimeZone('America/Chicago'));
        $rows = [
            $this->row(1, 'Past', 'Grace', '1980-01-01', '13:40:00', 'Visit', '^', '^ Pending'),
            $this->row(2, 'In', 'Grace', '1980-01-02', '13:50:00', 'Visit', '^', '^ Pending'),
            $this->row(3, 'Later', 'On', '1980-01-03', '15:00:00', 'Visit', '^', '^ Pending'),
        ];

        $schedule = $this->builder->build(7, $rows, '2026-07-21', 'America/Chicago', $now);

        $this->assertSame(2, $schedule->nextPid);
        $this->assertCount(3, $schedule->appointments);
    }

    public function testJsonShapeUsesSnakeCaseKeys(): void
    {
        $now = new DateTimeImmutable('2026-07-21 08:00:00', new DateTimeZone('UTC'));
        $rows = [
            $this->row(6, 'Jane', 'Doe', '1980-04-12', '14:30:00', 'Office Visit', '^', '^ Pending'),
        ];

        $payload = $this->builder->build(7, $rows, '2026-07-21', 'UTC', $now)->toArray();

        $this->assertSame(
            [
                'date' => '2026-07-21',
                'timezone' => 'UTC',
                'next_pid' => 6,
                'next_pid_mode' => NextAppointmentSelector::MODE_UPCOMING,
                'appointments' => [
                    [
                        'pid' => 6,
                        'name' => 'Jane Doe',
                        'dob' => '1980-04-12',
                        'start_time' => '14:30',
                        'title' => 'Office Visit',
                        'status' => 'Pending',
                    ],
                ],
            ],
            $payload
        );
    }

    public function testFallsBackToPcTitleWhenCategoryMissing(): void
    {
        $now = new DateTimeImmutable('2026-07-21 08:00:00', new DateTimeZone('America/Chicago'));
        $row = $this->row(6, 'Jane', 'Doe', '1980-04-12', '09:00:00', null, '^', '^ Pending');
        $row['pc_title'] = 'Custom Title';

        $schedule = $this->builder->build(7, [$row], '2026-07-21', 'America/Chicago', $now);

        $this->assertSame('Custom Title', $schedule->appointments[0]->title);
    }

    public function testPreservesConfiguredTimezoneInResponse(): void
    {
        $now = new DateTimeImmutable('2026-07-21 23:30:00', new DateTimeZone('America/Los_Angeles'));
        $schedule = $this->builder->build(7, [], '2026-07-21', 'America/Los_Angeles', $now);

        $this->assertSame('America/Los_Angeles', $schedule->timezone);
        $this->assertSame('2026-07-21', $schedule->date);
    }

    /**
     * @return array{
     *     pid: int,
     *     fname: string,
     *     lname: string,
     *     dob: string,
     *     start_time: string,
     *     category_title: ?string,
     *     pc_title: string,
     *     status_code: string,
     *     status_title: string
     * }
     */
    private function row(
        int $pid,
        string $fname,
        string $lname,
        string $dob,
        string $startTime,
        ?string $categoryTitle,
        string $statusCode,
        string $statusTitle,
    ): array {
        return [
            'pid' => $pid,
            'fname' => $fname,
            'lname' => $lname,
            'dob' => $dob,
            'start_time' => $startTime,
            'category_title' => $categoryTitle,
            'pc_title' => $categoryTitle ?? '',
            'status_code' => $statusCode,
            'status_title' => $statusTitle,
        ];
    }
}
