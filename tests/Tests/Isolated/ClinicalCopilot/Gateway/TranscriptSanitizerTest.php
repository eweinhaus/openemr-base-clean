<?php

/**
 * Isolated unit tests for TranscriptSanitizer.
 *
 * @package   OpenEMR
 * @link      https://www.open-emr.org
 * @author    eweinhaus <eweinhaus@users.noreply.github.com>
 * @copyright Copyright (c) 2026 eweinhaus
 * @license   https://github.com/openemr/openemr/blob/master/LICENSE GNU General Public License 3
 */

declare(strict_types=1);

namespace OpenEMR\Tests\Isolated\ClinicalCopilot\Gateway;

use OpenEMR\ClinicalCopilot\Gateway\TranscriptSanitizer;
use PHPUnit\Framework\Attributes\Small;
use PHPUnit\Framework\TestCase;

#[Small]
class TranscriptSanitizerTest extends TestCase
{
    public function testSanitizeKeepsUserAndAssistantTurns(): void
    {
        $result = TranscriptSanitizer::sanitize([
            ['role' => 'user', 'text' => 'Hello'],
            ['role' => 'assistant', 'text' => 'Hi'],
            ['role' => 'system', 'text' => 'ignore'],
            ['role' => 'user', 'text' => ''],
            'not-an-array',
            ['role' => 'user', 'text' => 123],
        ]);

        $this->assertSame(
            [
                ['role' => 'user', 'text' => 'Hello'],
                ['role' => 'assistant', 'text' => 'Hi'],
            ],
            $result,
        );
    }

    public function testSanitizeTruncatesLengthAndEntryCount(): void
    {
        $long = str_repeat('a', TranscriptSanitizer::MAX_TEXT_LENGTH + 50);
        $entries = [];
        for ($i = 0; $i < TranscriptSanitizer::MAX_ENTRIES + 5; $i++) {
            $entries[] = ['role' => 'user', 'text' => 'msg-' . $i];
        }
        $entries[] = ['role' => 'user', 'text' => $long];

        $result = TranscriptSanitizer::sanitize($entries);

        $this->assertCount(TranscriptSanitizer::MAX_ENTRIES, $result);
        $this->assertSame('msg-6', $result[0]['text']);
        $last = $result[array_key_last($result)];
        $this->assertSame(TranscriptSanitizer::MAX_TEXT_LENGTH, mb_strlen($last['text'], 'UTF-8'));
    }

    public function testSanitizeTruncatesMultibyteWithoutBreakingUtf8(): void
    {
        // Each emoji is 4 bytes / 1 code point — byte-wise substr would corrupt UTF-8.
        $long = str_repeat('😀', TranscriptSanitizer::MAX_TEXT_LENGTH + 10);
        $result = TranscriptSanitizer::sanitize([
            ['role' => 'user', 'text' => $long],
        ]);

        $this->assertCount(1, $result);
        $this->assertSame(TranscriptSanitizer::MAX_TEXT_LENGTH, mb_strlen($result[0]['text'], 'UTF-8'));
        $this->assertTrue(mb_check_encoding($result[0]['text'], 'UTF-8'));
        json_encode($result, JSON_THROW_ON_ERROR);
    }
}
