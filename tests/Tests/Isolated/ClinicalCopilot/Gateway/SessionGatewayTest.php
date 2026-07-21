<?php

/**
 * Isolated unit tests for SessionGateway session binding.
 *
 * @package   OpenEMR
 * @link      https://www.open-emr.org
 * @author    eweinhaus <eweinhaus@users.noreply.github.com>
 * @copyright Copyright (c) 2026 eweinhaus
 * @license   https://github.com/openemr/openemr/blob/master/LICENSE GNU General Public License 3
 */

declare(strict_types=1);

namespace OpenEMR\Tests\Isolated\ClinicalCopilot\Gateway;

use DomainException;
use OpenEMR\ClinicalCopilot\Gateway\SessionContext;
use OpenEMR\ClinicalCopilot\Gateway\SessionGateway;
use PHPUnit\Framework\Attributes\DataProvider;
use PHPUnit\Framework\Attributes\Small;
use PHPUnit\Framework\TestCase;

#[Small]
class SessionGatewayTest extends TestCase
{
    public function testFromSessionValuesReturnsBoundPidFromSession(): void
    {
        $context = SessionGateway::fromSessionValues(42, 'clinician', 1001);

        $this->assertInstanceOf(SessionContext::class, $context);
        $this->assertSame(42, $context->userId);
        $this->assertSame('clinician', $context->username);
        $this->assertSame(1001, $context->pid);
        $this->assertTrue($context->isBound());
        $this->assertMatchesRegularExpression('/^[0-9a-f]{32}$/', $context->correlationId);
    }

    public function testFromSessionValuesReturnsUnboundWhenPidMissingOrNonPositive(): void
    {
        $missing = SessionGateway::fromSessionValues(7, 'user', null);
        $zero = SessionGateway::fromSessionValues(7, 'user', 0);
        $negative = SessionGateway::fromSessionValues(7, 'user', -5);
        $invalidString = SessionGateway::fromSessionValues(7, 'user', 'abc');

        foreach ([$missing, $zero, $negative, $invalidString] as $context) {
            $this->assertNull($context->pid);
            $this->assertFalse($context->isBound());
        }
    }

    public function testFromSessionValuesIgnoresRequestPid(): void
    {
        $context = SessionGateway::fromSessionValues(9, 'doctor', null, '9999');

        $this->assertNull($context->pid);
        $this->assertFalse($context->isBound());

        $boundContext = SessionGateway::fromSessionValues(9, 'doctor', 55, '9999');

        $this->assertSame(55, $boundContext->pid);
        $this->assertNotSame(9999, $boundContext->pid);
    }

    public function testFromSessionValuesMintsCorrelationIdWith32HexChars(): void
    {
        $first = SessionGateway::fromSessionValues(1, 'user', 10);
        $second = SessionGateway::fromSessionValues(1, 'user', 10);

        $this->assertSame(32, strlen($first->correlationId));
        $this->assertSame(32, strlen($second->correlationId));
        $this->assertNotSame($first->correlationId, $second->correlationId);
    }

    /**
     * @param mixed $authUserId
     * @param mixed $authUser
     */
    #[DataProvider('unauthenticatedProvider')]
    public function testFromSessionValuesThrowsWhenUnauthenticated(mixed $authUserId, mixed $authUser): void
    {
        $this->expectException(DomainException::class);

        SessionGateway::fromSessionValues($authUserId, $authUser, 1);
    }

    /**
     * @return array<string, array{mixed, mixed}>
     *
     * @codeCoverageIgnore Data providers run before coverage instrumentation starts.
     */
    public static function unauthenticatedProvider(): array
    {
        return [
            'empty username' => [1, ''],
            'null username' => [1, null],
            'whitespace username' => [1, '   '],
            'missing user id and username' => [null, null],
        ];
    }
}
