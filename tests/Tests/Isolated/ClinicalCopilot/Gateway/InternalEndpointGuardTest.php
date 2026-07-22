<?php

/**
 * Isolated unit tests for InternalEndpointGuard private/loopback allowlist.
 *
 * @package   OpenEMR
 * @link      https://www.open-emr.org
 * @author    eweinhaus <eweinhaus@users.noreply.github.com>
 * @copyright Copyright (c) 2026 eweinhaus
 * @license   https://github.com/openemr/openemr/blob/master/LICENSE GNU General Public License 3
 */

declare(strict_types=1);

namespace OpenEMR\Tests\Isolated\ClinicalCopilot\Gateway;

use OpenEMR\ClinicalCopilot\Gateway\InternalEndpointGuard;
use PHPUnit\Framework\Attributes\DataProvider;
use PHPUnit\Framework\Attributes\Small;
use PHPUnit\Framework\TestCase;

#[Small]
class InternalEndpointGuardTest extends TestCase
{
    protected function tearDown(): void
    {
        putenv('COPILOT_INTERNAL_ENDPOINTS_PUBLIC');
        putenv('COPILOT_INTERNAL_ALLOW_CIDRS');
        parent::tearDown();
    }

    /**
     * @return array<string, array{string|null, bool}>
     *
     * @codeCoverageIgnore Data providers run before coverage instrumentation starts.
     */
    public static function defaultAllowProvider(): array
    {
        return [
            'loopback v4' => ['127.0.0.1', true],
            'loopback net' => ['127.0.0.42', true],
            'loopback v6' => ['::1', true],
            'docker bridge' => ['172.18.0.3', true],
            'rfc1918 10' => ['10.0.0.5', true],
            'rfc1918 192' => ['192.168.1.10', true],
            'mapped ipv4' => ['::ffff:172.18.0.2', true],
            'public v4' => ['8.8.8.8', false],
            'public v4 b' => ['1.2.3.4', false],
            'empty' => ['', false],
            'null' => [null, false],
            'garbage' => ['not-an-ip', false],
        ];
    }

    #[DataProvider('defaultAllowProvider')]
    public function testDefaultPrivateAllowlist(?string $addr, bool $expected): void
    {
        putenv('COPILOT_INTERNAL_ENDPOINTS_PUBLIC');
        putenv('COPILOT_INTERNAL_ALLOW_CIDRS');

        $this->assertSame(
            $expected,
            InternalEndpointGuard::isRemoteAddrAllowed($addr)
        );
    }

    public function testPublicEscapeHatchAllowsInternetAddr(): void
    {
        putenv('COPILOT_INTERNAL_ENDPOINTS_PUBLIC=1');

        $this->assertTrue(InternalEndpointGuard::isRemoteAddrAllowed('8.8.8.8'));
    }

    public function testExtraCidrAllowlist(): void
    {
        putenv('COPILOT_INTERNAL_ENDPOINTS_PUBLIC');
        putenv('COPILOT_INTERNAL_ALLOW_CIDRS=203.0.113.0/24,198.51.100.10');

        $this->assertTrue(InternalEndpointGuard::isRemoteAddrAllowed('203.0.113.50'));
        $this->assertTrue(InternalEndpointGuard::isRemoteAddrAllowed('198.51.100.10'));
        $this->assertFalse(InternalEndpointGuard::isRemoteAddrAllowed('198.51.100.11'));
        $this->assertFalse(InternalEndpointGuard::isRemoteAddrAllowed('8.8.8.8'));
    }
}
