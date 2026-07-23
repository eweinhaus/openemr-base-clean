<?php

/**
 * Isolated unit tests for PrefetchBriefService (mocked schedule + sidecar, no DB).
 *
 * @package   OpenEMR
 * @link      https://www.open-emr.org
 * @author    eweinhaus <eweinhaus@users.noreply.github.com>
 * @copyright Copyright (c) 2026 eweinhaus
 * @license   https://github.com/openemr/openemr/blob/master/LICENSE GNU General Public License 3
 */

declare(strict_types=1);

namespace OpenEMR\Tests\Isolated\ClinicalCopilot\Gateway;

use DateTimeImmutable;
use DateTimeZone;
use GuzzleHttp\Client;
use GuzzleHttp\Exception\ConnectException;
use GuzzleHttp\Handler\MockHandler;
use GuzzleHttp\HandlerStack;
use GuzzleHttp\Middleware;
use GuzzleHttp\Psr7\Request;
use GuzzleHttp\Psr7\Response;
use OpenEMR\ClinicalCopilot\Gateway\CorrelationBind;
use OpenEMR\ClinicalCopilot\Gateway\CorrelationBindStoreInterface;
use OpenEMR\ClinicalCopilot\Gateway\PrefetchBriefService;
use OpenEMR\ClinicalCopilot\Gateway\SidecarClient;
use OpenEMR\ClinicalCopilot\Schedule\ProviderDayScheduleService;
use PHPUnit\Framework\Attributes\Small;
use PHPUnit\Framework\TestCase;
use Psr\Clock\ClockInterface;

#[Small]
class PrefetchBriefServiceTest extends TestCase
{
    private const INTERNAL_SECRET = 'test-internal-secret';

    private const PROVIDER_USER_ID = 42;

    private const USERNAME = 'admin';

    public function testEmptyScheduleReturnsEmptyQueuedList(): void
    {
        $bindStore = new RecordingCorrelationBindStore();
        $sidecar = $this->createSidecarClient([]);

        $service = $this->createService(
            $this->createScheduleService(static fn (): array => []),
            $bindStore,
            $sidecar,
        );

        $result = $service->queueTodayTopThree(self::PROVIDER_USER_ID, self::USERNAME);

        $this->assertSame(['queued' => []], $result);
        $this->assertSame([], $bindStore->puts);
    }

    public function testTopThreePidsQueuedInPickerDisplayOrder(): void
    {
        $bindStore = new RecordingCorrelationBindStore();
        $history = [];
        $sidecar = $this->createSidecarClient(
            [
                new Response(200, [], json_encode(['ok' => true], JSON_THROW_ON_ERROR)),
                new Response(200, [], json_encode(['ok' => true], JSON_THROW_ON_ERROR)),
                new Response(200, [], json_encode(['ok' => true], JSON_THROW_ON_ERROR)),
            ],
            $history,
        );

        $service = $this->createService(
            $this->scheduleServiceWithDemoDay(),
            $bindStore,
            $sidecar,
        );

        $result = $service->queueTodayTopThree(self::PROVIDER_USER_ID, self::USERNAME);

        $this->assertSame(['queued' => [8, 6, 2]], $result);
        $this->assertCount(3, $bindStore->puts);
        $this->assertSame([8, 6, 2], array_column($bindStore->puts, 'pid'));
    }

    public function testEachPidGetsBindStorePutWithUniqueCorrelation(): void
    {
        $bindStore = new RecordingCorrelationBindStore();
        $history = [];
        $sidecar = $this->createSidecarClient(
            [
                new Response(200, [], json_encode(['ok' => true], JSON_THROW_ON_ERROR)),
                new Response(200, [], json_encode(['ok' => true], JSON_THROW_ON_ERROR)),
                new Response(200, [], json_encode(['ok' => true], JSON_THROW_ON_ERROR)),
            ],
            $history,
        );

        $service = $this->createService(
            $this->scheduleServiceWithDemoDay(),
            $bindStore,
            $sidecar,
        );

        $before = time();
        $service->queueTodayTopThree(self::PROVIDER_USER_ID, self::USERNAME);
        $after = time();

        $correlationIds = array_column($bindStore->puts, 'correlationId');
        $this->assertCount(3, $correlationIds);
        $this->assertCount(3, array_unique($correlationIds));

        foreach ($bindStore->puts as $put) {
            $this->assertSame(self::PROVIDER_USER_ID, $put['userId']);
            $this->assertSame(1800, $put['ttlSeconds']);

            $bind = $bindStore->get($put['correlationId']);
            $this->assertInstanceOf(CorrelationBind::class, $bind);
            $this->assertSame($put['pid'], $bind->pid);
            $this->assertGreaterThanOrEqual($before + 1800, $bind->expiresAt);
            $this->assertLessThanOrEqual($after + 1800, $bind->expiresAt);
        }

        $this->assertCount(3, $history);
        foreach ($history as $transaction) {
            /** @var Request $request */
            $request = $transaction['request'];
            $this->assertSame('POST', $request->getMethod());
            $this->assertStringEndsWith('/v1/prefetch-brief', $request->getUri()->getPath());
            $this->assertSame(self::INTERNAL_SECRET, $request->getHeaderLine('X-Copilot-Internal-Secret'));
        }
    }

