<?php

/**
 * Correlation bind record persisted for tool-proxy pid re-checks.
 *
 * @package   OpenEMR
 * @link      https://www.open-emr.org
 * @author    eweinhaus <eweinhaus@users.noreply.github.com>
 * @copyright Copyright (c) 2026 eweinhaus
 * @license   https://github.com/openemr/openemr/blob/master/LICENSE GNU General Public License 3
 */

declare(strict_types=1);

namespace OpenEMR\ClinicalCopilot\Gateway;

final readonly class CorrelationBind
{
    public function __construct(
        public int $pid,
        public int $userId,
        public int $expiresAt,
    ) {
    }
}
