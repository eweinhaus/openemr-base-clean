<?php

/**
 * Queue schedule-scoped brief prefetch jobs for Ask Co-Pilot top-three patients.
 *
 * @package   OpenEMR
 * @link      https://www.open-emr.org
 * @author    eweinhaus <eweinhaus@users.noreply.github.com>
 * @copyright Copyright (c) 2026 eweinhaus
 * @license   https://github.com/openemr/openemr/blob/master/LICENSE GNU General Public License 3
 */

declare(strict_types=1);

namespace OpenEMR\ClinicalCopilot\Gateway;

use OpenEMR\ClinicalCopilot\Schedule\ProviderDayScheduleService;
use OpenEMR\ClinicalCopilot\Schedule\SchedulePrefetchSelector;
use Throwable;

final class PrefetchBriefService
{
    private const BIND_TTL_SECONDS = 1800;

    private const PREFETCH_LIMIT = 3;

    /**
     * @param (callable(int): string)|null $usernameResolver
     */
    public function __construct(
        private readonly ProviderDayScheduleService $scheduleService,
        private readonly CorrelationBindStoreInterface $bindStore,
        private readonly SidecarClient $sidecarClient,
        private $usernameResolver = null,
    ) {
    }

    /**
     * Mint correlation binds and kick sidecar prefetch for today's top-three schedule pids.
     *
     * @return array{queued: list<int>, skipped?: string|null}
     */
    public function queueTodayTopThree(int $providerUserId, string $username): array
    {
        $username = trim($username);
        if ($username === '' && $this->usernameResolver !== null) {
            $username = trim((string) ($this->usernameResolver)($providerUserId));
        }

        if ($username === '') {
            return [
                'queued' => [],
                'skipped' => 'invalid_user',
            ];
        }

        $schedule = $this->scheduleService->getTodayForProvider($providerUserId);
        if ($schedule->appointments === []) {
            return ['queued' => []];
        }

        $targetPids = SchedulePrefetchSelector::topPids($schedule, self::PREFETCH_LIMIT);
        if ($targetPids === []) {
            return ['queued' => []];
        }

        /** @var list<int> $allSchedulePids */
        $allSchedulePids = [];
        foreach ($schedule->appointments as $appointment) {
            if (!in_array($appointment->pid, $allSchedulePids, true)) {
                $allSchedulePids[] = $appointment->pid;
            }
        }

        /** @var list<int> $queued */
        $queued = [];
        foreach ($targetPids as $pid) {
            if (!in_array($pid, $allSchedulePids, true)) {
                continue;
            }

            $correlationId = bin2hex(random_bytes(16));
            $this->bindStore->put($correlationId, $pid, $providerUserId, self::BIND_TTL_SECONDS);

            try {
                $response = $this->sidecarClient->postPrefetch([
                    'correlation_id' => $correlationId,
                    'user_id' => $providerUserId,
                    'username' => $username,
                    'pid' => $pid,
                    'prefetch' => true,
                ]);
            } catch (Throwable) {
                continue;
            }

            if (($response['ok'] ?? false) === true) {
                $queued[] = $pid;
            }
        }

        return ['queued' => $queued];
    }
}
