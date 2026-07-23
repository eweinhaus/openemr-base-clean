<?php

/**
 * Human-readable patient names for Co-Pilot UI (schedule picker, chat header).
 *
 * Synthea imports often append numeric suffixes to given/family names
 * (e.g. Gonzalo160 Wisozk929). Strip those for physician-facing labels.
 *
 * @package   OpenEMR
 * @link      https://www.open-emr.org
 * @author    eweinhaus <eweinhaus@users.noreply.github.com>
 * @copyright Copyright (c) 2026 eweinhaus
 * @license   https://github.com/openemr/openemr/blob/master/LICENSE GNU General Public License 3
 */

declare(strict_types=1);

namespace OpenEMR\ClinicalCopilot;

final class PatientDisplayName
{
    public static function fromParts(string $fname, string $lname): string
    {
        $fname = self::sanitizePart(trim($fname));
        $lname = self::sanitizePart(trim($lname));

        return trim($fname . ' ' . $lname);
    }

    /**
     * Remove trailing digit runs Synthea adds to disambiguate synthetic names.
     * Handles multi-token given names (e.g. "Isabel214 Francisca" → "Isabel Francisca").
     */
    public static function sanitizePart(string $part): string
    {
        if ($part === '') {
            return '';
        }

        $tokens = preg_split('/\s+/', trim($part)) ?: [];
        $clean = [];
        foreach ($tokens as $token) {
            $stripped = preg_replace('/\d+$/', '', $token);
            if (!is_string($stripped)) {
                continue;
            }
            $stripped = trim($stripped);
            if ($stripped !== '') {
                $clean[] = $stripped;
            }
        }

        return implode(' ', $clean);
    }
}
