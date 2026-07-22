<?php

/**
 * Recent clinical notes chart reader (form_clinical_notes only).
 *
 * Does not extend BaseService (Schedule isolatable pattern).
 *
 * @package   OpenEMR
 * @link      https://www.open-emr.org
 * @author    eweinhaus <eweinhaus@users.noreply.github.com>
 * @copyright Copyright (c) 2026 eweinhaus
 * @license   https://github.com/openemr/openemr/blob/master/LICENSE GNU General Public License 3
 */

declare(strict_types=1);

namespace OpenEMR\ClinicalCopilot\Chart;

use InvalidArgumentException;
use OpenEMR\Common\Database\QueryUtils;

final class NotesChartService
{
    public const TABLE_NAME = 'form_clinical_notes';

    public const DEFAULT_LIMIT = 3;

    public const DEFAULT_EXCERPT_MAX = 500;

    /**
     * @var (callable(int, int): list<array<string, mixed>>)|null
     */
    private $notesLoader;

    public function __construct(?callable $notesLoader = null)
    {
        $this->notesLoader = $notesLoader;
    }

    /**
     * @param callable(int, int): list<array<string, mixed>> $notesLoader
     */
    public static function createForTesting(callable $notesLoader): self
    {
        return new self($notesLoader);
    }

    public function recent(
        int $pid,
        int $limit = self::DEFAULT_LIMIT,
        int $excerptMax = self::DEFAULT_EXCERPT_MAX,
    ): ChartFactSet {
        if ($pid <= 0) {
            throw new InvalidArgumentException('Patient id must be a positive integer.');
        }

        $limit = max(1, $limit);
        $excerptMax = max(1, $excerptMax);
        $rows = $this->loadNotes($pid, $limit);
        if (count($rows) > $limit) {
            $rows = array_slice($rows, 0, $limit);
        }

        $facts = [];
        foreach ($rows as $row) {
            $fact = $this->mapNoteFact($row, $excerptMax);
            if ($fact !== null) {
                $facts[] = $fact;
            }
        }

        return new ChartFactSet($facts);
    }

    /**
     * @return list<array<string, mixed>>
     */
    private function loadNotes(int $pid, int $limit): array
    {
        if ($this->notesLoader !== null) {
            return array_values(($this->notesLoader)($pid, $limit));
        }

        $sql = <<<SQL
            SELECT
                id,
                `date`,
                description,
                codetext,
                clinical_notes_type,
                clinical_notes_category,
                activity
            FROM form_clinical_notes
            WHERE pid = ?
              AND (activity = 1 OR activity IS NULL)
            ORDER BY COALESCE(`date`, last_updated) DESC, id DESC
            LIMIT {$limit}
            SQL;

        $rows = QueryUtils::fetchRecords($sql, [$pid]);

        /** @var list<array<string, mixed>> $normalized */
        $normalized = [];
        foreach ($rows as $row) {
            if (is_array($row)) {
                $normalized[] = $row;
            }
        }

        return $normalized;
    }

    /**
     * @param array<string, mixed> $row
     */
    private function mapNoteFact(array $row, int $excerptMax): ?ChartFact
    {
        $id = $this->stringifyId($row['id'] ?? '');
        $rawBody = $this->asString($row['description'] ?? '');
        if (trim($rawBody) === '') {
            $rawBody = $this->asString($row['codetext'] ?? '');
        }

        $plain = $this->toPlainText($rawBody);
        if ($plain === '') {
            return null;
        }

        $excerpt = $this->truncate($plain, $excerptMax);
        $date = $this->formatDate($row['date'] ?? null);
        $type = trim($this->asString($row['clinical_notes_type'] ?? ''));
        $codetext = trim($this->asString($row['codetext'] ?? ''));

        $label = $codetext !== '' ? $codetext : ($type !== '' ? $type : 'Clinical note');
        $text = $label;
        if ($date !== '') {
            $text .= ' (' . $date . ')';
        }
        $text .= ': ' . $this->truncate($plain, min(160, $excerptMax));

        return new ChartFact($text, self::TABLE_NAME, $id, $excerpt);
    }

    private function toPlainText(string $value): string
    {
        $stripped = strip_tags($value);
        $stripped = html_entity_decode($stripped, ENT_QUOTES | ENT_HTML5, 'UTF-8');
        $stripped = preg_replace('/\s+/u', ' ', $stripped) ?? $stripped;

        return trim($stripped);
    }

    private function truncate(string $value, int $max): string
    {
        if (strlen($value) <= $max) {
            return $value;
        }

        return substr($value, 0, $max);
    }

    private function stringifyId(mixed $id): string
    {
        if (is_int($id) || is_float($id)) {
            return (string) $id;
        }
        if (is_string($id) && $id !== '') {
            return $id;
        }

        return '0';
    }

    private function asString(mixed $value): string
    {
        if (is_string($value)) {
            return $value;
        }
        if (is_int($value) || is_float($value)) {
            return (string) $value;
        }

        return '';
    }

    private function formatDate(mixed $value): string
    {
        $raw = trim($this->asString($value));
        if ($raw === '' || str_starts_with($raw, '0000-00-00')) {
            return '';
        }

        return substr($raw, 0, 10);
    }
}
