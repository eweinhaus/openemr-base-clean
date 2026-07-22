<?php

/**
 * Maps Ask Co-Pilot chart tool names to Chart*Service readers.
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

final class ChartToolDispatcher implements ChartToolDispatcherInterface
{
    public function __construct(
        private readonly PatientContextService $context,
        private readonly LabsChartService $labs,
        private readonly MedsChartService $meds,
        private readonly NotesChartService $notes,
    ) {
    }

    public function dispatch(string $tool, int $pid): ChartFactSet
    {
        if ($pid <= 0) {
            throw new InvalidArgumentException('Patient id must be a positive integer.');
        }

        return match ($tool) {
            'patient_context' => $this->context->snapshot($pid),
            'labs' => $this->labs->recent($pid),
            'meds' => $this->meds->activeWithAllergies($pid),
            'notes' => $this->notes->recent($pid),
            default => throw new InvalidArgumentException('Unknown chart tool'),
        };
    }
}