    public function testSidecarFailureOnOnePidStillQueuesOthers(): void
    {
        $bindStore = new RecordingCorrelationBindStore();
        $sidecar = $this->createSidecarClient([
            new Response(200, [], json_encode(['ok' => true], JSON_THROW_ON_ERROR)),
            new Response(500, [], json_encode(['ok' => false, 'error' => 'busy'], JSON_THROW_ON_ERROR)),
            new Response(200, [], json_encode(['ok' => true], JSON_THROW_ON_ERROR)),
        ]);

        $service = $this->createService(
            $this->scheduleServiceWithDemoDay(),
            $bindStore,
            $sidecar,
        );

        $result = $service->queueTodayTopThree(self::PROVIDER_USER_ID, self::USERNAME);

        $this->assertSame(['queued' => [8, 2]], $result);
        $this->assertCount(3, $bindStore->puts);
    }

    public function testSidecarConnectExceptionStillQueuesRemainingPids(): void
    {
        $bindStore = new RecordingCorrelationBindStore();
        $sidecar = $this->createSidecarClient([
            new ConnectException('connection refused', new Request('POST', 'http://sidecar.test/v1/prefetch-brief')),
            new Response(200, [], json_encode(['ok' => true], JSON_THROW_ON_ERROR)),
            new Response(200, [], json_encode(['ok' => true], JSON_THROW_ON_ERROR)),
        ]);

        $service = $this->createService(
            $this->scheduleServiceWithDemoDay(),
            $bindStore,
            $sidecar,
        );

        $result = $service->queueTodayTopThree(self::PROVIDER_USER_ID, self::USERNAME);

        $this->assertSame(['queued' => [6, 2]], $result);
        $this->assertCount(3, $bindStore->puts);
    }

    private function createService(
        ProviderDayScheduleService $scheduleService,
        CorrelationBindStoreInterface $bindStore,
        SidecarClient $sidecarClient,
    ): PrefetchBriefService {
        return new PrefetchBriefService($scheduleService, $bindStore, $sidecarClient);
    }

    private function scheduleServiceWithDemoDay(): ProviderDayScheduleService
    {
        return $this->createScheduleService(static function (): array {
            return [
                [
                    'pid' => 6,
                    'fname' => 'Jane',
                    'lname' => 'Six',
                    'dob' => '1980-01-01',
                    'start_time' => '09:00:00',
                    'category_title' => 'Office Visit',
                    'pc_title' => 'Office Visit',
                    'status_code' => '^',
                    'status_title' => '^ Pending',
                ],
                [
                    'pid' => 8,
                    'fname' => 'Jane',
                    'lname' => 'Eight',
                    'dob' => '1980-01-02',
                    'start_time' => '10:00:00',
                    'category_title' => 'Office Visit',
                    'pc_title' => 'Office Visit',
                    'status_code' => '^',
                    'status_title' => '^ Pending',
                ],
                [
                    'pid' => 2,
                    'fname' => 'Jane',
                    'lname' => 'Two',
                    'dob' => '1980-01-03',
                    'start_time' => '11:00:00',
                    'category_title' => 'Office Visit',
                    'pc_title' => 'Office Visit',
                    'status_code' => '^',
                    'status_title' => '^ Pending',
                ],
            ];
        });
    }

    /**
     * @param callable(int, string): list<array<string, mixed>> $appointmentLoader
     */
    private function createScheduleService(callable $appointmentLoader): ProviderDayScheduleService
    {
        $clock = new class implements ClockInterface {
            public function now(): DateTimeImmutable
            {
                return new DateTimeImmutable('2026-07-21 10:00:00', new DateTimeZone('America/Chicago'));
            }
        };

        return ProviderDayScheduleService::createForTesting(
            $clock,
            'America/Chicago',
            $appointmentLoader,
        );
    }

    /**
     * @param list<Response|ConnectException> $responses
     * @param list<array<string, mixed>>|null $history
     */
    private function createSidecarClient(array $responses, ?array &$history = null): SidecarClient
    {
        $mock = new MockHandler($responses);
        $stack = HandlerStack::create($mock);
        if ($history !== null) {
            $stack->push(Middleware::history($history));
        }

        $client = new Client([
            'handler' => $stack,
            'http_errors' => false,
        ]);

        return new SidecarClient('http://sidecar.test', self::INTERNAL_SECRET, 5.0, $client);
    }
}

/**
 * Records bind store writes for prefetch assertions.
 */
final class RecordingCorrelationBindStore implements CorrelationBindStoreInterface
{
    /** @var list<array{correlationId: string, pid: int, userId: int, ttlSeconds: int}> */
    public array $puts = [];

    private FakeCorrelationBindStore $inner;

    public function __construct()
    {
        $this->inner = new FakeCorrelationBindStore();
    }

    public function put(string $correlationId, int $pid, int $userId, int $ttlSeconds = 600): void
    {
        $this->puts[] = [
            'correlationId' => $correlationId,
            'pid' => $pid,
            'userId' => $userId,
            'ttlSeconds' => $ttlSeconds,
        ];
        $this->inner->put($correlationId, $pid, $userId, $ttlSeconds);
    }

    public function get(string $correlationId): ?CorrelationBind
    {
        return $this->inner->get($correlationId);
    }
}
