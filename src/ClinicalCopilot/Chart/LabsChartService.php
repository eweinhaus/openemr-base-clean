<?php

/**
 * Recent lab result chart reader (procedure_order → report → result).
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

final class LabsChartService
{
    public const TABLE_NAME = 'procedure_result';

    public const DEFAULT_LIMIT = 15;

    /**
     * @var (callable(int, int): list<array<string, mixed>>)|null
     */
    private $resultsLoader;

    public function __construct(?callable $resultsLoader = null)
    {
        $this->resultsLoader = $resultsLoader;
    }

    /**
     * @param callable(int, int): list<array<string, mixed>> $resultsLoader
     */
    public static function createForTesting(callable $resultsLoader): self
    {
        return new self($resultsLoader);
    }

    public function recent(int $pid, int $limit = self::DEFAULT_LIMIT): ChartFactSet
    {
        if ($pid <= 0) {
            throw new InvalidArgumentException('Patient id must be a positive integer.');
        }

        $limit = max(1, $limit);
        $rows = $this->loadResults($pid, $limit);
        if (count($rows) > $limit) {
            $rows = array_slice($rows, 0, $limit);
        }

        $facts = [];
        foreach ($rows as $row) {
            $facts[] = $this->mapResultFact($row);
        }

        return new ChartFactSet($facts);
    }

    /**
     * @return list<array<string, mixed>>
     */
    private function loadResults(int $pid, int $limit): array
    {
        if ($this->resultsLoader !== null) {
            return array_values(($this->resultsLoader)($pid, $limit));
        }

        $sql = <<<SQL
            SELECT
                pr.procedure_result_id,
                pr.result_text,
                pr.result,
                pr.units,
                COALESCE(pr.`date`, prep.date_report, po.date_ordered) AS `date`,
                pr.`range`,
                pr.abnormal,
                poc.procedure_name
            FROM procedure_order AS po
            INNER JOIN procedure_report AS prep
                ON prep.procedure_order_id = po.procedure_order_id
            INNER JOIN procedure_result AS pr
                ON pr.procedure_report_id = prep.procedure_report_id
            LEFT JOIN procedure_order_code AS poc
                ON poc.procedure_order_id = po.procedure_order_id
               AND poc.procedure_order_seq = prep.procedure_order_seq
            WHERE po.patient_id = ?
              AND po.activity = 1
            ORDER BY COALESCE(pr.`date`, prep.date_report, po.date_ordered) DESC,
                     pr.procedure_result_id DESC
            LIMIT {$limit}
            SQL;

        // LIMIT is an int we validated above — not user input.
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
    private function mapResultFact(array $row): ChartFact
    {
        $id = $this->stringifyId($row['procedure_result_id'] ?? '');
        $label = trim($this->asString($row['result_text'] ?? ''));
        if ($label === '') {
            $label = trim($this->asString($row['procedure_name'] ?? ''));
        }
        if ($label === '') {
            $label = 'Lab result';
        }

        $result = $this->asString($row['result'] ?? '');
        $units = trim($this->asString($row['units'] ?? ''));
        $date = $this->formatDate($row['date'] ?? null);
        $range = trim($this->asString($row['range'] ?? ''));
        $abnormal = trim($this->asString($row['abnormal'] ?? ''));

        $text = $label;
        if ($result !== '') {
            $text .= ' ' . $result;
            if ($units !== '') {
                $text .= ' ' . $units;
            }
        }
        if ($date !== '') {
            $text .= ' (' . $date . ')';
        }

        if ($abnormal !== '' && !in_array(strtolower($abnormal), ['no', 'n', '0'], true)) {
            $text .= ' [abnormal: ' . $abnormal . ']';
        }
        if ($range !== '') {
            $text .= ' (ref ' . $range . ')';
        }

        $procedureName = trim($this->asString($row['procedure_name'] ?? ''));
        $excerptParts = [];
        if ($procedureName !== '') {
            $excerptParts[] = $procedureName;
        }
        if ($range !== '') {
            $excerptParts[] = 'reference range on file';
        } elseif ($abnormal !== '') {
            $excerptParts[] = 'abnormal flag on file';
        } else {
            $excerptParts[] = 'Lab result';
        }

        return new ChartFact($text, self::TABLE_NAME, $id, implode(' — ', $excerptParts));
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
