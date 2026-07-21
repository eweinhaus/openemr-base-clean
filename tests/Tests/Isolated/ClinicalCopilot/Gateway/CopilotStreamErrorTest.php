<?php

/**
 * Isolated unit tests for CopilotStreamError payload helpers.
 *
 * @package   OpenEMR
 * @link      https://www.open-emr.org
 * @author    eweinhaus <eweinhaus@users.noreply.github.com>
 * @copyright Copyright (c) 2026 eweinhaus
 * @license   https://github.com/openemr/openemr/blob/master/LICENSE GNU General Public License 3
 */

declare(strict_types=1);

namespace OpenEMR\Tests\Isolated\ClinicalCopilot\Gateway;

use OpenEMR\ClinicalCopilot\Gateway\CopilotStreamError;
use PHPUnit\Framework\Attributes\DataProvider;
use PHPUnit\Framework\Attributes\Small;
use PHPUnit\Framework\TestCase;
use RuntimeException;

#[Small]
class CopilotStreamErrorTest extends TestCase
{
    public function testPayloadIncludesMessageCodeAndCorrelationId(): void
    {
        $payload = CopilotStreamError::payload('gateway_misconfigured', 'corr-abc');

        self::assertSame('gateway_misconfigured', $payload['code']);
        self::assertSame('corr-abc', $payload['correlation_id']);
        self::assertStringContainsString('misconfigured', $payload['message']);
        self::assertArrayNotHasKey('detail', $payload);
    }

    public function testPayloadOptionalDetail(): void
    {
        $payload = CopilotStreamError::payload('sidecar_error', 'corr-1', 'connect');

        self::assertSame('connect', $payload['detail']);
    }

    /**
     * @return array<string, array{string, string}>
     *
     * @codeCoverageIgnore Data providers run before coverage instrumentation starts.
     */
    public static function codeFromThrowableProvider(): array
    {
        return [
            'unreachable' => ['sidecar_unreachable', 'sidecar_unreachable'],
            'timeout' => ['sidecar_timeout', 'sidecar_timeout'],
            'http' => ['sidecar_http_502', 'sidecar_http_502'],
            'fallback' => ['Connection refused to host', 'sidecar_error'],
        ];
    }

    #[DataProvider('codeFromThrowableProvider')]
    public function testCodeFromThrowable(string $exceptionMessage, string $expectedCode): void
    {
        self::assertSame(
            $expectedCode,
            CopilotStreamError::codeFromThrowable(new RuntimeException($exceptionMessage))
        );
    }

    public function testMessageForSidecarHttpIncludesStatus(): void
    {
        $message = CopilotStreamError::messageForCode('sidecar_http_503');

        self::assertStringContainsString('503', $message);
    }
}
