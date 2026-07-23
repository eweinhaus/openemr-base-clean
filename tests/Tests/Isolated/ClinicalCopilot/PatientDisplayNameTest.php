<?php

/**
 * Isolated unit tests for PatientDisplayName.
 *
 * @package   OpenEMR
 * @link      https://www.open-emr.org
 * @author    eweinhaus <eweinhaus@users.noreply.github.com>
 * @copyright Copyright (c) 2026 eweinhaus
 * @license   https://github.com/openemr/openemr/blob/master/LICENSE GNU General Public License 3
 */

declare(strict_types=1);

namespace OpenEMR\Tests\Isolated\ClinicalCopilot;

use OpenEMR\ClinicalCopilot\PatientDisplayName;
use PHPUnit\Framework\Attributes\DataProvider;
use PHPUnit\Framework\Attributes\Small;
use PHPUnit\Framework\TestCase;

#[Small]
class PatientDisplayNameTest extends TestCase
{
    #[DataProvider('sanitizePartProvider')]
    public function testSanitizePartStripsTrailingDigits(string $input, string $expected): void
    {
        $this->assertSame($expected, PatientDisplayName::sanitizePart($input));
    }

    /**
     * @return array<string, array{string, string}>
     *
     * @codeCoverageIgnore Data providers run before coverage instrumentation starts.
     */
    public static function sanitizePartProvider(): array
    {
        return [
            'synthea given name' => ['Gonzalo160', 'Gonzalo'],
            'synthea family name' => ['Wisozk929', 'Wisozk'],
            'multi-token given name' => ['Isabel214 Francisca', 'Isabel Francisca'],
            'plain name unchanged' => ['Susan', 'Susan'],
            'empty string' => ['', ''],
        ];
    }

    public function testFromPartsJoinsSanitizedNames(): void
    {
        $this->assertSame(
            'Gonzalo Wisozk',
            PatientDisplayName::fromParts('Gonzalo160', 'Wisozk929'),
        );
    }
}
