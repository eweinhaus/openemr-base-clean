<?php

/**
 * Maps gateway/sidecar failures to safe SSE error payloads (no exception dumps / PHI).
 *
 * @package   OpenEMR
 * @link      https://www.open-emr.org
 * @author    eweinhaus <eweinhaus@users.noreply.github.com>
 * @copyright Copyright (c) 2026 eweinhaus
 * @license   https://github.com/openemr/openemr/blob/master/LICENSE GNU General Public License 3
 */

declare(strict_types=1);

namespace OpenEMR\ClinicalCopilot\Gateway;

use Throwable;

final class CopilotStreamError
{
    /**
     * Build a user-facing SSE error payload from a stable code.
     *
     * @return array{message: string, code: string, correlation_id?: string, detail?: string}
     */
    public static function payload(string $code, string $correlationId = '', ?string $detail = null): array
    {
        $payload = [
            'message' => self::messageForCode($code),
            'code' => $code !== '' ? $code : 'unexpected',
        ];
        if ($correlationId !== '') {
            $payload['correlation_id'] = $correlationId;
        }
        if ($detail !== null && $detail !== '') {
            $payload['detail'] = $detail;
        }

        return $payload;
    }

    /**
     * Classify a caught throwable into a stable code (never use getMessage() as the UI text).
     */
    public static function codeFromThrowable(Throwable $e): string
    {
        $raw = $e->getMessage();
        if ($raw === 'sidecar_unreachable') {
            return 'sidecar_unreachable';
        }
        if ($raw === 'sidecar_timeout') {
            return 'sidecar_timeout';
        }
        if ($raw === 'sidecar_request_failed') {
            return 'sidecar_request_failed';
        }
        if (str_starts_with($raw, 'sidecar_http_')) {
            return $raw;
        }

        return 'sidecar_error';
    }

    public static function messageForCode(string $code): string
    {
        return match (true) {
            $code === 'gateway_misconfigured' => 'Co-Pilot gateway is misconfigured (missing secret or sidecar URL).',
            $code === 'gateway_bind_store' => 'Co-Pilot could not create the correlation bind store.',
            $code === 'sidecar_unreachable' => 'Could not reach the Co-Pilot sidecar.',
            $code === 'sidecar_timeout' => 'Co-Pilot sidecar timed out. Try again.',
            $code === 'sidecar_request_failed' => 'Co-Pilot sidecar request failed. Try again.',
            $code === 'sidecar_unready' => 'Co-Pilot is temporarily unavailable. Try again.',
            str_starts_with($code, 'sidecar_http_') => 'Co-Pilot sidecar returned HTTP '
                . substr($code, strlen('sidecar_http_')) . '.',
            $code === 'access_denied' => 'Access denied.',
            $code === 'invalid_request' => 'Unable to process request.',
            $code === 'unbound_patient' => 'Select a patient before chatting.',
            $code === 'patient_changed' => 'Patient changed. Clear the chat and try again.',
            default => 'Something went wrong. Try again.',
        };
    }
}
