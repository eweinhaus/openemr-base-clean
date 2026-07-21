<?php

/**
 * Sanitizes client-supplied chat transcript before gateway → sidecar.
 *
 * @package   OpenEMR
 * @link      https://www.open-emr.org
 * @author    eweinhaus <eweinhaus@users.noreply.github.com>
 * @copyright Copyright (c) 2026 eweinhaus
 * @license   https://github.com/openemr/openemr/blob/master/LICENSE GNU General Public License 3
 */

declare(strict_types=1);

namespace OpenEMR\ClinicalCopilot\Gateway;

final class TranscriptSanitizer
{
    public const MAX_ENTRIES = 20;

    public const MAX_TEXT_LENGTH = 4000;

    /** @var list<string> */
    private const ALLOWED_ROLES = ['user', 'assistant'];

    /**
     * @param list<mixed> $raw
     *
     * @return list<array{role: string, text: string}>
     */
    public static function sanitize(array $raw, int $maxEntries = self::MAX_ENTRIES): array
    {
        $out = [];
        foreach ($raw as $entry) {
            if (!is_array($entry)) {
                continue;
            }

            $role = $entry['role'] ?? null;
            if (!is_string($role) || !in_array($role, self::ALLOWED_ROLES, true)) {
                continue;
            }

            $text = $entry['text'] ?? null;
            if (!is_string($text)) {
                continue;
            }

            $text = trim($text);
            if ($text === '') {
                continue;
            }

            // Truncate by characters (not bytes) so UTF-8 stays valid for JSON encode.
            if (mb_strlen($text, 'UTF-8') > self::MAX_TEXT_LENGTH) {
                $text = mb_substr($text, 0, self::MAX_TEXT_LENGTH, 'UTF-8');
            }

            $out[] = [
                'role' => $role,
                'text' => $text,
            ];
        }

        if ($maxEntries < 1) {
            return [];
        }

        return array_values(array_slice($out, -$maxEntries));
    }
}
