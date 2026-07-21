<?php

/**
 * Isolated unit tests for FileCorrelationBindStore correlation bind persistence.
 *
 * @package   OpenEMR
 * @link      https://www.open-emr.org
 * @author    eweinhaus <eweinhaus@users.noreply.github.com>
 * @copyright Copyright (c) 2026 eweinhaus
 * @license   https://github.com/openemr/openemr/blob/master/LICENSE GNU General Public License 3
 */

declare(strict_types=1);

namespace OpenEMR\Tests\Isolated\ClinicalCopilot\Gateway;

use OpenEMR\ClinicalCopilot\Gateway\FileCorrelationBindStore;
use PHPUnit\Framework\Attributes\Small;
use PHPUnit\Framework\TestCase;
use RecursiveDirectoryIterator;
use RecursiveIteratorIterator;
use RuntimeException;
use SplFileInfo;

#[Small]
class FileCorrelationBindStoreTest extends TestCase
{
    private string $tempDir;

    protected function setUp(): void
    {
        $this->tempDir = sys_get_temp_dir() . '/copilot_bind_test_' . uniqid('', true);
        if (!mkdir($this->tempDir, 0700, true) && !is_dir($this->tempDir)) {
            throw new RuntimeException('Failed to create temp directory: ' . $this->tempDir);
        }
    }

    protected function tearDown(): void
    {
        if (!is_dir($this->tempDir)) {
            return;
        }

        $iterator = new RecursiveIteratorIterator(
            new RecursiveDirectoryIterator($this->tempDir, RecursiveDirectoryIterator::SKIP_DOTS),
            RecursiveIteratorIterator::CHILD_FIRST
        );

        /** @var SplFileInfo $entry */
        foreach ($iterator as $entry) {
            if ($entry->isDir()) {
                rmdir($entry->getPathname());
                continue;
            }

            unlink($entry->getPathname());
        }

        rmdir($this->tempDir);
    }

    public function testPutGetRoundtrip(): void
    {
        $store = new FileCorrelationBindStore($this->tempDir);
        $correlationId = 'a1b2c3d4-e5f6-7890-abcd-ef1234567890';

        $store->put($correlationId, 42, 7, 600);

        $bind = $store->get($correlationId);

        $this->assertNotNull($bind);
        $this->assertSame(42, $bind->pid);
        $this->assertSame(7, $bind->userId);
        $this->assertGreaterThan(time(), $bind->expiresAt);
    }

    public function testExpiredEntryReturnsNullAndDeletesFile(): void
    {
        $correlationId = 'deadbeef';
        $safeName = 'deadbeef.json';
        $path = $this->tempDir . DIRECTORY_SEPARATOR . $safeName;

        $written = file_put_contents($path, json_encode([
            'pid' => 10,
            'user_id' => 2,
            'exp' => time() - 60,
        ], JSON_THROW_ON_ERROR));

        if ($written === false) {
            throw new RuntimeException('Failed to seed expired bind file');
        }

        $store = new FileCorrelationBindStore($this->tempDir);

        $this->assertNull($store->get($correlationId));
        $this->assertFileDoesNotExist($path);
    }

    public function testMissingEntryReturnsNull(): void
    {
        $store = new FileCorrelationBindStore($this->tempDir);

        $this->assertNull($store->get('missing-correlation-id'));
    }

    public function testPutThrowsWhenDirectoryNotWritable(): void
    {
        if (PHP_OS_FAMILY === 'Windows') {
            $this->markTestSkipped('Read-only directory semantics differ on Windows');
        }

        if (function_exists('posix_geteuid') && posix_geteuid() === 0) {
            $this->markTestSkipped('Root bypasses directory write permission bits');
        }

        $readOnlyDir = $this->tempDir . DIRECTORY_SEPARATOR . 'readonly';
        if (!mkdir($readOnlyDir, 0500, true) && !is_dir($readOnlyDir)) {
            throw new RuntimeException('Failed to create read-only directory');
        }

        $this->expectException(RuntimeException::class);
        $this->expectExceptionMessage('not writable');

        new FileCorrelationBindStore($readOnlyDir);
    }

    public function testPutThrowsWhenWriteFails(): void
    {
        if (PHP_OS_FAMILY === 'Windows') {
            $this->markTestSkipped('Read-only directory semantics differ on Windows');
        }

        if (function_exists('posix_geteuid') && posix_geteuid() === 0) {
            $this->markTestSkipped('Root bypasses directory write permission bits');
        }

        $store = new FileCorrelationBindStore($this->tempDir);
        chmod($this->tempDir, 0500);

        try {
            $this->expectException(RuntimeException::class);
            $this->expectExceptionMessage('Failed to write correlation bind');

            $store->put('abc123', 1, 1);
        } finally {
            chmod($this->tempDir, 0700);
        }
    }
}
