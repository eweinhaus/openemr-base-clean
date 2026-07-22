<?php

/**
 * Isolated unit tests for LabsChartService (mocked loaders / no DB).
 *
 * @package   OpenEMR
 * @link      https://www.open-emr.org
 * @author    eweinhaus <eweinhaus@users.noreply.github.com>
 * @copyright Copyright (c) 2026 eweinhaus
 * @license   https://github.com/openemr/openemr/blob/master/LICENSE GNU General Public License 3
 */

declare(strict_types=1);

namespace OpenEMR\Tests\Isolated\ClinicalCopilot\Chart;

use InvalidArgumentException;
use OpenEMR\ClinicalCopilot\Chart\LabsChartService;
use PHPUnit\Framework\Attributes\Small;
use PHPUnit\Framework\TestCase;

#[Small]
class LabsChartServiceTest extends TestCase
{
    public function testRecentFailsClosedOnInvalidPid(): void
    {
        $service = LabsChartService::createForTesting(static fn (): array => []);

        $this->expectException(InvalidArgumentException::class);
        $service->recent(0);
    }

    public function testRecentReturnsEmptyFactsWhenNoResults(): void
    {
        $service = LabsChartService::createForTesting(static fn (): array => []);

        $this->assertSame(['facts' => []], $service->recent(6)->toArray());
    }

    public function testRecentCapsAtFifteenAndUsesProcedureResultLocator(): void
    {
        $rows = [];
        for ($i = 1; $i <= 20; ++$i) {
            $rows[] = [
                'procedure_result_id' => $i,
                'result_text' => "Analyte {$i}",
                'result' => (string) $i,
                'units' => 'mg/dL',
                'date' => '2026-06-01',
                'range' => '',
                'abnormal' => '',
                'procedure_name' => 'CMP',
            ];
        }

        $capturedLimit = null;
        $service = LabsChartService::createForTesting(
            static function (int $pid, int $limit) use ($rows, &$capturedLimit): array {
                $capturedLimit = $limit;

                return $rows;
            },
        );

        $facts = $service->recent(6)->toArray()['facts'];

        $this->assertSame(15, $capturedLimit);
        $this->assertCount(15, $facts);
        $this->assertSame('procedure_result', $facts[0]['table']);
        $this->assertSame('1', $facts[0]['id']);
        $this->assertSame('15', $facts[14]['id']);
        $this->assertStringContainsString('Analyte 1', $facts[0]['text']);
        $this->assertStringContainsString('mg/dL', $facts[0]['text']);
    }

    public function testRecentKeepsVarcharResultAndSurfacesAbnormalRangeOnlyWhenPresent(): void
    {
        $service = LabsChartService::createForTesting(
            static fn (): array => [
                [
                    'procedure_result_id' => 501,
                    'result_text' => 'Serum creatinine',
                    'result' => '1.1',
                    'units' => 'mg/dL',
                    'date' => '2026-06-01 08:00:00',
                    'range' => '0.6-1.2',
                    'abnormal' => 'no',
                    'procedure_name' => 'CMP',
                ],
                [
                    'procedure_result_id' => 502,
                    'result_text' => 'Free text result',
                    'result' => 'trace ketones',
                    'units' => '',
                    'date' => '2026-05-15',
                    'range' => '',
                    'abnormal' => '',
                    'procedure_name' => 'UA',
                ],
            ],
        );

        $facts = $service->recent(6)->toArray()['facts'];

        $this->assertStringContainsString('1.1', $facts[0]['text']);
        $this->assertStringContainsString('0.6-1.2', $facts[0]['text'] . ' ' . $facts[0]['excerpt']);
        $this->assertStringContainsString('trace ketones', $facts[1]['text']);
        $this->assertStringNotContainsString('abnormal', strtolower($facts[1]['text']));
        $this->assertStringNotContainsString('range', strtolower($facts[1]['excerpt']));
    }
}
