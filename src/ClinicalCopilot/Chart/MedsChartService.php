<?php

/**
 * Active prescriptions + allergies chart reader for Ask Co-Pilot.
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
use OpenEMR\ClinicalCopilot\ClinicalDisplayDate;
use OpenEMR\Common\Database\QueryUtils;

final class MedsChartService
{
    public const PRESCRIPTIONS_TABLE = 'prescriptions';

    public const LISTS_TABLE = 'lists';

    public const DEFAULT_MED_LIMIT = 20;

    private const RXNORM_UNCERTAIN_SUFFIX = ' (RxNorm not on file — drug identity uncertain)';

    /**
     * @var (callable(int, int): list<array<string, mixed>>)|null
     */
    private $prescriptionsLoader;

    /**
     * @var (callable(int): list<array<string, mixed>>)|null
     */
    private $allergiesLoader;

    public function __construct(
        ?callable $prescriptionsLoader = null,
        ?callable $allergiesLoader = null,
    ) {
        $this->prescriptionsLoader = $prescriptionsLoader;
        $this->allergiesLoader = $allergiesLoader;
    }

    /**
     * @param callable(int, int): list<array<string, mixed>> $prescriptionsLoader
     * @param callable(int): list<array<string, mixed>> $allergiesLoader
     */
    public static function createForTesting(callable $prescriptionsLoader, callable $allergiesLoader): self
    {
        return new self($prescriptionsLoader, $allergiesLoader);
    }

    public function activeWithAllergies(int $pid, int $medLimit = self::DEFAULT_MED_LIMIT): ChartFactSet
    {
        if ($pid <= 0) {
            throw new InvalidArgumentException('Patient id must be a positive integer.');
        }

        $medLimit = max(1, $medLimit);
        $activeMeds = [];
        foreach ($this->loadPrescriptions($pid, $medLimit) as $row) {
            if ($this->isActivePrescription($row)) {
                $activeMeds[] = $row;
            }
        }
        if (count($activeMeds) > $medLimit) {
            $activeMeds = array_slice($activeMeds, 0, $medLimit);
        }

        $allergies = $this->loadAllergies($pid);

        $facts = [];
        foreach ($activeMeds as $row) {
            $facts[] = $this->mapPrescriptionFact($row);
        }
        foreach ($allergies as $row) {
            $facts[] = $this->mapAllergyFact($row);
        }

        return new ChartFactSet($facts, [
            'active_med_count' => count($activeMeds),
            'allergy_count' => count($allergies),
        ]);
    }

    /**
     * @return list<array<string, mixed>>
     */
    private function loadPrescriptions(int $pid, int $limit): array
    {
        if ($this->prescriptionsLoader !== null) {
            return array_values(($this->prescriptionsLoader)($pid, $limit));
        }

        $sql = <<<SQL
            SELECT
                id,
                uuid,
                drug,
                dosage,
                size,
                rxnorm_drugcode,
                active,
                end_date,
                start_date,
                date_added,
                drug_dosage_instructions,
                note
            FROM prescriptions
            WHERE patient_id = ?
              AND active = '1'
              AND (end_date IS NULL OR end_date = '0000-00-00')
            ORDER BY COALESCE(start_date, date_added, datetime) DESC, id DESC
            LIMIT {$limit}
            SQL;

        $rows = QueryUtils::fetchRecords($sql, [$pid]);

        return $this->normalizeRows($rows);
    }

    /**
     * @return list<array<string, mixed>>
     */
    private function loadAllergies(int $pid): array
    {
        if ($this->allergiesLoader !== null) {
            return array_values(($this->allergiesLoader)($pid));
        }

        $sql = <<<SQL
            SELECT
                id,
                uuid,
                title,
                reaction,
                comments,
                begdate,
                enddate,
                activity
            FROM lists
            WHERE pid = ?
              AND type = 'allergy'
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

        return $this->normalizeRows($rows);
    }

    /**
     * @param array<string, mixed> $row
     */
    private function isActivePrescription(array $row): bool
    {
        $active = $row['active'] ?? null;
        $isActive = $active === 1 || $active === '1' || $active === true;
        if (!$isActive) {
            return false;
        }

        $endDate = $row['end_date'] ?? null;
        if ($endDate === null) {
            return true;
        }

        $end = trim($this->asString($endDate));
        if ($end === '' || str_starts_with($end, '0000-00-00')) {
            return true;
        }

        return false;
    }

    /**
     * @param array<string, mixed> $row
     */
    private function mapPrescriptionFact(array $row): ChartFact
    {
        $id = $this->stringifyId($row['id'] ?? '');
        $drug = trim($this->asString($row['drug'] ?? ''));
        if ($drug === '') {
            $drug = 'Unspecified medication';
        }

        $dosage = trim($this->asString($row['dosage'] ?? ''));
        $size = trim($this->asString($row['size'] ?? ''));
        $instructions = trim($this->asString($row['drug_dosage_instructions'] ?? ''));

        $text = $drug;
        if ($dosage !== '') {
            $text .= ' ' . $dosage;
        } elseif ($size !== '') {
            $text .= ' ' . $size;
        }
        if ($instructions !== '') {
            $text .= ' — ' . $instructions;
        }

        $rxnorm = trim($this->asString($row['rxnorm_drugcode'] ?? ''));
        if ($rxnorm === '') {
            $text .= self::RXNORM_UNCERTAIN_SUFFIX;
        }

        $start = ClinicalDisplayDate::format($row['start_date'] ?? $row['date_added'] ?? null);
        $excerpt = $start !== ''
            ? 'Active Rx — started ' . $start
            : 'Active Rx';

        return new ChartFact(
            $text,
            self::PRESCRIPTIONS_TABLE,
            $id,
            $excerpt,
            ChartFact::uuidFromRowValue($row['uuid'] ?? null),
        );
    }

    /**
     * @param array<string, mixed> $row
     */
    private function mapAllergyFact(array $row): ChartFact
    {
        $id = $this->stringifyId($row['id'] ?? '');
        $title = trim($this->asString($row['title'] ?? ''));
        if ($title === '') {
            $title = 'Unspecified allergen';
        }

        $reaction = trim($this->asString($row['reaction'] ?? ''));
        $text = 'Allergy: ' . $title;
        if ($reaction !== '') {
            $text .= ' — ' . $reaction;
        }

        $comments = trim($this->asString($row['comments'] ?? ''));
        $excerpt = $comments !== ''
            ? 'Allergy list — ' . $this->truncate($comments, 120)
            : 'Allergy list';

        return new ChartFact(
            $text,
            self::LISTS_TABLE,
            $id,
            $excerpt,
            ChartFact::uuidFromRowValue($row['uuid'] ?? null),
        );
    }

    /**
     * @param list<mixed>|array<int, mixed> $rows
     * @return list<array<string, mixed>>
     */
    private function normalizeRows(array $rows): array
    {
        /** @var list<array<string, mixed>> $normalized */
        $normalized = [];
        foreach ($rows as $row) {
            if (is_array($row)) {
                $normalized[] = $row;
            }
        }

        return $normalized;
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

    private function truncate(string $value, int $max): string
    {
        if (strlen($value) <= $max) {
            return $value;
        }

        return substr($value, 0, $max);
    }
}
