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
    private const STUB_TOOLS = [
        'patient_context_stub',
        'labs_stub',
        'meds_stub',
    ];

    public function __construct(
        private readonly CorrelationBindStoreInterface $bindStore,
        private readonly string $internalSecret,
        private readonly ?DisclosureLog $disclosureLog = null,
    ) {
    }

    /**
     * @param array<string, mixed> $body
     *
     * @return array{
     *     ok: bool,
     *     tool?: string,
     *     data?: array{facts: list<array{text: string, table: string, id: string|int, excerpt: string}>},
     *     error?: string
     * }
     */
    public function handle(array $body, string $providedSecret, string $correlationIdFromHeader): array
    {
        if (!hash_equals((string) $this->internalSecret, (string) $providedSecret)) {
            $this->logResult(false, 'unauthorized', null, null, null, null);

            return ['ok' => false, 'error' => 'unauthorized'];
        }

        $tool = $body['tool'] ?? null;
        if (!is_string($tool) || trim($tool) === '') {
            $this->logResult(false, 'invalid_request', null, null, null, null);

            return ['ok' => false, 'error' => 'invalid_request'];
        }

        $pid = $body['pid'] ?? null;
        if (!is_int($pid)) {
            $this->logResult(false, 'invalid_request', null, null, null, $tool);

            return ['ok' => false, 'error' => 'invalid_request'];
        }

        $userId = $body['user_id'] ?? null;
        if (!is_int($userId) || $userId <= 0) {
            $this->logResult(false, 'invalid_request', $pid, null, null, $tool);

            return ['ok' => false, 'error' => 'invalid_request'];
        }

        $correlationId = trim($correlationIdFromHeader);
        if ($correlationId === '') {
            $bodyCorrelationId = $body['correlation_id'] ?? null;
            if (!is_string($bodyCorrelationId) || trim($bodyCorrelationId) === '') {
                $this->logResult(false, 'invalid_request', $pid, $userId, null, $tool);

                return ['ok' => false, 'error' => 'invalid_request'];
            }

            $correlationId = trim($bodyCorrelationId);
        }

        $bind = $this->bindStore->get($correlationId);
        if ($bind === null) {
            $this->logResult(false, 'bind_missing', $pid, $userId, $correlationId, $tool);

            return ['ok' => false, 'error' => 'bind_missing'];
        }

        if ($pid !== $bind->pid) {
            $this->logResult(false, 'pid_mismatch', $pid, $userId, $correlationId, $tool);

            return ['ok' => false, 'error' => 'pid_mismatch'];
        }

        if ($userId !== $bind->userId) {
            $this->logResult(false, 'user_mismatch', $pid, $userId, $correlationId, $tool);

            return ['ok' => false, 'error' => 'user_mismatch'];
        }

        if (!in_array($tool, self::STUB_TOOLS, true)) {
            $this->logResult(false, 'not_implemented', $pid, $userId, $correlationId, $tool);

            return ['ok' => false, 'error' => 'not_implemented'];
        }

        $this->logResult(true, 'ok', $pid, $userId, $correlationId, $tool);

        return [
            'ok' => true,
            'tool' => $tool,
            'data' => $this->stubToolData($tool),
        ];
    }

    /**
     * @return array{facts: list<array{text: string, table: string, id: string|int, excerpt: string}>}
     */
    private function stubToolData(string $tool): array
    {
        return match ($tool) {
            'patient_context_stub' => [
                'facts' => [
                    [
                        'text' => 'Active problem: Type 2 diabetes mellitus (E11.9)',
                        'table' => 'lists',
                        'id' => '101',
                        'excerpt' => 'Problem list — onset 2019-03-14, active',
                    ],
                    [
                        'text' => 'Allergy: Penicillin — rash',
                        'table' => 'lists',
                        'id' => '102',
                        'excerpt' => 'Allergy list — severity moderate',
                    ],
                    [
                        'text' => 'Active problem: Essential hypertension (I10)',
                        'table' => 'lists',
                        'id' => '103',
                        'excerpt' => 'Problem list — onset 2017-08-02, active',
                    ],
                ],
            ],
            'labs_stub' => [
                'facts' => [
                    [
                        'text' => 'Serum creatinine 1.1 mg/dL (2026-06-01)',
                        'table' => 'procedure_result',
                        'id' => '501',
                        'excerpt' => 'CMP — within reference range',
                    ],
                    [
                        'text' => 'HbA1c 7.2% (2026-05-15)',
                        'table' => 'procedure_result',
                        'id' => '502',
                        'excerpt' => 'Glycemic control — above goal',
                    ],
                    [
                        'text' => 'LDL cholesterol 118 mg/dL (2026-05-15)',
                        'table' => 'procedure_result',
                        'id' => '503',
                        'excerpt' => 'Lipid panel — borderline high',
                    ],
                ],
            ],
            'meds_stub' => [
                'facts' => [
                    [
                        'text' => 'Metformin 500 mg tablet — take one twice daily with meals',
                        'table' => 'prescriptions',
                        'id' => '201',
                        'excerpt' => 'Active Rx — started 2020-01-10',
                    ],
                    [
                        'text' => 'Lisinopril 10 mg tablet — take one daily',
                        'table' => 'prescriptions',
                        'id' => '202',
                        'excerpt' => 'Active Rx — started 2018-11-03',
                    ],
                ],
            ],
            default => throw new \InvalidArgumentException('Unsupported stub tool: ' . $tool),
        };
    }

    private function logResult(
        bool $pass,
        string $reason,
        ?int $pid,
        ?int $userId,
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

        if ($userId !== null) {
            $fields['user_id'] = $userId;
        }

        if ($tool !== null && $tool !== '') {
            $fields['tool'] = $tool;
        }

        $this->disclosureLog->write($fields);
    }
}
