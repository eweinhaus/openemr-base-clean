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
use GuzzleHttp\Exception\GuzzleException;
use RuntimeException;

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
     * @throws RuntimeException When the sidecar returns a non-success status
     */
    public function streamChat(array $payload): void
    {
        $base = rtrim($this->sidecarBaseUrl, '/');
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

        $status = $response->getStatusCode();
        if ($status < 200 || $status >= 300) {
            throw new RuntimeException('Sidecar chat request failed with HTTP ' . $status);
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
}
