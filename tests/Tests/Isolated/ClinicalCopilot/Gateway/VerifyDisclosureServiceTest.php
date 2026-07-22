<?php

/**
 * Isolated unit tests for VerifyDisclosureService secret/bind/write path.
 *
 * @package   OpenEMR
 * @link      https://www.open-emr.org
 * @author    eweinhaus <eweinhaus@users.noreply.github.com>
 * @copyright Copyright (c) 2026 eweinhaus
 * @license   https://github.com/openemr/openemr/blob/master/LICENSE GNU General Public License 3
 */

declare(strict_types=1);

namespace OpenEMR\Tests\Isolated\ClinicalCopilot\Gateway;

use OpenEMR\ClinicalCopilot\Gateway\CorrelationBind;
use OpenEMR\ClinicalCopilot\Gateway\VerifyDisclosureService;
use OpenEMR\ClinicalCopilot\Logging\DisclosureLog;
use PHPUnit\Framework\Attributes\Small;
use PHPUnit\Framework\TestCase;
use RuntimeException;

#[Small]
class VerifyDisclosureServiceTest extends TestCase
{
    private const INTERNAL_SECRET = 'test-internal-secret';

    private FakeCorrelationBindStore $bindStore;

    private string $tempDir = '';

    private string $logPath = '';

    private DisclosureLog $disclosureLog;

    private VerifyDisclosureService $service;

    protected function setUp(): void
    {
        $this->bindStore = new FakeCorrelationBindStore();
        $this->tempDir = sys_get_temp_dir() . '/verify-disclosure-test-' . bin2hex(random_bytes(8));
        if (!mkdir($this->tempDir, 0777, true) && !is_dir($this->tempDir)) {
            throw new RuntimeException('Failed to create temp directory: ' . $this->tempDir);
        }

        $this->logPath = $this->tempDir . '/disclosure.jsonl';
        $this->disclosureLog = new DisclosureLog($this->logPath);
        $this->service = new VerifyDisclosureService(
            $this->bindStore,
            self::INTERNAL_SECRET,
            $this->disclosureLog,
        );
    }

    protected function tearDown(): void
    {
        if ($this->tempDir === '' || !is_dir($this->tempDir)) {
            return;
        }

        $entries = scandir($this->tempDir);
        if ($entries !== false) {
            foreach ($entries as $entry) {
                if ($entry === '.' || $entry === '..') {
                    continue;
                }
                unlink($this->tempDir . '/' . $entry);
            }
        }
        rmdir($this->tempDir);
    }

    public function testHandleWritesVerifyLineWhenSecretAndBindMatch(): void
    {
        $correlationId = 'abc123correlationid00000001';
        $this->bindStore->put($correlationId, 100, 7);

        $result = $this->service->handle(
            [
                'event' => 'verify',
                'pass' => true,
                'reason' => 'ok',
            ],
            self::INTERNAL_SECRET,
            $correlationId,
        );

        $this->assertTrue($result['ok']);
        $this->assertFileExists($this->logPath);

        $lines = file($this->logPath, FILE_IGNORE_NEW_LINES | FILE_SKIP_EMPTY_LINES);
        $this->assertIsArray($lines);
        $this->assertCount(1, $lines);

        $decoded = json_decode((string) $lines[0], true, 512, JSON_THROW_ON_ERROR);
        $this->assertSame('verify', $decoded['event']);
        $this->assertSame($correlationId, $decoded['correlation_id']);
        $this->assertTrue($decoded['pass']);
        $this->assertSame('ok', $decoded['reason']);
        $this->assertArrayNotHasKey('message', $decoded);
        $this->assertArrayNotHasKey('text', $decoded);
    }

    public function testHandleWritesPassFalseWithShortReason(): void
    {
        $correlationId = 'abc123correlationid00000002';
        $this->bindStore->put($correlationId, 55, 3);

        $result = $this->service->handle(
            [
                'event' => 'verify',
                'pass' => false,
                'reason' => 'empty_verified',
            ],
            self::INTERNAL_SECRET,
            $correlationId,
        );

        $this->assertTrue($result['ok']);
        $decoded = json_decode((string) file_get_contents($this->logPath), true, 512, JSON_THROW_ON_ERROR);
        $this->assertFalse($decoded['pass']);
        $this->assertSame('empty_verified', $decoded['reason']);
    }

    public function testHandleFailsWhenSecretDoesNotMatch(): void
    {
        $correlationId = 'abc123correlationid00000003';
        $this->bindStore->put($correlationId, 100, 7);

        $result = $this->service->handle(
            [
                'event' => 'verify',
                'pass' => true,
                'reason' => 'ok',
            ],
            'wrong-secret',
            $correlationId,
        );

        $this->assertFalse($result['ok']);
        $this->assertSame('unauthorized', $result['error']);
        $this->assertFileDoesNotExist($this->logPath);
    }

    public function testHandleFailsWhenBindIsMissing(): void
    {
        $result = $this->service->handle(
            [
                'event' => 'verify',
                'pass' => true,
                'reason' => 'ok',
            ],
            self::INTERNAL_SECRET,
            'missing-correlation-id',
        );

        $this->assertFalse($result['ok']);
        $this->assertSame('bind_missing', $result['error']);
        $this->assertFileDoesNotExist($this->logPath);
    }

