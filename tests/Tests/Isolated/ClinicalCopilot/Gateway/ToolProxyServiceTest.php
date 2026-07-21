<?php

/**
 * Isolated unit tests for ToolProxyService pid fail-closed re-checks.
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
use OpenEMR\ClinicalCopilot\Gateway\ToolProxyService;
use OpenEMR\ClinicalCopilot\Logging\DisclosureLog;
use PHPUnit\Framework\Attributes\Small;
use PHPUnit\Framework\TestCase;
use RuntimeException;

#[Small]
class ToolProxyServiceTest extends TestCase
{
    private const INTERNAL_SECRET = 'test-internal-secret';

    private FakeCorrelationBindStore $bindStore;

    private ToolProxyService $service;

    protected function setUp(): void
    {
        $this->bindStore = new FakeCorrelationBindStore();
        $this->service = new ToolProxyService($this->bindStore, self::INTERNAL_SECRET);
    }

    public function testHandlePassesWhenSecretPidAndBindMatch(): void
    {
        $correlationId = 'abc123correlationid00000001';
        $this->bindStore->put($correlationId, 100, 7);

        $result = $this->service->handle(
            [
                'tool' => 'patient_context_stub',
                'pid' => 100,
                'user_id' => 7,
            ],
            self::INTERNAL_SECRET,
            $correlationId,
        );

        $this->assertTrue($result['ok']);
        $this->assertSame('patient_context_stub', $result['tool']);
        $this->assertArrayHasKey('facts', $result['data']);
        $this->assertCount(3, $result['data']['facts']);
        $this->assertSame('lists', $result['data']['facts'][0]['table']);
        $this->assertSame('101', $result['data']['facts'][0]['id']);
        $this->assertSame('lists', $result['data']['facts'][1]['table']);
        $this->assertSame('102', $result['data']['facts'][1]['id']);
        $this->assertSame('lists', $result['data']['facts'][2]['table']);
        $this->assertSame('103', $result['data']['facts'][2]['id']);
    }

    public function testHandleReturnsLabsStubFactsWithLocators(): void
    {
        $correlationId = 'abc123correlationid00000011';
        $this->bindStore->put($correlationId, 100, 7);

        $result = $this->service->handle(
            [
                'tool' => 'labs_stub',
                'pid' => 100,
                'user_id' => 7,
            ],
            self::INTERNAL_SECRET,
            $correlationId,
        );

        $this->assertTrue($result['ok']);
        $this->assertSame('labs_stub', $result['tool']);
        $this->assertCount(3, $result['data']['facts']);
        $this->assertSame('procedure_result', $result['data']['facts'][0]['table']);
        $this->assertSame('501', $result['data']['facts'][0]['id']);
        $this->assertSame('procedure_result', $result['data']['facts'][1]['table']);
        $this->assertSame('502', $result['data']['facts'][1]['id']);
        $this->assertSame('procedure_result', $result['data']['facts'][2]['table']);
        $this->assertSame('503', $result['data']['facts'][2]['id']);
    }

    public function testHandleReturnsMedsStubFactsWithLocators(): void
    {
        $correlationId = 'abc123correlationid00000012';
        $this->bindStore->put($correlationId, 100, 7);

        $result = $this->service->handle(
            [
                'tool' => 'meds_stub',
                'pid' => 100,
                'user_id' => 7,
            ],
            self::INTERNAL_SECRET,
            $correlationId,
        );

        $this->assertTrue($result['ok']);
        $this->assertSame('meds_stub', $result['tool']);
        $this->assertCount(2, $result['data']['facts']);
        $this->assertSame('prescriptions', $result['data']['facts'][0]['table']);
        $this->assertSame('201', $result['data']['facts'][0]['id']);
        $this->assertSame('prescriptions', $result['data']['facts'][1]['table']);
        $this->assertSame('202', $result['data']['facts'][1]['id']);
    }

    public function testHandleFailsWhenSecretDoesNotMatch(): void
    {
        $correlationId = 'abc123correlationid00000002';
        $this->bindStore->put($correlationId, 100, 7);

        $result = $this->service->handle(
            [
                'tool' => 'patient_context_stub',
                'pid' => 100,
                'user_id' => 7,
            ],
            'wrong-secret',
            $correlationId,
        );

        $this->assertFalse($result['ok']);
        $this->assertSame('unauthorized', $result['error']);
    }

    public function testHandleFailsWhenPidDoesNotMatchBind(): void
    {
        $correlationId = 'abc123correlationid00000003';
        $this->bindStore->put($correlationId, 100, 7);

        $result = $this->service->handle(
            [
                'tool' => 'patient_context_stub',
                'pid' => 999,
                'user_id' => 7,
            ],
            self::INTERNAL_SECRET,
            $correlationId,
        );

        $this->assertFalse($result['ok']);
        $this->assertSame('pid_mismatch', $result['error']);
    }

    public function testHandleFailsWhenBindIsMissing(): void
    {
        $result = $this->service->handle(
            [
                'tool' => 'patient_context_stub',
                'pid' => 100,
                'user_id' => 7,
            ],
            self::INTERNAL_SECRET,
            'missing-correlation-id',
        );

        $this->assertFalse($result['ok']);
        $this->assertSame('bind_missing', $result['error']);
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
                'tool' => 'patient_context_stub',
                'pid' => 100,
                'user_id' => 7,
            ],
            self::INTERNAL_SECRET,
            $correlationId,
        );

        $this->assertFalse($result['ok']);
        $this->assertSame('bind_missing', $result['error']);
    }

    public function testHandleUsesCorrelationIdFromBodyWhenHeaderEmpty(): void
    {
        $correlationId = 'abc123correlationid00000005';
        $this->bindStore->put($correlationId, 55, 3);

        $result = $this->service->handle(
            [
                'tool' => 'patient_context_stub',
                'pid' => 55,
                'user_id' => 3,
                'correlation_id' => $correlationId,
            ],
            self::INTERNAL_SECRET,
            '',
        );

        $this->assertTrue($result['ok']);
        $this->assertSame('patient_context_stub', $result['tool']);
    }

    public function testHandlePrefersCorrelationIdFromHeaderOverBody(): void
    {
        $headerCorrelationId = 'abc123correlationid00000006';
        $this->bindStore->put($headerCorrelationId, 42, 1);

        $result = $this->service->handle(
            [
                'tool' => 'patient_context_stub',
                'pid' => 42,
                'user_id' => 1,
                'correlation_id' => 'other-correlation-id',
            ],
            self::INTERNAL_SECRET,
            $headerCorrelationId,
        );

        $this->assertTrue($result['ok']);
    }

    public function testHandleFailsWhenRequiredFieldsAreMissing(): void
    {
        $missingTool = $this->service->handle(
            ['pid' => 100],
            self::INTERNAL_SECRET,
            'abc123correlationid00000007',
        );
        $missingPid = $this->service->handle(
            ['tool' => 'patient_context_stub'],
            self::INTERNAL_SECRET,
            'abc123correlationid00000008',
        );
        $missingCorrelation = $this->service->handle(
            [
                'tool' => 'patient_context_stub',
                'pid' => 100,
                'user_id' => 7,
            ],
            self::INTERNAL_SECRET,
            '',
        );

        $this->assertFalse($missingTool['ok']);
        $this->assertSame('invalid_request', $missingTool['error']);
        $this->assertFalse($missingPid['ok']);
        $this->assertSame('invalid_request', $missingPid['error']);
        $this->assertFalse($missingCorrelation['ok']);
        $this->assertSame('invalid_request', $missingCorrelation['error']);
    }

    public function testHandleFailsWhenUserIdDoesNotMatchBind(): void
    {
        $correlationId = 'abc123correlationid00000013';
        $this->bindStore->put($correlationId, 100, 7);

        $result = $this->service->handle(
            [
                'tool' => 'patient_context_stub',
                'pid' => 100,
                'user_id' => 99,
            ],
            self::INTERNAL_SECRET,
            $correlationId,
        );

        $this->assertFalse($result['ok']);
        $this->assertSame('user_mismatch', $result['error']);
    }

    public function testHandleReturnsNotImplementedForUnknownToolAfterBindCheck(): void
    {
        $correlationId = 'abc123correlationid00000009';
        $this->bindStore->put($correlationId, 100, 7);

        $result = $this->service->handle(
            [
                'tool' => 'unknown_tool',
                'pid' => 100,
                'user_id' => 7,
            ],
            self::INTERNAL_SECRET,
            $correlationId,
        );

        $this->assertFalse($result['ok']);
        $this->assertSame('not_implemented', $result['error']);
    }

    public function testHandleWritesDisclosureLogOnPassAndFail(): void
    {
        $tempDir = sys_get_temp_dir() . '/tool-proxy-log-test-' . bin2hex(random_bytes(8));
        if (!mkdir($tempDir, 0777, true) && !is_dir($tempDir)) {
            throw new RuntimeException('Failed to create temp directory: ' . $tempDir);
        }

        $logPath = $tempDir . '/disclosure.jsonl';
        $disclosureLog = new DisclosureLog($logPath);
        $service = new ToolProxyService($this->bindStore, self::INTERNAL_SECRET, $disclosureLog);

        $correlationId = 'abc123correlationid00000010';
        $this->bindStore->put($correlationId, 100, 7);

        $service->handle(
            [
                'tool' => 'patient_context_stub',
                'pid' => 100,
                'user_id' => 7,
            ],
            self::INTERNAL_SECRET,
            $correlationId,
        );

        $service->handle(
            [
                'tool' => 'patient_context_stub',
                'pid' => 999,
                'user_id' => 7,
            ],
            self::INTERNAL_SECRET,
            $correlationId,
        );

        $lines = file($logPath, FILE_IGNORE_NEW_LINES | FILE_SKIP_EMPTY_LINES);
        $this->assertIsArray($lines);
        $this->assertCount(2, $lines);

        $passLine = json_decode((string) $lines[0], true, 512, JSON_THROW_ON_ERROR);
        $failLine = json_decode((string) $lines[1], true, 512, JSON_THROW_ON_ERROR);

        $this->assertSame('tool_proxy', $passLine['event']);
        $this->assertTrue($passLine['pass']);
        $this->assertSame('ok', $passLine['reason']);
        $this->assertSame($correlationId, $passLine['correlation_id']);
        $this->assertSame(100, $passLine['pid']);
        $this->assertSame('patient_context_stub', $passLine['tool']);

        $this->assertSame('tool_proxy', $failLine['event']);
        $this->assertFalse($failLine['pass']);
        $this->assertSame('pid_mismatch', $failLine['reason']);

        array_map('unlink', glob($tempDir . '/*') ?: []);
        rmdir($tempDir);
    }
}
