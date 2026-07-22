<?php

/**
 * Isolated unit tests for MedsChartService (mocked loaders / no DB).
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
use OpenEMR\ClinicalCopilot\Chart\MedsChartService;
use PHPUnit\Framework\Attributes\Small;
use PHPUnit\Framework\TestCase;

#[Small]
class MedsChartServiceTest extends TestCase
{
    public function testActiveWithAllergiesFailsClosedOnInvalidPid(): void
    {
        $service = MedsChartService::createForTesting(
            static fn (): array => [],
            static fn (): array => [],
        );

        $this->expectException(InvalidArgumentException::class);
        $service->activeWithAllergies(0);
    }

    public function testEmptyDomainReturnsEmptyFactsWithZeroMetaCounts(): void
    {
        $service = MedsChartService::createForTesting(
            static fn (): array => [],
            static fn (): array => [],
        );

        $payload = $service->activeWithAllergies(8)->toArray();

        $this->assertSame([], $payload['facts']);
        $this->assertSame(0, $payload['meta']['active_med_count']);
        $this->assertSame(0, $payload['meta']['allergy_count']);
    }

    public function testActiveMedFilterExcludesEndedPrescriptions(): void
    {
        $service = MedsChartService::createForTesting(
            static fn (): array => [
                [
                    'id' => 1,
                    'drug' => 'Metformin',
                    'dosage' => '500 mg',
                    'rxnorm_drugcode' => '860975',
                    'active' => '1',
                    'end_date' => null,
                    'start_date' => '2020-01-10',
                    'drug_dosage_instructions' => 'twice daily with meals',
                ],
                [
                    'id' => 2,
                    'drug' => 'Completed statin',
                    'dosage' => '20 mg',
                    'rxnorm_drugcode' => '123',
                    'active' => '1',
                    'end_date' => '2024-01-01',
                    'start_date' => '2022-01-01',
                    'drug_dosage_instructions' => '',
                ],
                [
                    'id' => 3,
                    'drug' => 'Inactive drug',
                    'dosage' => '5 mg',
                    'rxnorm_drugcode' => '456',
                    'active' => '0',
                    'end_date' => null,
                    'start_date' => '2021-01-01',
                    'drug_dosage_instructions' => '',
                ],
                [
                    'id' => 4,
                    'drug' => 'Open-ended zero date',
                    'dosage' => '10 mg',
                    'rxnorm_drugcode' => '789',
                    'active' => '1',
                    'end_date' => '0000-00-00',
                    'start_date' => '2019-01-01',
                    'drug_dosage_instructions' => 'daily',
                ],
            ],
            static fn (): array => [],
        );

        $payload = $service->activeWithAllergies(6)->toArray();
        $ids = array_column($payload['facts'], 'id');

        $this->assertSame(['1', '4'], $ids);
        $this->assertSame(2, $payload['meta']['active_med_count']);
        $this->assertSame(0, $payload['meta']['allergy_count']);
    }

    public function testMissingRxNormNeverInventedAndAllergiesIncluded(): void
    {
        $service = MedsChartService::createForTesting(
            static fn (): array => [
                [
                    'id' => 55,
                    'drug' => 'Lisinopril',
                    'dosage' => '10 mg',
                    'rxnorm_drugcode' => '',
                    'active' => '1',
                    'end_date' => null,
                    'start_date' => '2018-11-03',
                    'drug_dosage_instructions' => 'daily',
                ],
            ],
            static fn (): array => [
                [
                    'id' => 77,
                    'title' => 'Penicillin',
                    'reaction' => 'rash',
                    'comments' => '',
                ],
            ],
        );

        $payload = $service->activeWithAllergies(8)->toArray();

        $this->assertCount(2, $payload['facts']);
        $this->assertSame('prescriptions', $payload['facts'][0]['table']);
        $this->assertStringContainsString('RxNorm not on file — drug identity uncertain', $payload['facts'][0]['text']);
        $this->assertStringNotContainsString('RxNorm:', $payload['facts'][0]['text']);
        $this->assertSame('lists', $payload['facts'][1]['table']);
        $this->assertSame('77', $payload['facts'][1]['id']);
        $this->assertStringContainsString('Penicillin', $payload['facts'][1]['text']);
        $this->assertSame(1, $payload['meta']['active_med_count']);
        $this->assertSame(1, $payload['meta']['allergy_count']);
    }

    public function testActiveMedsCapAtTwentyKeepsAllAllergies(): void
    {
        $meds = [];
        for ($i = 1; $i <= 25; ++$i) {
            $meds[] = [
                'id' => $i,
                'drug' => "Drug {$i}",
                'dosage' => '1 mg',
                'rxnorm_drugcode' => (string) (1000 + $i),
                'active' => '1',
                'end_date' => null,
                'start_date' => sprintf('2020-01-%02d', min($i, 28)),
                'drug_dosage_instructions' => '',
            ];
        }

        $allergies = [
            ['id' => 901, 'title' => 'Latex', 'reaction' => '', 'comments' => ''],
            ['id' => 902, 'title' => 'Peanuts', 'reaction' => 'anaphylaxis', 'comments' => ''],
        ];

        $service = MedsChartService::createForTesting(
            static fn (): array => $meds,
            static fn (): array => $allergies,
        );

        $payload = $service->activeWithAllergies(6)->toArray();

        $medFacts = array_values(array_filter(
            $payload['facts'],
            static fn (array $f): bool => $f['table'] === 'prescriptions',
        ));
        $allergyFacts = array_values(array_filter(
            $payload['facts'],
            static fn (array $f): bool => $f['table'] === 'lists',
        ));

        $this->assertCount(20, $medFacts);
        $this->assertCount(2, $allergyFacts);
        $this->assertSame(20, $payload['meta']['active_med_count']);
        $this->assertSame(2, $payload['meta']['allergy_count']);
    }
}
