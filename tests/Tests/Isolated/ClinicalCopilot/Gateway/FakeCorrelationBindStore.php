<?php

/**
 * In-memory correlation bind store for isolated gateway tests.
 *
 * @package   OpenEMR
 * @link      https://www.open-emr.org
 * @author    eweinhaus <eweinhaus@users.noreply.github.com>
 * @copyright Copyright (c) 2026 eweinhaus
 * @license   https://github.com/openemr/openemr/blob/master/LICENSE GNU General Public License 3
 */

declare(strict_types=1);

namespace OpenEMR\Tests\Isolated\ClinicalCopilot\Gateway;

use OpenEMR\ClinicalCopilot\Gateway\CorrelationBind;
use OpenEMR\ClinicalCopilot\Gateway\CorrelationBindStoreInterface;

final class FakeCorrelationBindStore implements CorrelationBindStoreInterface
{
    /** @var array<string, CorrelationBind> */
    private array $binds = [];

    public function put(string $correlationId, int $pid, int $userId, int $ttlSeconds = 600): void
    {
        $this->binds[$correlationId] = new CorrelationBind(
            pid: $pid,
            userId: $userId,
            expiresAt: time() + $ttlSeconds,
        );
    }

    public function putBind(string $correlationId, CorrelationBind $bind): void
    {
        $this->binds[$correlationId] = $bind;
    }

    public function get(string $correlationId): ?CorrelationBind
    {
        $bind = $this->binds[$correlationId] ?? null;
        if ($bind === null) {
            return null;
        }

        if ($bind->expiresAt <= time()) {
            return null;
        }

        return $bind;
    }
}
