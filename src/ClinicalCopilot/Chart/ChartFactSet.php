<?php

/**
 * Chart fact list (+ optional meta) for Ask Co-Pilot tool_proxy data payloads.
 *
 * @package   OpenEMR
 * @link      https://www.open-emr.org
 * @author    eweinhaus <eweinhaus@users.noreply.github.com>
 * @copyright Copyright (c) 2026 eweinhaus
 * @license   https://github.com/openemr/openemr/blob/master/LICENSE GNU General Public License 3
 */

declare(strict_types=1);

namespace OpenEMR\ClinicalCopilot\Chart;

final readonly class ChartFactSet
{
    /**
     * @param list<ChartFact> $facts
     * @param array<string, mixed>|null $meta
     */
    public function __construct(
        public array $facts,
        public ?array $meta = null,
    ) {
    }

    /**
     * @return array{
     *     facts: list<array{
     *         text: string,
     *         table: string,
     *         id: string,
     *         excerpt: string,
     *         fhir_uuid?: string
     *     }>,
     *     meta?: array<string, mixed>
     * }
     */
    public function toArray(): array
    {
        $payload = [
            'facts' => array_map(
                static fn (ChartFact $fact): array => $fact->toArray(),
                $this->facts,
            ),
        ];

        if ($this->meta !== null) {
            $payload['meta'] = $this->meta;
        }

        return $payload;
    }
}
