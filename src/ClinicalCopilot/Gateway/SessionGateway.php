<?php

/**
 * Builds gateway session context from OpenEMR session values.
 *
 * @package   OpenEMR
 * @link      https://www.open-emr.org
 * @author    eweinhaus <eweinhaus@users.noreply.github.com>
 * @copyright Copyright (c) 2026 eweinhaus
 * @license   https://github.com/openemr/openemr/blob/master/LICENSE GNU General Public License 3
 */

declare(strict_types=1);

namespace OpenEMR\ClinicalCopilot\Gateway;

use DomainException;

final class SessionGateway
{
    public static function fromSessionValues(
        mixed $authUserId,
        mixed $authUser,
        mixed $pid,
        ?string $requestPidIgnored = null,
    ): SessionContext {
        // Explicitly discard any client-supplied pid — bind from session only.
        unset($requestPidIgnored);

        $username = self::normalizeUsername($authUser);
        if ($username === '') {
            throw new DomainException('Authenticated session required');
        }

        $userId = self::normalizeUserId($authUserId);
        $boundPid = self::normalizePid($pid);

        return new SessionContext(
            $userId,
            $username,
            $boundPid,
            bin2hex(random_bytes(16)),
        );
    }

    private static function normalizeUsername(mixed $authUser): string
    {
        if (!is_string($authUser)) {
            return '';
        }

        return trim($authUser);
    }

    private static function normalizeUserId(mixed $authUserId): int
    {
        if (is_int($authUserId)) {
            return max(0, $authUserId);
        }

        if (is_string($authUserId) && ctype_digit($authUserId)) {
            return (int) $authUserId;
        }

        if (is_numeric($authUserId)) {
            return max(0, (int) $authUserId);
        }

        return 0;
    }

    private static function normalizePid(mixed $pid): ?int
    {
        if ($pid === null || $pid === '') {
            return null;
        }

        if (is_int($pid)) {
            return $pid > 0 ? $pid : null;
        }

        if (is_string($pid) && ctype_digit($pid)) {
            $normalized = (int) $pid;

            return $normalized > 0 ? $normalized : null;
        }

        if (is_numeric($pid)) {
            $normalized = (int) $pid;

            return $normalized > 0 ? $normalized : null;
        }

        return null;
    }
}
