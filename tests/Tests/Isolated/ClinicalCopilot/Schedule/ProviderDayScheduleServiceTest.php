<?php

/**
 * Isolated unit tests for ProviderDayScheduleService (mocked row loader / no DB).
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
use OpenEMR\ClinicalCopilot\Schedule\ProviderDayScheduleService;
use PHPUnit\Framework\Attributes\Small;
use PHPUnit\Framework\TestCase;
use Psr\Clock\ClockInterface;

#[Small]
class ProviderDayScheduleServiceTest extends TestCase
{
    public function testGetTodayForProviderFailsClosedOnInvalidUserId(): void
    {
        $service = $this->createService(
            new DateTimeImmutable('2026-07-21 10:00:00', new DateTimeZone('America/Chicago')),
            'America/Chicago',
            static fn (): array => [],
        );

        $this->expectException(InvalidArgumentException::class);
        $service->getTodayForProvider(0);
    }

    public function testGetTodayForProviderScopesToConfiguredTimezoneDate(): void
    {
        // 2026-07-22 01:30 UTC == 2026-07-21 20:30 America/Chicago
        $nowUtc = new DateTimeImmutable('2026-07-22 01:30:00', new DateTimeZone('UTC'));
        $capturedDate = null;
        $capturedProviderId = null;

        $service = $this->createService(
            $nowUtc,
            'America/Chicago',
            static function (int $providerId, string $date) use (&$capturedDate, &$capturedProviderId): array {
                $capturedProviderId = $providerId;
                $capturedDate = $date;

                return [
                    [
                        'pid' => 6,
                        'fname' => 'Jane',
                        'lname' => 'Doe',
                        'dob' => '1980-04-12',
                        'start_time' => '20:45:00',
                        'category_title' => 'Office Visit',
                        'pc_title' => 'Office Visit',
                        'status_code' => '^',
                        'status_title' => '^ Pending',
                    ],
                ];
            },
        );

        $schedule = $service->getTodayForProvider(99);

        $this->assertSame(99, $capturedProviderId);
        $this->assertSame('2026-07-21', $capturedDate);
        $this->assertSame('2026-07-21', $schedule->date);
        $this->assertSame('America/Chicago', $schedule->timezone);
        $this->assertSame(6, $schedule->nextPid);
        $this->assertCount(1, $schedule->appointments);
    }

    public function testGetTodayForProviderDoesNotAcceptBrowserDateOverride(): void
    {
        $now = new DateTimeImmutable('2026-07-21 12:00:00', new DateTimeZone('UTC'));
        $loaderCalls = 0;

        $service = $this->createService(
            $now,
            'UTC',
            static function (int $providerId, string $date) use (&$loaderCalls): array {
                ++$loaderCalls;
                TestCase::assertSame(5, $providerId);
                TestCase::assertSame('2026-07-21', $date);

                return [];
            },
        );

        $schedule = $service->getTodayForProvider(5);

        $this->assertSame(1, $loaderCalls);
        $this->assertSame('2026-07-21', $schedule->date);
        $this->assertNull($schedule->nextPid);
    }

    public function testResolveTimezoneFallsBackToPhpDefaultWhenConfiguredBlank(): void
    {
        $previous = date_default_timezone_get();
        date_default_timezone_set('America/New_York');

        try {
            $tz = ProviderDayScheduleService::resolveTimezoneId('');
            $this->assertSame('America/New_York', $tz);
        } finally {
            date_default_timezone_set($previous);
        }
    }

    public function testResolveTimezonePrefersConfiguredValue(): void
    {
        $this->assertSame('America/Chicago', ProviderDayScheduleService::resolveTimezoneId('America/Chicago'));
    }

    public function testTerminalStatusSqlPlaceholdersMatchFilterSet(): void
    {
        $codes = ProviderDayScheduleService::terminalStatusSqlList();
        $this->assertSame(['x', '?', '!', '>', '$', '%'], $codes);
    }

    /**
     * @param callable(int, string): list<array<string, mixed>> $loader
     */
    private function createService(
        DateTimeImmutable $now,
        string $timezoneId,
        callable $loader,
    ): ProviderDayScheduleService {
        $clock = new class ($now) implements ClockInterface {
            public function __construct(private readonly DateTimeImmutable $now)
            {
            }

            public function now(): DateTimeImmutable
            {
                return $this->now;
            }
        };

        return ProviderDayScheduleService::createForTesting($clock, $timezoneId, $loader);
    }
}
