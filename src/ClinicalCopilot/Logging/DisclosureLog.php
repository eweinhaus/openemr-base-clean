<?php

/**
 * Append-only JSONL disclosure / verification log stub (no note bodies).
 *
 * @package   OpenEMR
 * @link      https://www.open-emr.org
 * @author    eweinhaus <eweinhaus@users.noreply.github.com>
 * @copyright Copyright (c) 2026 eweinhaus
 * @license   https://github.com/openemr/openemr/blob/master/LICENSE GNU General Public License 3
 */

declare(strict_types=1);

namespace OpenEMR\ClinicalCopilot\Logging;

use DateTimeImmutable;
use DateTimeZone;
use DomainException;

final class DisclosureLog
{
    /** @var list<string> */
    private const ALLOWED_OPTIONAL_KEYS = [
        'user_id',
        'pid',
        'tool',
        'pass',
        'reason',
    ];

    /** @var list<string> */
    private const FORBIDDEN_KEYS = [
        'message',
        'note',
        'body',
        'text',
        'chart',
        'payload',
    ];

    public function __construct(
        private readonly string $logFilePath,
    ) {
    }

    /**
     * @param array<string, mixed> $fields
     */
    public function write(array $fields): void
    {
        $record = $this->buildRecord($fields);
        $line = json_encode($record, JSON_THROW_ON_ERROR) . "\n";

        $directory = dirname($this->logFilePath);
        if (!is_dir($directory) && !mkdir($directory, 0775, true) && !is_dir($directory)) {
            throw new DomainException('Unable to create disclosure log directory');
        }

        if (file_put_contents($this->logFilePath, $line, FILE_APPEND | LOCK_EX) === false) {
            throw new DomainException('Unable to write disclosure log entry');
        }
    }

    /**
     * @param array<string, mixed> $fields
     *
     * @return array<string, bool|int|string>
     */
    private function buildRecord(array $fields): array
    {
        foreach (self::FORBIDDEN_KEYS as $forbiddenKey) {
            unset($fields[$forbiddenKey]);
        }

        $correlationId = $fields['correlation_id'] ?? null;
        if (!is_string($correlationId) || trim($correlationId) === '') {
            throw new DomainException('Disclosure log entry requires correlation_id');
        }

        $event = $fields['event'] ?? null;
        if (!is_string($event) || trim($event) === '') {
            throw new DomainException('Disclosure log entry requires event');
        }

        $timestamp = $fields['ts'] ?? null;
        if (!is_string($timestamp) || trim($timestamp) === '') {
            $timestamp = (new DateTimeImmutable('now', new DateTimeZone('UTC')))->format('Y-m-d\TH:i:s\Z');
        }

        /** @var array<string, bool|int|string> $record */
        $record = [
            'correlation_id' => $correlationId,
            'ts' => $timestamp,
            'event' => $event,
        ];

        foreach (self::ALLOWED_OPTIONAL_KEYS as $optionalKey) {
            if (!array_key_exists($optionalKey, $fields)) {
                continue;
            }

            $value = $fields[$optionalKey];
            if ($optionalKey === 'pass') {
                if (!is_bool($value)) {
                    continue;
                }
                $record[$optionalKey] = $value;
                continue;
            }

            if ($optionalKey === 'user_id' || $optionalKey === 'pid') {
                if (!is_int($value) && !(is_string($value) && ctype_digit($value))) {
                    continue;
                }
                $record[$optionalKey] = (int) $value;
                continue;
            }

            if (is_string($value) && $value !== '') {
                $record[$optionalKey] = $value;
            }
        }

        return $record;
    }
}
