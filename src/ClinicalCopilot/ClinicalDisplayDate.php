<?php

/**
 * Physician-facing dates for Clinical Co-Pilot chart facts and citations.
 *
 * @package   OpenEMR
 * @link      https://www.open-emr.org
 * @author    eweinhaus <eweinhaus@users.noreply.github.com>
 * @copyright Copyright (c) 2026 eweinhaus
 * @license   https://github.com/openemr/openemr/blob/master/LICENSE GNU General Public License 3
 */

declare(strict_types=1);

namespace OpenEMR\ClinicalCopilot;

use DateTimeImmutable;

final class ClinicalDisplayDate
{
    /**
     * Format a DB datetime/date for chat and citation text (e.g. Jan 18, 2026).
     */
    public static function format(mixed $value): string
    {
        $raw = trim(self::asString($value));
        if ($raw === '' || str_starts_with($raw, '0000-00-00')) {
            return '';
        }

        $dateOnly = substr($raw, 0, 10);
        $parsed = DateTimeImmutable::createFromFormat('Y-m-d', $dateOnly);
        if ($parsed instanceof DateTimeImmutable) {
            return $parsed->format('M j, Y');
        }

        try {
            return (new DateTimeImmutable($raw))->format('M j, Y');
        } catch (\Exception) {
            return $dateOnly;
        }
    }

    private static function asString(mixed $value): string
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
