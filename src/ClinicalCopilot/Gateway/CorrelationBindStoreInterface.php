<?php

/**
 * Correlation bind store contract for session-proxy gateway pid re-checks.
 *
 * @package   OpenEMR
 * @link      https://www.open-emr.org
 * @author    eweinhaus <eweinhaus@users.noreply.github.com>
 * @copyright Copyright (c) 2026 eweinhaus
 * @license   https://github.com/openemr/openemr/blob/master/LICENSE GNU General Public License 3
 */

declare(strict_types=1);

namespace OpenEMR\ClinicalCopilot\Gateway;

interface CorrelationBindStoreInterface
{
    public function put(string $correlationId, int $pid, int $userId, int $ttlSeconds = 600): void;

    public function get(string $correlationId): ?CorrelationBind;
}
