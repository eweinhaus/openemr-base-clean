<?php

/**
 * Maps raw appointment query rows into a ProviderDaySchedule.
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
use InvalidArgumentException;
use OpenEMR\ClinicalCopilot\PatientDisplayName;

final class ProviderDayScheduleBuilder
{
    /**
     * @param list<array<string, mixed>> $rows
     */
    public function build(
        int $providerUserId,
        array $rows,
        string $date,
        string $timezone,
        DateTimeImmutable $now,
    ): ProviderDaySchedule {
        if ($providerUserId <= 0) {
            throw new InvalidArgumentException('Provider user id must be a positive integer.');
        }

        $appointments = [];
        foreach ($rows as $row) {
            $appointment = $this->mapRow($row);
            if ($appointment === null) {
                continue;
            }
            $appointments[] = $appointment;
        }

        usort(
            $appointments,
            static fn (ScheduleAppointment $a, ScheduleAppointment $b): int => strcmp($a->startTime, $b->startTime),
        );

        /** @var list<ScheduleAppointment> $appointments */
        $appointments = array_values($appointments);

        $next = NextAppointmentSelector::selectNext($appointments, $now);

        return new ProviderDaySchedule(
            date: $date,
            timezone: $timezone,
            nextPid: $next['pid'],
            nextPidMode: $next['mode'],
            appointments: $appointments,
        );
    }

    /**
     * @param array<string, mixed> $row
     */
    private function mapRow(array $row): ?ScheduleAppointment
    {
        $pidRaw = $row['pid'] ?? null;
        if (!is_numeric($pidRaw)) {
            return null;
        }
        $pid = (int) $pidRaw;
        if ($pid <= 0) {
            return null;
        }

        $statusCode = $this->asString($row['status_code'] ?? '');
        if (TerminalAppointmentStatus::isTerminal($statusCode)) {
            return null;
        }

        $startTime = $this->normalizeStartTime($this->asString($row['start_time'] ?? ''));
        if ($startTime === null) {
            return null;
        }

        $name = PatientDisplayName::fromParts(
            $this->asString($row['fname'] ?? ''),
            $this->asString($row['lname'] ?? ''),
        );
        if ($name === '') {
            $name = 'Patient ' . $pid;
        }

        $categoryTitle = $this->asString($row['category_title'] ?? '');
        $pcTitle = $this->asString($row['pc_title'] ?? '');
        $title = $categoryTitle !== '' ? $categoryTitle : $pcTitle;

        $statusTitle = $this->asString($row['status_title'] ?? '');
        $status = $this->normalizeStatusLabel($statusCode, $statusTitle);

        return new ScheduleAppointment(
            pid: $pid,
            name: $name,
            dob: $this->normalizeDob($this->asString($row['dob'] ?? '')),
            startTime: $startTime,
            title: $title,
            status: $status,
        );
    }

    private function normalizeStartTime(string $raw): ?string
    {
        $raw = trim($raw);
        if ($raw === '') {
            return null;
        }

        // Accept HH:MM or HH:MM:SS
        if (preg_match('/^(\d{1,2}):(\d{2})(?::\d{2})?$/', $raw, $matches) !== 1) {
            return null;
        }

        $hour = (int) $matches[1];
        $minute = (int) $matches[2];
        if ($hour < 0 || $hour > 23 || $minute < 0 || $minute > 59) {
            return null;
        }

        return sprintf('%02d:%02d', $hour, $minute);
    }

    private function normalizeDob(string $raw): string
    {
        $raw = trim($raw);
        if ($raw === '') {
            return '';
        }

        $parsed = DateTimeImmutable::createFromFormat('Y-m-d', substr($raw, 0, 10));
        if ($parsed instanceof DateTimeImmutable) {
            return $parsed->format('Y-m-d');
        }

        return $raw;
    }

    private function normalizeStatusLabel(string $statusCode, string $statusTitle): string
    {
        $title = trim($statusTitle);
        if ($title === '') {
            return $statusCode;
        }

        if ($statusCode !== '' && str_starts_with($title, $statusCode)) {
            $stripped = trim(substr($title, strlen($statusCode)));
            if ($stripped !== '') {
                return $stripped;
            }
        }

        return $title;
    }

    private function asString(mixed $value): string
    {
        if (is_string($value)) {
            return $value;
        }
        if (is_int($value) || is_float($value)) {
            return (string) $value;
        }

        return '';
    }
}
