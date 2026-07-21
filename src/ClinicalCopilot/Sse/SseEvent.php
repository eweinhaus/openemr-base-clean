<?php

/**
 * Formats Server-Sent Event frames for the Ask Co-Pilot hybrid SSE contract.
 *
 * @package   OpenEMR
 * @link      https://www.open-emr.org
 * @author    eweinhaus <eweinhaus@users.noreply.github.com>
 * @copyright Copyright (c) 2026 eweinhaus
 * @license   https://github.com/openemr/openemr/blob/master/LICENSE GNU General Public License 3
 */

declare(strict_types=1);

namespace OpenEMR\ClinicalCopilot\Sse;

use JsonException;

final class SseEvent
{
    /**
     * Build one SSE frame: event line, data line (JSON), terminating blank line.
     *
     * @param array<string, mixed> $data
     *
     * @throws JsonException When $data cannot be JSON-encoded
     */
    public static function format(string $event, array $data): string
    {
        $json = json_encode($data, JSON_THROW_ON_ERROR | JSON_UNESCAPED_UNICODE);

        return "event: {$event}\ndata: {$json}\n\n";
    }
}
