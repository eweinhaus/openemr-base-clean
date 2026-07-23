<?php

/**
 * Isolated unit tests for ClinicalDisplayDate.
 *
 * @package   OpenEMR
 * @link      https://www.open-emr.org
 * @author    eweinhaus <eweinhaus@users.noreply.github.com>
 * @copyright Copyright (c) 2026 eweinhaus
 * @license   https://github.com/openemr/openemr/blob/master/LICENSE GNU General Public License 3
 */

declare(strict_types=1);

namespace OpenEMR\Tests\Isolated\ClinicalCopilot;

use OpenEMR\ClinicalCopilot\ClinicalDisplayDate;
use PHPUnit\Framework\Attributes\DataProvider;
use PHPUnit\Framework\Attributes\Small;
use PHPUnit\Framework\TestCase;

#[Small]
class ClinicalDisplayDateTest extends TestCase
{
    #[DataProvider('formatProvider')]
    public function testFormat(mixed $input, string $expected): void
    {
        $this->assertSame($expected, ClinicalDisplayDate::format($input));
    }

    /**
     * @return array<string, array{mixed, string}>
     *
     * @codeCoverageIgnore Data providers run before coverage instrumentation starts.
     */
    public static function formatProvider(): array
    {
        return [
            'date only' => ['2026-01-18', 'Jan 18, 2026'],
            'datetime' => ['2026-01-18 09:30:00', 'Jan 18, 2026'],
            'med start date' => ['2020-12-13', 'Dec 13, 2020'],
            'empty' => ['', ''],
            'zero date' => ['0000-00-00', ''],
        ];
    }
}
