<?php

/**
 * Dispatches Ask Co-Pilot chart tool names to ChartFactSet readers.
 *
 * @package   OpenEMR
 * @link      https://www.open-emr.org
 * @author    eweinhaus <eweinhaus@users.noreply.github.com>
 * @copyright Copyright (c) 2026 eweinhaus
 * @license   https://github.com/openemr/openemr/blob/master/LICENSE GNU General Public License 3
 */

declare(strict_types=1);

namespace OpenEMR\ClinicalCopilot\Chart;

interface ChartToolDispatcherInterface
{
    public function dispatch(string $tool, int $pid): ChartFactSet;
}
