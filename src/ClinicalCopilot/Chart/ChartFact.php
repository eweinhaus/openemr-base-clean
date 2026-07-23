<?php

/**
 * Single chart fact locator for Ask Co-Pilot tool_proxy responses.
 *
 * @package   OpenEMR
 * @link      https://www.open-emr.org
 * @author    eweinhaus <eweinhaus@users.noreply.github.com>
 * @copyright Copyright (c) 2026 eweinhaus
 * @license   https://github.com/openemr/openemr/blob/master/LICENSE GNU General Public License 3
 */

declare(strict_types=1);

namespace OpenEMR\ClinicalCopilot\Chart;

use OpenEMR\Common\Uuid\UuidRegistry;

final readonly class ChartFact
{
    public function __construct(
        public string $text,
        public string $table,
        public string $id,
        public string $excerpt,
        public ?string $fhirUuid = null,
    ) {
    }

    /**
     * Convert a row uuid (string UUID or binary(16)) to a string FHIR id when present.
     */
    public static function uuidFromRowValue(mixed $raw): ?string
    {
        if (!is_string($raw) || $raw === '') {
            return null;
        }
        if (preg_match('/^[0-9a-fA-F-]{36}$/', $raw) === 1) {
            return strtolower($raw);
        }
        if (strlen($raw) === 16) {
            return UuidRegistry::uuidToString($raw);
        }

        return null;
    }

    /**
     * @return array{
     *     text: string,
     *     table: string,
     *     id: string,
     *     excerpt: string,
     *     fhir_uuid?: string
     * }
     */
    public function toArray(): array
    {
        $payload = [
            'text' => $this->text,
            'table' => $this->table,
            'id' => $this->id,
            'excerpt' => $this->excerpt,
        ];

        if ($this->fhirUuid !== null && $this->fhirUuid !== '') {
            $payload['fhir_uuid'] = $this->fhirUuid;
        }

        return $payload;
    }
}
