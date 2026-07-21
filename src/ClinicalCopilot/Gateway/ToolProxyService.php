<?php

/**
 * Sidecar chart-tool proxy with secret auth and pid fail-closed re-check.
 *
 * @package   OpenEMR
 * @link      https://www.open-emr.org
 * @author    eweinhaus <eweinhaus@users.noreply.github.com>
 * @copyright Copyright (c) 2026 eweinhaus
 * @license   https://github.com/openemr/openemr/blob/master/LICENSE GNU General Public License 3
 */

declare(strict_types=1);

namespace OpenEMR\ClinicalCopilot\Gateway;

use OpenEMR\ClinicalCopilot\Logging\DisclosureLog;

final class ToolProxyService
{
    public function __construct(
        private readonly CorrelationBindStoreInterface $bindStore,
        private readonly string $internalSecret,
        private readonly ?DisclosureLog $disclosureLog = null,
    ) {
    }

    /**
     * @param array<string, mixed> $body
     *
     * @return array{ok: bool, tool?: string, data?: array<string, string>, error?: string}
     */
    public function handle(array $body, string $providedSecret, string $correlationIdFromHeader): array
    {
        if (!hash_equals((string) $this->internalSecret, (string) $providedSecret)) {
            $this->logResult(false, 'unauthorized', null, null, null);

            return ['ok' => false, 'error' => 'unauthorized'];
        }

        $tool = $body['tool'] ?? null;
        if (!is_string($tool) || trim($tool) === '') {
            $this->logResult(false, 'invalid_request', null, null, null);

            return ['ok' => false, 'error' => 'invalid_request'];
        }

        $pid = $body['pid'] ?? null;
        if (!is_int($pid)) {
            $this->logResult(false, 'invalid_request', null, null, $tool);

            return ['ok' => false, 'error' => 'invalid_request'];
        }

        $correlationId = trim($correlationIdFromHeader);
        if ($correlationId === '') {
            $bodyCorrelationId = $body['correlation_id'] ?? null;
            if (!is_string($bodyCorrelationId) || trim($bodyCorrelationId) === '') {
                $this->logResult(false, 'invalid_request', $pid, null, $tool);

                return ['ok' => false, 'error' => 'invalid_request'];
            }

            $correlationId = trim($bodyCorrelationId);
        }

        $bind = $this->bindStore->get($correlationId);
        if ($bind === null) {
            $this->logResult(false, 'bind_missing', $pid, $correlationId, $tool);

            return ['ok' => false, 'error' => 'bind_missing'];
        }

        if ($pid !== $bind->pid) {
            $this->logResult(false, 'pid_mismatch', $pid, $correlationId, $tool);

            return ['ok' => false, 'error' => 'pid_mismatch'];
        }

        if ($tool !== 'patient_context_stub') {
            $this->logResult(false, 'not_implemented', $pid, $correlationId, $tool);

            return ['ok' => false, 'error' => 'not_implemented'];
        }

        $this->logResult(true, 'ok', $pid, $correlationId, $tool);

        return [
            'ok' => true,
            'tool' => 'patient_context_stub',
            'data' => ['status' => 'not_implemented'],
        ];
    }

    private function logResult(
        bool $pass,
        string $reason,
        ?int $pid,
        ?string $correlationId,
        ?string $tool,
    ): void {
        if ($this->disclosureLog === null) {
            return;
        }

        // DisclosureLog requires correlation_id; skip when unavailable (e.g. bad secret).
        if ($correlationId === null || $correlationId === '') {
            return;
        }

        /** @var array<string, bool|int|string> $fields */
        $fields = [
            'event' => 'tool_proxy',
            'pass' => $pass,
            'reason' => $reason,
            'correlation_id' => $correlationId,
        ];

        if ($pid !== null) {
            $fields['pid'] = $pid;
        }

        if ($tool !== null && $tool !== '') {
            $fields['tool'] = $tool;
        }

        $this->disclosureLog->write($fields);
    }
}