    public function testHandleFailsWhenBindIsExpired(): void
    {
        $correlationId = 'abc123correlationid00000004';
        $this->bindStore->putBind(
            $correlationId,
            new CorrelationBind(pid: 100, userId: 7, expiresAt: time() - 1),
        );

        $result = $this->service->handle(
            [
                'event' => 'verify',
                'pass' => true,
                'reason' => 'ok',
            ],
            self::INTERNAL_SECRET,
            $correlationId,
        );

        $this->assertFalse($result['ok']);
        $this->assertSame('bind_missing', $result['error']);
        $this->assertFileDoesNotExist($this->logPath);
    }

    public function testHandleUsesCorrelationIdFromBodyWhenHeaderEmpty(): void
    {
        $correlationId = 'abc123correlationid00000005';
        $this->bindStore->put($correlationId, 42, 1);

        $result = $this->service->handle(
            [
                'event' => 'verify',
                'correlation_id' => $correlationId,
                'pass' => true,
                'reason' => 'ok',
            ],
            self::INTERNAL_SECRET,
            '',
        );

        $this->assertTrue($result['ok']);
        $decoded = json_decode((string) file_get_contents($this->logPath), true, 512, JSON_THROW_ON_ERROR);
        $this->assertSame($correlationId, $decoded['correlation_id']);
    }

    public function testHandlePrefersCorrelationIdFromHeaderOverBody(): void
    {
        $headerCorrelationId = 'abc123correlationid00000006';
        $this->bindStore->put($headerCorrelationId, 42, 1);

        $result = $this->service->handle(
            [
                'event' => 'verify',
                'correlation_id' => 'other-correlation-id',
                'pass' => true,
                'reason' => 'ok',
            ],
            self::INTERNAL_SECRET,
            $headerCorrelationId,
        );

        $this->assertTrue($result['ok']);
        $decoded = json_decode((string) file_get_contents($this->logPath), true, 512, JSON_THROW_ON_ERROR);
        $this->assertSame($headerCorrelationId, $decoded['correlation_id']);
    }

    public function testHandleFailsWhenCorrelationIdMissing(): void
    {
        $result = $this->service->handle(
            [
                'event' => 'verify',
                'pass' => true,
                'reason' => 'ok',
            ],
            self::INTERNAL_SECRET,
            '',
        );

        $this->assertFalse($result['ok']);
        $this->assertSame('invalid_request', $result['error']);
        $this->assertFileDoesNotExist($this->logPath);
    }

    public function testHandleFailsWhenEventIsNotVerify(): void
    {
        $correlationId = 'abc123correlationid00000007';
        $this->bindStore->put($correlationId, 100, 7);

        $result = $this->service->handle(
            [
                'event' => 'tool_proxy',
                'pass' => true,
                'reason' => 'ok',
            ],
            self::INTERNAL_SECRET,
            $correlationId,
        );

        $this->assertFalse($result['ok']);
        $this->assertSame('invalid_request', $result['error']);
        $this->assertFileDoesNotExist($this->logPath);
    }

    public function testHandleFailsWhenPassIsNotBool(): void
    {
        $correlationId = 'abc123correlationid00000008';
        $this->bindStore->put($correlationId, 100, 7);

        $result = $this->service->handle(
            [
                'event' => 'verify',
                'pass' => 'true',
                'reason' => 'ok',
            ],
            self::INTERNAL_SECRET,
            $correlationId,
        );

        $this->assertFalse($result['ok']);
        $this->assertSame('invalid_request', $result['error']);
        $this->assertFileDoesNotExist($this->logPath);
    }

    public function testHandleFailsWhenReasonMissingOrEmpty(): void
    {
        $correlationId = 'abc123correlationid00000009';
        $this->bindStore->put($correlationId, 100, 7);

        $missing = $this->service->handle(
            [
                'event' => 'verify',
                'pass' => true,
            ],
            self::INTERNAL_SECRET,
            $correlationId,
        );
        $empty = $this->service->handle(
            [
                'event' => 'verify',
                'pass' => true,
                'reason' => '   ',
            ],
            self::INTERNAL_SECRET,
            $correlationId,
        );

        $this->assertFalse($missing['ok']);
        $this->assertSame('invalid_request', $missing['error']);
        $this->assertFalse($empty['ok']);
        $this->assertSame('invalid_request', $empty['error']);
        $this->assertFileDoesNotExist($this->logPath);
    }

    public function testHandleFailsWhenReasonIsTooLong(): void
    {
        $correlationId = 'abc123correlationid00000010';
        $this->bindStore->put($correlationId, 100, 7);

        $result = $this->service->handle(
            [
                'event' => 'verify',
                'pass' => false,
                'reason' => str_repeat('a', 65),
            ],
            self::INTERNAL_SECRET,
            $correlationId,
        );

        $this->assertFalse($result['ok']);
        $this->assertSame('invalid_request', $result['error']);
        $this->assertFileDoesNotExist($this->logPath);
    }

    public function testHandleStripsForbiddenKeysFromWrittenLine(): void
    {
        $correlationId = 'abc123correlationid00000011';
        $this->bindStore->put($correlationId, 100, 7);

        $result = $this->service->handle(
            [
                'event' => 'verify',
                'pass' => false,
                'reason' => 'claims_dropped',
                'message' => 'must not appear',
                'text' => 'clinical claim',
                'payload' => ['x' => 1],
            ],
            self::INTERNAL_SECRET,
            $correlationId,
        );

        $this->assertTrue($result['ok']);
        $decoded = json_decode((string) file_get_contents($this->logPath), true, 512, JSON_THROW_ON_ERROR);
        $this->assertSame('claims_dropped', $decoded['reason']);
        $this->assertArrayNotHasKey('message', $decoded);
        $this->assertArrayNotHasKey('text', $decoded);
        $this->assertArrayNotHasKey('payload', $decoded);
    }
}
