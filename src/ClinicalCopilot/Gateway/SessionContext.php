<?php

/**
 * Immutable session binding context for Clinical Co-Pilot gateway requests.
 *
 * @package   OpenEMR
 * @link      https://www.open-emr.org
 * @author    eweinhaus <eweinhaus@users.noreply.github.com>
 * @copyright Copyright (c) 2026 eweinhaus
 * @license   https://github.com/openemr/openemr/blob/master/LICENSE GNU General Public License 3
 */

declare(strict_types=1);

namespace OpenEMR\ClinicalCopilot\Gateway;

final readonly class SessionContext
{
    public function __construct(
        public int $userId,
        public string $username,
        public ?int $pid,
        public string $correlationId,
    ) {
    }

    public function isBound(): bool
    {
        return $this->pid !== null && $this->pid > 0;
    }
}
