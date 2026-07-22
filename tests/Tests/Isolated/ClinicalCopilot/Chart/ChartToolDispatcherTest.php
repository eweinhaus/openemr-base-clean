<?php

/**
 * Isolated unit tests for ChartToolDispatcher tool-name mapping.
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
use OpenEMR\ClinicalCopilot\Chart\ChartToolDispatcher;
use OpenEMR\ClinicalCopilot\Chart\LabsChartService;
use OpenEMR\ClinicalCopilot\Chart\MedsChartService;
use OpenEMR\ClinicalCopilot\Chart\NotesChartService;
use OpenEMR\ClinicalCopilot\Chart\PatientContextService;
use PHPUnit\Framework\Attributes\DataProvider;
use PHPUnit\Framework\Attributes\Small;
use PHPUnit\Framework\TestCase;

#[Small]
class ChartToolDispatcherTest extends TestCase
{
    /**
     * @return array<string, array{string, string}>
     *
     * @codeCoverageIgnore Data providers run before coverage instrumentation starts.
     */
    public static function toolMappingProvider(): array
    {
        return [
            'patient_context' => ['patient_context', 'form_encounter'],
            'labs' => ['labs', 'procedure_result'],
            'meds' => ['meds', 'prescriptions'],
            'notes' => ['notes', 'form_clinical_notes'],
        ];
    }

    #[DataProvider('toolMappingProvider')]
    public function testDispatchMapsToolNames(string $tool, string $expectedTable): void
    {
        $dispatcher = $this->createDispatcher();

        $set = $dispatcher->dispatch($tool, 6);
        $facts = $set->toArray()['facts'];

        $this->assertNotEmpty($facts);
        $this->assertSame($expectedTable, $facts[0]['table']);
    }

    public function testDispatchUnknownToolThrows(): void
    {
        $dispatcher = $this->createDispatcher();

        $this->expectException(InvalidArgumentException::class);
        $this->expectExceptionMessage('Unknown chart tool');
        $dispatcher->dispatch('patient_context_stub', 6);
    }

    private function createDispatcher(): ChartToolDispatcher
    {
        $context = PatientContextService::createForTesting(
            static fn (): ?array => [
                'id' => 1,
                'date' => '2026-01-01',
                'reason' => 'Follow-up',
            ],
            static fn (): array => [],
        );
        $labs = LabsChartService::createForTesting(
            static fn (): array => [
                [
                    'procedure_result_id' => 9,
                    'result_text' => 'Creatinine',
                    'result' => '1.0',
                    'units' => 'mg/dL',
                    'date' => '2026-06-01',
                    'range' => '',
                    'abnormal' => '',
                    'procedure_name' => 'CMP',
                ],
            ],
        );
        $meds = MedsChartService::createForTesting(
            static fn (): array => [
                [
                    'id' => 3,
                    'drug' => 'Metformin',
                    'dosage' => '500 mg',
                    'rxnorm_drugcode' => '860975',
                    'active' => '1',
                    'end_date' => null,
                    'start_date' => '2020-01-01',
                    'drug_dosage_instructions' => '',
                ],
            ],
            static fn (): array => [],
        );
        $notes = NotesChartService::createForTesting(
            static fn (): array => [
                [
                    'id' => 4,
                    'date' => '2026-07-01',
                    'description' => 'Progress note body',
                    'codetext' => 'Progress',
                    'clinical_notes_type' => 'progress_note',
                ],
            ],
        );

        return new ChartToolDispatcher($context, $labs, $meds, $notes);
    }
}
