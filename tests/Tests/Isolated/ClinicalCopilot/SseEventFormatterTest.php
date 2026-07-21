<?php

/**
 * Isolated unit tests for SSE event frame formatting.
 *
 * @package   OpenEMR
 * @link      https://www.open-emr.org
 * @author    eweinhaus <eweinhaus@users.noreply.github.com>
 * @copyright Copyright (c) 2026 eweinhaus
 * @license   https://github.com/openemr/openemr/blob/master/LICENSE GNU General Public License 3
 */

declare(strict_types=1);

namespace OpenEMR\Tests\Isolated\ClinicalCopilot;

use JsonException;
use OpenEMR\ClinicalCopilot\Sse\SseEvent;
use PHPUnit\Framework\Attributes\DataProvider;
use PHPUnit\Framework\Attributes\Small;
use PHPUnit\Framework\TestCase;

#[Small]
class SseEventFormatterTest extends TestCase
{
    public function testFormatProgressEvent(): void
    {
        $frame = SseEvent::format('progress', ['message' => 'Working…']);

        self::assertSame(
            "event: progress\ndata: {\"message\":\"Working…\"}\n\n",
            $frame
        );
    }

    public function testFormatClinicalEvent(): void
    {
        $frame = SseEvent::format('clinical', ['text' => 'Stub: I received: hello']);

        self::assertSame(
            "event: clinical\ndata: {\"text\":\"Stub: I received: hello\"}\n\n",
            $frame
        );
    }

    public function testFormatDoneEvent(): void
    {
        $frame = SseEvent::format('done', ['correlation_id' => 'a1b2c3d4e5f60718']);

        self::assertSame(
            "event: done\ndata: {\"correlation_id\":\"a1b2c3d4e5f60718\"}\n\n",
            $frame
        );
    }

    public function testFormatErrorEvent(): void
    {
        $frame = SseEvent::format('error', ['message' => 'Unable to process request.']);

        self::assertSame(
            "event: error\ndata: {\"message\":\"Unable to process request.\"}\n\n",
            $frame
        );
    }

    public function testFormatEscapesSpecialCharactersInJson(): void
    {
        $frame = SseEvent::format('clinical', ['text' => "line1\n\"quoted\""]);

        self::assertSame(
            "event: clinical\ndata: {\"text\":\"line1\\n\\\"quoted\\\"\"}\n\n",
            $frame
        );
    }

    public function testFormatEndsWithBlankLine(): void
    {
        $frame = SseEvent::format('progress', ['message' => 'ok']);

        self::assertStringEndsWith("\n\n", $frame);
        self::assertSame(1, substr_count($frame, "\n\n"));
    }

    /**
     * @return array<string, array{string, array<string, mixed>}>
     *
     * @codeCoverageIgnore Data providers run before coverage instrumentation starts.
     */
    public static function lockedEventProvider(): array
    {
        return [
            'progress' => ['progress', ['message' => 'Looking up chart…']],
            'clinical' => ['clinical', ['text' => 'Stub: I received: labs']],
            'done' => ['done', ['correlation_id' => 'deadbeefcafebabe']],
            'error' => ['error', ['message' => 'Request failed.']],
        ];
    }

    /**
     * @param array<string, mixed> $data
     */
    #[DataProvider('lockedEventProvider')]
    public function testFormatProducesEventAndDataLines(string $event, array $data): void
    {
        $frame = SseEvent::format($event, $data);

        self::assertStringStartsWith("event: {$event}\n", $frame);
        self::assertStringContainsString("\ndata: ", $frame);
        self::assertMatchesRegularExpression('/^event: .+\ndata: \{.+\}\n\n$/s', $frame);

        $dataLine = explode("\n", $frame)[1];
        self::assertStringStartsWith('data: ', $dataLine);
        $decoded = json_decode(substr($dataLine, 6), true, 512, JSON_THROW_ON_ERROR);
        self::assertSame($data, $decoded);
    }

    public function testFormatThrowsOnInvalidUtf8(): void
    {
        $this->expectException(JsonException::class);

        SseEvent::format('error', ['message' => "\xB1\x31"]);
    }
}
