<?php

/**
 * Isolated unit tests for ChartFact / ChartFactSet serialization.
 *
 * @package   OpenEMR
 * @link      https://www.open-emr.org
 * @author    eweinhaus <eweinhaus@users.noreply.github.com>
 * @copyright Copyright (c) 2026 eweinhaus
 * @license   https://github.com/openemr/openemr/blob/master/LICENSE GNU General Public License 3
 */

declare(strict_types=1);

namespace OpenEMR\Tests\Isolated\ClinicalCopilot\Chart;

use OpenEMR\ClinicalCopilot\Chart\ChartFact;
use OpenEMR\ClinicalCopilot\Chart\ChartFactSet;
use PHPUnit\Framework\Attributes\Small;
use PHPUnit\Framework\TestCase;

#[Small]
class ChartFactTest extends TestCase
{
    public function testChartFactToArrayOmitsNullFhirUuid(): void
    {
        $fact = new ChartFact(
            text: 'Serum creatinine 1.1 mg/dL (2026-06-01)',
            table: 'procedure_result',
            id: '501',
            excerpt: 'CMP',
        );

        $this->assertSame(
            [
                'text' => 'Serum creatinine 1.1 mg/dL (2026-06-01)',
                'table' => 'procedure_result',
                'id' => '501',
                'excerpt' => 'CMP',
            ],
            $fact->toArray(),
        );
    }

    public function testChartFactToArrayIncludesFhirUuidWhenPresent(): void
    {
        $fact = new ChartFact(
            text: 'Active problem: Hypertension',
            table: 'lists',
            id: '42',
            excerpt: 'Problem list',
            fhirUuid: 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee',
        );

        $this->assertSame('aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee', $fact->toArray()['fhir_uuid']);
    }

    public function testChartFactSetSerializesFactsAndOptionalMeta(): void
    {
        $set = new ChartFactSet(
            facts: [
                new ChartFact('Med A', 'prescriptions', '1', 'Active Rx'),
                new ChartFact('Allergy: Penicillin', 'lists', '2', 'Allergy'),
            ],
            meta: [
                'active_med_count' => 1,
                'allergy_count' => 1,
            ],
        );

        $payload = $set->toArray();

        $this->assertCount(2, $payload['facts']);
        $this->assertSame('Med A', $payload['facts'][0]['text']);
        $this->assertSame(
            [
                'active_med_count' => 1,
                'allergy_count' => 1,
            ],
            $payload['meta'],
        );
    }

    public function testEmptyChartFactSetSerializesEmptyFactsWithoutMeta(): void
    {
        $set = new ChartFactSet(facts: []);

        $this->assertSame(['facts' => []], $set->toArray());
    }
}
