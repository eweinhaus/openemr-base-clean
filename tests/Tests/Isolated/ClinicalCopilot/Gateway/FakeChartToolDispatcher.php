<?php

/**
 * Fake chart dispatcher for ToolProxyService isolated tests.
 *
 * @package   OpenEMR
 * @link      https://www.open-emr.org
 * @author    eweinhaus <eweinhaus@users.noreply.github.com>
 * @copyright Copyright (c) 2026 eweinhaus
 * @license   https://github.com/openemr/openemr/blob/master/LICENSE GNU General Public License 3
 */

declare(strict_types=1);

namespace OpenEMR\Tests\Isolated\ClinicalCopilot\Gateway;

use InvalidArgumentException;
use OpenEMR\ClinicalCopilot\Chart\ChartFact;
use OpenEMR\ClinicalCopilot\Chart\ChartFactSet;
use OpenEMR\ClinicalCopilot\Chart\ChartToolDispatcherInterface;
use RuntimeException;
use Throwable;

final class FakeChartToolDispatcher implements ChartToolDispatcherInterface
{
    /** @var array<string, ChartFactSet|Throwable> */
    private array $responsesByTool = [];

    private ?int $lastPid = null;

    private ?string $lastTool = null;

    public function setResponse(string $tool, ChartFactSet $factSet): void
    {
        $this->responsesByTool[$tool] = $factSet;
    }

    public function setThrow(string $tool, Throwable $throwable): void
    {
        $this->responsesByTool[$tool] = $throwable;
    }

    public function dispatch(string $tool, int $pid): ChartFactSet
    {
        $this->lastTool = $tool;
        $this->lastPid = $pid;

        if (!array_key_exists($tool, $this->responsesByTool)) {
            throw new InvalidArgumentException('Unknown chart tool');
        }

        $response = $this->responsesByTool[$tool];
        if ($response instanceof Throwable) {
            throw $response;
        }

        return $response;
    }

    public function getLastPid(): ?int
    {
        return $this->lastPid;
    }

    public function getLastTool(): ?string
    {
        return $this->lastTool;
    }

    public static function withSampleContextFacts(): self
    {
        $fake = new self();
        $fake->setResponse(
            'patient_context',
            new ChartFactSet([
                new ChartFact(
                    'Last visit 2026-01-18 — Encounter for check up',
                    'form_encounter',
                    '77',
                    'Most recent encounter',
                ),
                new ChartFact(
                    'Active problem: Type 2 diabetes mellitus (E11.9)',
                    'lists',
                    '101',
                    'Problem list — active',
                ),
            ]),
        );
        $fake->setResponse(
            'labs',
            new ChartFactSet([
                new ChartFact(
                    'Serum creatinine 1.1 mg/dL (2026-06-01)',
                    'procedure_result',
                    '501',
                    'CMP',
                ),
            ]),
        );
        $fake->setResponse(
            'meds',
            new ChartFactSet(
                [
                    new ChartFact(
                        'Metformin 500 mg tablet — take one twice daily',
                        'prescriptions',
                        '201',
                        'Active Rx',
                    ),
                ],
                ['active_med_count' => 1, 'allergy_count' => 0],
            ),
        );
        $fake->setResponse('notes', new ChartFactSet([]));

        return $fake;
    }

    public function assertDispatched(string $tool, int $pid): void
    {
        if ($this->lastTool !== $tool || $this->lastPid !== $pid) {
            throw new RuntimeException(sprintf(
                'Expected dispatch(%s, %d); got (%s, %s)',
                $tool,
                $pid,
                (string) $this->lastTool,
                $this->lastPid === null ? 'null' : (string) $this->lastPid,
            ));
        }
    }
}
