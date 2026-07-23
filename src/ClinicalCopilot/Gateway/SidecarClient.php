<?php

/**
 * Guzzle client that proxies hybrid SSE from the Co-Pilot sidecar.
 *
 * @package   OpenEMR
 * @link      https://www.open-emr.org
 * @author    eweinhaus <eweinhaus@users.noreply.github.com>
 * @copyright Copyright (c) 2026 eweinhaus
 * @license   https://github.com/openemr/openemr/blob/master/LICENSE GNU General Public License 3
 */

declare(strict_types=1);

namespace OpenEMR\ClinicalCopilot\Gateway;

use GuzzleHttp\Client;
use GuzzleHttp\Exception\ConnectException;
use GuzzleHttp\Exception\GuzzleException;
use GuzzleHttp\Exception\RequestException;
use JsonException;
use RuntimeException;
use Throwable;

final class SidecarClient
{
    private readonly Client $client;

    public function __construct(
        private readonly string $sidecarBaseUrl,
        private readonly string $internalSecret,
        private readonly float $timeoutSeconds = 45.0,
        ?Client $client = null,
    ) {
        $this->client = $client ?? new Client([
            'http_errors' => false,
            'timeout' => $this->timeoutSeconds,
            'connect_timeout' => min(10.0, $this->timeoutSeconds),
        ]);
    }

    /**
     * POST /v1/chat and write the sidecar SSE body to the current output buffer.
     *
     * @param array{
     *     correlation_id: string,
     *     user_id: int,
     *     username: string,
     *     pid: int,
     *     message: string,
     *     transcript: list<mixed>
     * } $payload
     *
     * @throws GuzzleException
     * @throws RuntimeException When the sidecar is unreachable, times out, or returns non-success
     */
    public function streamChat(array $payload): void
    {
        $base = rtrim($this->sidecarBaseUrl, '/');
        try {
            $response = $this->client->request('POST', $base . '/v1/chat', [
                'headers' => [
                    'Accept' => 'text/event-stream',
                    'Content-Type' => 'application/json',
                    'X-Copilot-Internal-Secret' => $this->internalSecret,
                    'X-Correlation-Id' => $payload['correlation_id'],
                ],
                'json' => $payload,
                'stream' => true,
            ]);
        } catch (ConnectException $e) {
            throw new RuntimeException('sidecar_unreachable', 0, $e);
        } catch (RequestException $e) {
            $msg = strtolower($e->getMessage());
            if (str_contains($msg, 'timed out') || str_contains($msg, 'timeout')) {
                throw new RuntimeException('sidecar_timeout', 0, $e);
            }
            throw new RuntimeException('sidecar_request_failed', 0, $e);
        } catch (GuzzleException $e) {
            throw new RuntimeException('sidecar_request_failed', 0, $e);
        }

        $status = $response->getStatusCode();
        if ($status < 200 || $status >= 300) {
            throw new RuntimeException('sidecar_http_' . $status);
        }

        $body = $response->getBody();
        while (!$body->eof()) {
            $chunk = $body->read(8192);
            if ($chunk === '') {
                continue;
            }
            echo $chunk;
            if (function_exists('ob_flush')) {
                @ob_flush();
            }
            flush();
        }
    }

    /**
     * POST /v1/prefetch-brief (non-SSE JSON kick for background brief cache warm).
     *
     * @param array{
     *     correlation_id: string,
     *     user_id: int,
     *     username: string,
     *     pid: int,
     *     prefetch: bool
     * } $payload
     *
     * @return array<string, mixed>
     */
    public function postPrefetch(array $payload): array
    {
        $base = rtrim($this->sidecarBaseUrl, '/');

        try {
            $response = $this->client->request('POST', $base . '/v1/prefetch-brief', [
                'headers' => [
                    'Content-Type' => 'application/json',
                    'X-Copilot-Internal-Secret' => $this->internalSecret,
                    'X-Correlation-Id' => $payload['correlation_id'],
                ],
                'json' => $payload,
                'timeout' => 5.0,
                'connect_timeout' => 5.0,
                'http_errors' => false,
            ]);
        } catch (Throwable) {
            return ['ok' => false];
        }

        $status = $response->getStatusCode();
        if ($status < 200 || $status >= 300) {
            return ['ok' => false];
        }

        $body = (string) $response->getBody();
        if ($body === '') {
            return ['ok' => false];
        }

        try {
            $decoded = json_decode($body, true, 512, JSON_THROW_ON_ERROR);
        } catch (JsonException) {
            return ['ok' => false];
        }

        if (!is_array($decoded)) {
            return ['ok' => false];
        }

        return $decoded;
    }
}
