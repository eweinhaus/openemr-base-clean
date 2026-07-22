<?php

/**
 * Patient-context chart reader: last visit + active conditions only.
 *
 * Does not extend BaseService: that base class bootstraps DB-backed code_types at
 * include time, which breaks isolated PHPUnit. Follows the Schedule isolatable
 * pattern (injectable loaders + QueryUtils).
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

final class PatientContextService
{
    public const ENCOUNTER_TABLE = 'form_encounter';

    public const LISTS_TABLE = 'lists';

    /**
     * @var (callable(int): (?array<string, mixed>))|null
     */
    private $encounterLoader;

    /**
     * @var (callable(int): list<array<string, mixed>>)|null
     */
    private $problemsLoader;

    public function __construct(
        ?callable $encounterLoader = null,
        ?callable $problemsLoader = null,
    ) {
        $this->encounterLoader = $encounterLoader;
        $this->problemsLoader = $problemsLoader;
    }

    /**
     * @param callable(int): (?array<string, mixed>) $encounterLoader
     * @param callable(int): list<array<string, mixed>> $problemsLoader
     */
    public static function createForTesting(callable $encounterLoader, callable $problemsLoader): self
    {
        return new self($encounterLoader, $problemsLoader);
    }

    public function snapshot(int $pid): ChartFactSet
    {
        if ($pid <= 0) {
            throw new InvalidArgumentException('Patient id must be a positive integer.');
        }

        $facts = [];
        $encounter = $this->loadLastEncounter($pid);
        if ($encounter !== null) {
            $facts[] = $this->mapEncounterFact($encounter);
        }

        foreach ($this->loadActiveProblems($pid) as $row) {
            $facts[] = $this->mapProblemFact($row);
        }

        return new ChartFactSet($facts);
    }

    /**
     * @return array<string, mixed>|null
     */
    private function loadLastEncounter(int $pid): ?array
    {
        if ($this->encounterLoader !== null) {
            $row = ($this->encounterLoader)($pid);

            return is_array($row) ? $row : null;
        }

        $sql = <<<SQL
            SELECT
                id,
                encounter,
                `date`,
                reason
            FROM form_encounter
            WHERE pid = ?
            ORDER BY `date` DESC, encounter DESC, id DESC
            LIMIT 1
            SQL;

        $rows = QueryUtils::fetchRecords($sql, [$pid]);
        $row = $rows[0] ?? null;

        return is_array($row) ? $row : null;
    }

    /**
     * @return list<array<string, mixed>>
     */
    private function loadActiveProblems(int $pid): array
    {
        if ($this->problemsLoader !== null) {
            return array_values(($this->problemsLoader)($pid));
        }

        $sql = <<<SQL
            SELECT
                id,
                title,
                diagnosis,
                begdate,
                enddate,
                activity
            FROM lists
            WHERE pid = ?
              AND type = 'medical_problem'
              AND activity = 1
              AND (
                    enddate IS NULL
                 OR enddate = '0000-00-00'
                 OR enddate = '0000-00-00 00:00:00'
                 OR enddate > NOW()
              )
            ORDER BY begdate DESC, id DESC
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
    private function mapEncounterFact(array $row): ChartFact
    {
        $id = $this->stringifyId($row['id'] ?? $row['encounter'] ?? '');
        $date = $this->formatDate($row['date'] ?? null);
        $reason = trim($this->asString($row['reason'] ?? ''));

        $text = $date !== ''
            ? 'Last visit ' . $date
            : 'Last visit';
        if ($reason !== '') {
            $text .= ' — ' . $reason;
        }

        $excerpt = $reason !== ''
            ? 'Encounter reason on file'
            : 'Most recent encounter';

        return new ChartFact($text, self::ENCOUNTER_TABLE, $id, $excerpt);
    }

    /**
     * @param array<string, mixed> $row
     */
    private function mapProblemFact(array $row): ChartFact
    {
        $id = $this->stringifyId($row['id'] ?? '');
        $title = trim($this->asString($row['title'] ?? ''));
        if ($title === '') {
            $title = 'Unspecified problem';
        }

        $diagnosis = trim($this->asString($row['diagnosis'] ?? ''));
        $text = 'Active problem: ' . $title;
        if ($diagnosis !== '') {
            $text .= ' (' . $diagnosis . ')';
        }

        $begdate = $this->formatDate($row['begdate'] ?? null);
        $excerpt = $begdate !== ''
            ? 'Problem list — onset ' . $begdate . ', active'
            : 'Problem list — active';

        return new ChartFact($text, self::LISTS_TABLE, $id, $excerpt);
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
