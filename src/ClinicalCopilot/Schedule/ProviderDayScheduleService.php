<?php

/**
 * Provider-scoped today's schedule for Ask Co-Pilot patient picker.
 *
 * Provider and date are never accepted from the browser — only session authUserID
 * and "today" in the configured OpenEMR timezone.
 *
 * Does not extend BaseService: that base class bootstraps DB-backed code_types at
 * include time, which breaks isolated PHPUnit. Still follows the service pattern
 * (TABLE_NAME + QueryUtils, typed API, fail-closed identity).
 *
 * @package   OpenEMR
 * @link      https://www.open-emr.org
 * @author    eweinhaus <eweinhaus@users.noreply.github.com>
 * @copyright Copyright (c) 2026 eweinhaus
 * @license   https://github.com/openemr/openemr/blob/master/LICENSE GNU General Public License 3
 */

declare(strict_types=1);

namespace OpenEMR\ClinicalCopilot\Schedule;

use DateTimeZone;
use InvalidArgumentException;
use Lcobucci\Clock\SystemClock;
use OpenEMR\Common\Database\QueryUtils;
use OpenEMR\Core\OEGlobalsBag;
use Psr\Clock\ClockInterface;
use Throwable;

final class ProviderDayScheduleService
{
    public const TABLE_NAME = 'openemr_postcalendar_events';

    private readonly ClockInterface $clock;

    private readonly string $timezoneId;

    private readonly ProviderDayScheduleBuilder $builder;

    /**
     * Optional row loader for isolated tests (providerId, Y-m-d date).
     *
     * @var (callable(int, string): list<array<string, mixed>>)|null
     */
    private $appointmentLoader;

    public function __construct(
        ?ClockInterface $clock = null,
        ?string $timezoneId = null,
        ?callable $appointmentLoader = null,
    ) {
        $this->timezoneId = self::resolveTimezoneId($timezoneId ?? self::readConfiguredTimezone());
        $this->clock = $clock ?? new SystemClock(new DateTimeZone($this->timezoneId));
        $this->builder = new ProviderDayScheduleBuilder();
        $this->appointmentLoader = $appointmentLoader;
    }

    /**
     * Build a service instance without touching the database (isolated tests).
     *
     * @param callable(int, string): list<array<string, mixed>> $appointmentLoader
     */
    public static function createForTesting(
        ClockInterface $clock,
        string $timezoneId,
        callable $appointmentLoader,
    ): self {
        return new self($clock, $timezoneId, $appointmentLoader);
    }

    public function getTodayForProvider(int $providerUserId): ProviderDaySchedule
    {
        if ($providerUserId <= 0) {
            throw new InvalidArgumentException('Provider user id must be a positive integer.');
        }

        $timezone = new DateTimeZone($this->timezoneId);
        $now = $this->clock->now()->setTimezone($timezone);
        $date = $now->format('Y-m-d');
        $rows = $this->loadAppointmentsForDay($providerUserId, $date);

        return $this->builder->build($providerUserId, $rows, $date, $this->timezoneId, $now);
    }

    /**
     * @return list<string>
     */
    public static function terminalStatusSqlList(): array
    {
        return TerminalAppointmentStatus::CODES;
    }

    public static function resolveTimezoneId(string $configured): string
    {
        $configured = trim($configured);
        if ($configured === '') {
            return date_default_timezone_get();
        }

        try {
            new DateTimeZone($configured);
        } catch (Throwable) {
            return date_default_timezone_get();
        }

        return $configured;
    }

    private static function readConfiguredTimezone(): string
    {
        try {
            $value = OEGlobalsBag::getInstance()->get('gbl_time_zone');
            if (is_string($value)) {
                return $value;
            }
        } catch (Throwable) {
            // Fall through to PHP default.
        }

        return date_default_timezone_get();
    }

    /**
     * @return list<array<string, mixed>>
     */
    private function loadAppointmentsForDay(int $providerUserId, string $date): array
    {
        if ($this->appointmentLoader !== null) {
            $rows = ($this->appointmentLoader)($providerUserId, $date);

            return array_values($rows);
        }

        $terminal = self::terminalStatusSqlList();
        $placeholders = implode(', ', array_fill(0, count($terminal), '?'));

        $sql = <<<SQL
            SELECT
                p.pid AS pid,
                p.fname AS fname,
                p.lname AS lname,
                p.DOB AS dob,
                e.pc_startTime AS start_time,
                c.pc_catname AS category_title,
                e.pc_title AS pc_title,
                e.pc_apptstatus AS status_code,
                lo.title AS status_title
            FROM openemr_postcalendar_events AS e
            INNER JOIN patient_data AS p ON p.pid = e.pc_pid
            LEFT JOIN openemr_postcalendar_categories AS c ON c.pc_catid = e.pc_catid
            LEFT JOIN list_options AS lo
                ON lo.list_id = 'apptstat'
                AND lo.option_id = e.pc_apptstatus
                AND lo.activity = 1
            WHERE e.pc_aid = ?
              AND e.pc_eventDate = ?
              AND e.pc_pid > 0
              AND e.pc_apptstatus NOT IN ($placeholders)
            ORDER BY e.pc_startTime ASC
            SQL;

        $binds = array_merge([$providerUserId, $date], $terminal);
        $rows = QueryUtils::fetchRecords($sql, $binds);

        /** @var list<array<string, mixed>> $normalized */
        $normalized = [];
        foreach ($rows as $row) {
            if (is_array($row)) {
                $normalized[] = $row;
            }
        }

        return $normalized;
    }
}
