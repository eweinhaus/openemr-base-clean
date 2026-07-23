<?php

/**
 * Isolated unit tests for PatientContextService (mocked loaders / no DB).
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
use OpenEMR\ClinicalCopilot\Chart\PatientContextService;
use PHPUnit\Framework\Attributes\Small;
use PHPUnit\Framework\TestCase;

#[Small]
class PatientContextServiceTest extends TestCase
{
    public function testSnapshotFailsClosedOnInvalidPid(): void
    {
        $service = PatientContextService::createForTesting(
            static fn (): ?array => null,
            static fn (): array => [],
        );

        $this->expectException(InvalidArgumentException::class);
        $service->snapshot(0);
    }

    public function testSnapshotReturnsEmptyFactsWhenNoEncounterOrProblems(): void
    {
        $service = PatientContextService::createForTesting(
            static fn (): ?array => null,
            static fn (): array => [],
        );

        $set = $service->snapshot(6);

        $this->assertSame(['facts' => []], $set->toArray());
    }

    public function testSnapshotIncludesLastVisitReasonAndActiveProblemsOnly(): void
    {
        $service = PatientContextService::createForTesting(
            static fn (int $pid): ?array => [
                'id' => 88,
                'encounter' => 1200,
                'date' => '2026-01-18 09:30:00',
                'reason' => 'Encounter for check up (procedure)',
            ],
            static fn (int $pid): array => [
                [
                    'id' => 101,
                    'title' => 'Type 2 diabetes mellitus',
                    'diagnosis' => 'ICD10:E11.9',
                    'begdate' => '2019-03-14',
                ],
                [
                    'id' => 103,
                    'title' => 'Essential hypertension',
                    'diagnosis' => '',
                    'begdate' => '2017-08-02',
                ],
            ],
        );

        $facts = $service->snapshot(6)->toArray()['facts'];

        $this->assertCount(3, $facts);
        $this->assertSame('form_encounter', $facts[0]['table']);
        $this->assertSame('88', $facts[0]['id']);
        $this->assertStringContainsString('Jan 18, 2026', $facts[0]['text']);
        $this->assertStringContainsString('Encounter for check up (procedure)', $facts[0]['text']);

        $this->assertSame('lists', $facts[1]['table']);
        $this->assertSame('101', $facts[1]['id']);
        $this->assertStringContainsString('Type 2 diabetes mellitus', $facts[1]['text']);
        $this->assertStringNotContainsString('ICD10', $facts[1]['text']);
        $this->assertStringContainsString('Essential hypertension', $facts[2]['text']);

        foreach ($facts as $fact) {
            $this->assertNotSame('allergy', strtolower($fact['excerpt']));
            $this->assertStringNotContainsString('allergy', strtolower($fact['text']));
            $this->assertNotSame('prescriptions', $fact['table']);
            $this->assertNotSame('procedure_result', $fact['table']);
            $this->assertNotSame('form_clinical_notes', $fact['table']);
        }
    }

    public function testSnapshotOmitsDemographicsAndAllowsVisitWithoutProblems(): void
    {
        $service = PatientContextService::createForTesting(
            static fn (): ?array => [
                'id' => 9,
                'date' => '2025-12-01',
                'reason' => '',
            ],
            static fn (): array => [],
        );

        $facts = $service->snapshot(8)->toArray()['facts'];

        $this->assertCount(1, $facts);
        $this->assertSame('form_encounter', $facts[0]['table']);
        $this->assertStringNotContainsString('fname', strtolower($facts[0]['text']));
        $this->assertStringNotContainsString('dob', strtolower($facts[0]['text']));
    }
}
