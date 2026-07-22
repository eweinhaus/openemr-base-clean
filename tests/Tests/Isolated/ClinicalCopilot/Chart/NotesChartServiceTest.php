<?php

/**
 * Isolated unit tests for NotesChartService (mocked loaders / no DB).
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
use OpenEMR\ClinicalCopilot\Chart\NotesChartService;
use PHPUnit\Framework\Attributes\Small;
use PHPUnit\Framework\TestCase;

#[Small]
class NotesChartServiceTest extends TestCase
{
    public function testRecentFailsClosedOnInvalidPid(): void
    {
        $service = NotesChartService::createForTesting(static fn (): array => []);

        $this->expectException(InvalidArgumentException::class);
        $service->recent(-1);
    }

    public function testRecentReturnsEmptyFactsWhenNoNotes(): void
    {
        $service = NotesChartService::createForTesting(static fn (): array => []);

        $this->assertSame(['facts' => []], $service->recent(6)->toArray());
    }

    public function testRecentCapsAtThreeAndTruncatesExcerptTo500(): void
    {
        $longBody = str_repeat('A', 600);
        $rows = [];
        for ($i = 1; $i <= 5; ++$i) {
            $rows[] = [
                'id' => $i,
                'date' => sprintf('2026-07-%02d', $i),
                'description' => $i === 1 ? $longBody : "Note body {$i}",
                'codetext' => "Note type {$i}",
                'clinical_notes_type' => 'progress_note',
            ];
        }

        $capturedLimit = null;
        $service = NotesChartService::createForTesting(
            static function (int $pid, int $limit) use ($rows, &$capturedLimit): array {
                $capturedLimit = $limit;

                return $rows;
            },
        );

        $facts = $service->recent(6)->toArray()['facts'];

        $this->assertSame(3, $capturedLimit);
        $this->assertCount(3, $facts);
        $this->assertSame('form_clinical_notes', $facts[0]['table']);
        $this->assertSame('1', $facts[0]['id']);
        $this->assertSame(500, strlen($facts[0]['excerpt']));
        $this->assertStringStartsWith('AAA', $facts[0]['excerpt']);
    }

    public function testRecentStripsHtmlAndSkipsEmptyBodies(): void
    {
        $service = NotesChartService::createForTesting(
            static fn (): array => [
                [
                    'id' => 10,
                    'date' => '2026-07-01',
                    'description' => '<p>Patient <b>improving</b></p>',
                    'codetext' => 'Progress',
                    'clinical_notes_type' => 'progress_note',
                ],
                [
                    'id' => 11,
                    'date' => '2026-06-01',
                    'description' => '   ',
                    'codetext' => '',
                    'clinical_notes_type' => 'progress_note',
                ],
            ],
        );

        $facts = $service->recent(6)->toArray()['facts'];

        $this->assertCount(1, $facts);
        $this->assertStringContainsString('Patient improving', $facts[0]['text']);
        $this->assertStringNotContainsString('<p>', $facts[0]['excerpt']);
    }
}
