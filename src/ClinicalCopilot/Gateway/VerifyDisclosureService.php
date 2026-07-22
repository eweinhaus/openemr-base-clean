<?php

/**
 * Secret-gated verify disclosure writer for the Co-Pilot sidecar callback.
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

final class VerifyDisclosureService
{
    /** Max length for short reason codes (not clinical text). */
    private const MAX_REASON_LENGTH = 64;

    public function __construct(
        private readonly CorrelationBindStoreInterface $bindStore,
        private readonly string $internalSecret,
        private readonly DisclosureLog $disclosureLog,
    ) {
    }

    /**
     * @param array<string, mixed> $body
     *
     * @return array{ok: bool, error?: string}
     */
    public function handle(array $body, string $providedSecret, string $correlationIdFromHeader): array
    {
        if (!hash_equals((string) $this->internalSecret, (string) $providedSecret)) {
            return ['ok' => false, 'error' => 'unauthorized'];
        }

        $event = $body['event'] ?? null;
        if (!is_string($event) || $event !== 'verify') {
            return ['ok' => false, 'error' => 'invalid_request'];
        }

        $pass = $body['pass'] ?? null;
        if (!is_bool($pass)) {
            return ['ok' => false, 'error' => 'invalid_request'];
        }

        $reason = $body['reason'] ?? null;
        if (!is_string($reason)) {
            return ['ok' => false, 'error' => 'invalid_request'];
        }
        $reason = trim($reason);
        if ($reason === '' || strlen($reason) > self::MAX_REASON_LENGTH) {
            return ['ok' => false, 'error' => 'invalid_request'];
        }

        $correlationId = trim($correlationIdFromHeader);
        if ($correlationId === '') {
            $bodyCorrelationId = $body['correlation_id'] ?? null;
            if (!is_string($bodyCorrelationId) || trim($bodyCorrelationId) === '') {
                return ['ok' => false, 'error' => 'invalid_request'];
            }
            $correlationId = trim($bodyCorrelationId);
        }

        $bind = $this->bindStore->get($correlationId);
        if ($bind === null) {
            return ['ok' => false, 'error' => 'bind_missing'];
        }

        $this->disclosureLog->write([
            'event' => 'verify',
            'correlation_id' => $correlationId,
            'pass' => $pass,
            'reason' => $reason,
        ]);

        return ['ok' => true];
    }
}
