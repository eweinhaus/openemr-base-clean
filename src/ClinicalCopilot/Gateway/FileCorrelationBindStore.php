<?php

/**
 * File-backed correlation bind store for single-worker gateway deployments.
 *
 * @package   OpenEMR
 * @link      https://www.open-emr.org
 * @author    eweinhaus <eweinhaus@users.noreply.github.com>
 * @copyright Copyright (c) 2026 eweinhaus
 * @license   https://github.com/openemr/openemr/blob/master/LICENSE GNU General Public License 3
 */

declare(strict_types=1);

namespace OpenEMR\ClinicalCopilot\Gateway;

use InvalidArgumentException;
use JsonException;
use RuntimeException;

final class FileCorrelationBindStore implements CorrelationBindStoreInterface
{
    public function __construct(
        private readonly string $directory,
    ) {
        if (!is_dir($this->directory)) {
            throw new RuntimeException('Correlation bind directory does not exist: ' . $this->directory);
        }

        if (!is_writable($this->directory)) {
            throw new RuntimeException('Correlation bind directory is not writable: ' . $this->directory);
        }
    }

    public function put(string $correlationId, int $pid, int $userId, int $ttlSeconds = 600): void
    {
        if ($ttlSeconds < 0) {
            throw new InvalidArgumentException('TTL seconds must be zero or positive');
        }

        $payload = json_encode([
            'pid' => $pid,
            'user_id' => $userId,
            'exp' => time() + $ttlSeconds,
        ], JSON_THROW_ON_ERROR);

        $path = $this->bindFilePath($correlationId);
        $written = file_put_contents($path, $payload, LOCK_EX);

        if ($written === false) {
            throw new RuntimeException('Failed to write correlation bind file: ' . $path);
        }
    }

    public function get(string $correlationId): ?CorrelationBind
    {
        $path = $this->bindFilePath($correlationId);

        if (!is_file($path)) {
            return null;
        }

        $contents = file_get_contents($path);
        if ($contents === false) {
            return null;
        }

        try {
            /** @var array{pid?: mixed, user_id?: mixed, exp?: mixed} $decoded */
            $decoded = json_decode($contents, true, 512, JSON_THROW_ON_ERROR);
        } catch (JsonException) {
            unlink($path);

            return null;
        }

        if (
            !isset($decoded['pid'], $decoded['user_id'], $decoded['exp'])
            || !is_int($decoded['pid'])
            || !is_int($decoded['user_id'])
            || !is_int($decoded['exp'])
        ) {
            unlink($path);

            return null;
        }

        if ($decoded['exp'] <= time()) {
            unlink($path);

            return null;
        }

        return new CorrelationBind(
            pid: $decoded['pid'],
            userId: $decoded['user_id'],
            expiresAt: $decoded['exp'],
        );
    }

    private function bindFilePath(string $correlationId): string
    {
        $safeName = preg_replace('/[^a-fA-F0-9]/', '', $correlationId) ?? '';

        if ($safeName === '') {
            throw new InvalidArgumentException('Correlation id contains no safe filename characters');
        }

        return $this->directory . DIRECTORY_SEPARATOR . $safeName . '.json';
    }
}
