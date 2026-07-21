<?php

/**
 * Isolated unit tests for DisclosureLog JSONL stub writer.
 *
 * @package   OpenEMR
 * @link      https://www.open-emr.org
 * @author    eweinhaus <eweinhaus@users.noreply.github.com>
 * @copyright Copyright (c) 2026 eweinhaus
 * @license   https://github.com/openemr/openemr/blob/master/LICENSE GNU General Public License 3
 */

declare(strict_types=1);

namespace OpenEMR\Tests\Isolated\ClinicalCopilot\Logging;

use OpenEMR\ClinicalCopilot\Logging\DisclosureLog;
use PHPUnit\Framework\Attributes\Small;
use PHPUnit\Framework\TestCase;

#[Small]
class DisclosureLogTest extends TestCase
{
    private string $tempDir = '';

    protected function setUp(): void
    {
        $this->tempDir = sys_get_temp_dir() . '/disclosure-log-test-' . bin2hex(random_bytes(8));
        mkdir($this->tempDir, 0777, true);
    }

    protected function tearDown(): void
    {
        if ($this->tempDir === '' || !is_dir($this->tempDir)) {
            return;
        }

        $this->removeDirectory($this->tempDir);
    }

    private function removeDirectory(string $directory): void
    {
        $entries = scandir($directory);
        if ($entries === false) {
            return;
        }

        foreach ($entries as $entry) {
            if ($entry === '.' || $entry === '..') {
                continue;
            }

            $path = $directory . '/' . $entry;
            if (is_dir($path)) {
                $this->removeDirectory($path);
                continue;
            }

            unlink($path);
        }

        rmdir($directory);
    }

    public function testWriteAppendsOneValidJsonLineWithRequiredFields(): void
    {
        $logPath = $this->tempDir . '/nested/disclosure.jsonl';
        $log = new DisclosureLog($logPath);

        $log->write([
            'correlation_id' => 'abc123',
            'event' => 'tool_call',
            'user_id' => 7,
            'pid' => 100,
        ]);

        $this->assertFileExists($logPath);
        $lines = file($logPath, FILE_IGNORE_NEW_LINES | FILE_SKIP_EMPTY_LINES);
        $this->assertIsArray($lines);
        $this->assertCount(1, $lines);

        $decoded = json_decode((string) $lines[0], true, 512, JSON_THROW_ON_ERROR);
        $this->assertSame('abc123', $decoded['correlation_id']);
        $this->assertSame('tool_call', $decoded['event']);
        $this->assertSame(7, $decoded['user_id']);
        $this->assertSame(100, $decoded['pid']);
        $this->assertArrayHasKey('ts', $decoded);
        $this->assertMatchesRegularExpression(
            '/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$/',
            (string) $decoded['ts']
        );
    }

    public function testWritePreservesProvidedTimestamp(): void
    {
        $logPath = $this->tempDir . '/disclosure.jsonl';
        $log = new DisclosureLog($logPath);

        $log->write([
            'correlation_id' => 'cid-1',
            'event' => 'verify',
            'ts' => '2026-07-21T18:00:00Z',
        ]);

        $decoded = json_decode((string) file_get_contents($logPath), true, 512, JSON_THROW_ON_ERROR);
        $this->assertSame('2026-07-21T18:00:00Z', $decoded['ts']);
    }

    public function testWriteStripsForbiddenMessageAndNoteBodyKeys(): void
    {
        $logPath = $this->tempDir . '/disclosure.jsonl';
        $log = new DisclosureLog($logPath);

        $log->write([
            'correlation_id' => 'cid-2',
            'event' => 'disclosure',
            'message' => 'must not persist',
            'note' => 'secret note body',
            'body' => 'raw body',
            'text' => 'free text',
            'chart' => ['vitals' => 1],
            'payload' => ['nested' => 'data'],
            'tool' => 'patient_context_stub',
            'pass' => true,
            'reason' => 'ok',
        ]);

        $decoded = json_decode((string) file_get_contents($logPath), true, 512, JSON_THROW_ON_ERROR);

        $this->assertArrayNotHasKey('message', $decoded);
        $this->assertArrayNotHasKey('note', $decoded);
        $this->assertArrayNotHasKey('body', $decoded);
        $this->assertArrayNotHasKey('text', $decoded);
        $this->assertArrayNotHasKey('chart', $decoded);
        $this->assertArrayNotHasKey('payload', $decoded);
        $this->assertSame('patient_context_stub', $decoded['tool']);
        $this->assertTrue($decoded['pass']);
        $this->assertSame('ok', $decoded['reason']);
    }
}
