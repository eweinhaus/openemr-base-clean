<?php

/**
 * Isolated unit tests for SessionContext patient binding helpers.
 *
 * @package   OpenEMR
 * @link      https://www.open-emr.org
 * @author    eweinhaus <eweinhaus@users.noreply.github.com>
 * @copyright Copyright (c) 2026 eweinhaus
 * @license   https://github.com/openemr/openemr/blob/master/LICENSE GNU General Public License 3
 */

declare(strict_types=1);

namespace OpenEMR\Tests\Isolated\ClinicalCopilot\Gateway;

use OpenEMR\ClinicalCopilot\Gateway\SessionContext;
use PHPUnit\Framework\Attributes\DataProvider;
use PHPUnit\Framework\Attributes\Small;
use PHPUnit\Framework\TestCase;

#[Small]
class SessionContextTest extends TestCase
{
    #[DataProvider('isBoundProvider')]
    public function testIsBound(?int $pid, bool $expected): void
    {
        $context = new SessionContext(
            userId: 1,
            username: 'admin',
            pid: $pid,
            correlationId: 'corr-123',
        );

        $this->assertSame($expected, $context->isBound());
    }

    /**
     * @return array<string, array{?int, bool}>
     *
     * @codeCoverageIgnore Data providers run before coverage instrumentation starts.
     */
    public static function isBoundProvider(): array
    {
        return [
            'null pid is unbound' => [null, false],
            'zero pid is unbound' => [0, false],
            'negative pid is unbound' => [-1, false],
            'positive pid is bound' => [6, true],
        ];
    }
}
