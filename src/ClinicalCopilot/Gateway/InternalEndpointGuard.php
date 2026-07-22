<?php

/**
 * Restricts sidecar-facing endpoints to private/loopback callers by default.
 *
 * tool_proxy.php and disclosure.php skip OpenEMR session auth and rely on the
 * shared internal secret. Bound-pid checks remain defense-in-depth, but rejecting
 * public REMOTE_ADDR values stops internet-facing secret-only probing.
 *
 * Escape hatch: COPILOT_INTERNAL_ENDPOINTS_PUBLIC=1 (not for production).
 * Extra allowlist: COPILOT_INTERNAL_ALLOW_CIDRS=comma-separated IPv4 CIDRs/IPs.
 *
 * @package   OpenEMR
 * @link      https://www.open-emr.org
 * @author    eweinhaus <eweinhaus@users.noreply.github.com>
 * @copyright Copyright (c) 2026 eweinhaus
 * @license   https://github.com/openemr/openemr/blob/master/LICENSE GNU General Public License 3
 */

declare(strict_types=1);

namespace OpenEMR\ClinicalCopilot\Gateway;

final class InternalEndpointGuard
{
    /**
     * @return bool True when the caller may hit internal Co-Pilot endpoints.
     */
    public static function isRemoteAddrAllowed(?string $remoteAddr): bool
    {
        $publicOk = getenv('COPILOT_INTERNAL_ENDPOINTS_PUBLIC');
        if (is_string($publicOk) && $publicOk === '1') {
            return true;
        }

        if ($remoteAddr === null) {
            return false;
        }

        $ip = self::normalizeIp($remoteAddr);
        if ($ip === '') {
            return false;
        }

        if (self::isLoopback($ip) || self::isRfc1918OrLocal($ip)) {
            return true;
        }

        foreach (self::extraAllowlist() as $entry) {
            if (self::ipv4Matches($ip, $entry)) {
                return true;
            }
        }

        return false;
    }

    /**
     * @return list<string>
     */
    private static function extraAllowlist(): array
    {
        $raw = getenv('COPILOT_INTERNAL_ALLOW_CIDRS');
        if (!is_string($raw) || trim($raw) === '') {
            return [];
        }

        $parts = preg_split('/\s*,\s*/', trim($raw)) ?: [];
        $out = [];
        foreach ($parts as $part) {
            if ($part !== '') {
                $out[] = $part;
            }
        }

        return $out;
    }

    private static function normalizeIp(string $remoteAddr): string
    {
        $ip = trim($remoteAddr);
        if ($ip === '') {
            return '';
        }

        // IPv6-mapped IPv4 (::ffff:172.18.0.2)
        if (str_starts_with(strtolower($ip), '::ffff:')) {
            $mapped = substr($ip, 7);
            if (filter_var($mapped, FILTER_VALIDATE_IP, FILTER_FLAG_IPV4)) {
                return $mapped;
            }
        }

        if (str_starts_with($ip, '[') && str_ends_with($ip, ']')) {
            $ip = substr($ip, 1, -1);
        }

        // Drop trailing :port on IPv4 (rare in REMOTE_ADDR, cheap to handle).
        if (substr_count($ip, ':') === 1 && str_contains($ip, '.')) {
            $maybe = explode(':', $ip, 2)[0];
            if (filter_var($maybe, FILTER_VALIDATE_IP, FILTER_FLAG_IPV4)) {
                return $maybe;
            }
        }

        if (!filter_var($ip, FILTER_VALIDATE_IP)) {
            return '';
        }

        return $ip;
    }

    private static function isLoopback(string $ip): bool
    {
        if ($ip === '::1') {
            return true;
        }

        return self::ipv4InCidr($ip, '127.0.0.0/8');
    }

    private static function isRfc1918OrLocal(string $ip): bool
    {
        if (self::ipv4InCidr($ip, '10.0.0.0/8')) {
            return true;
        }
        if (self::ipv4InCidr($ip, '172.16.0.0/12')) {
            return true;
        }
        if (self::ipv4InCidr($ip, '192.168.0.0/16')) {
            return true;
        }

        // Unique-local / link-local IPv6 (docker / compose often use these).
        $lower = strtolower($ip);
        if (str_starts_with($lower, 'fc') || str_starts_with($lower, 'fd')) {
            return filter_var($ip, FILTER_VALIDATE_IP, FILTER_FLAG_IPV6) !== false;
        }
        if (str_starts_with($lower, 'fe80:')) {
            return filter_var($ip, FILTER_VALIDATE_IP, FILTER_FLAG_IPV6) !== false;
        }

        return false;
    }

    private static function ipv4Matches(string $ip, string $entry): bool
    {
        if (str_contains($entry, '/')) {
            return self::ipv4InCidr($ip, $entry);
        }

        return $ip === $entry;
    }

    private static function ipv4InCidr(string $ip, string $cidr): bool
    {
        if (!filter_var($ip, FILTER_VALIDATE_IP, FILTER_FLAG_IPV4)) {
            return false;
        }

        $parts = explode('/', $cidr, 2);
        if (count($parts) !== 2) {
            return false;
        }

        [$subnet, $bitsRaw] = $parts;
        if (!filter_var($subnet, FILTER_VALIDATE_IP, FILTER_FLAG_IPV4)) {
            return false;
        }

        if (!ctype_digit($bitsRaw)) {
            return false;
        }
        $bits = (int) $bitsRaw;
        if ($bits < 0 || $bits > 32) {
            return false;
        }

        $ipLong = ip2long($ip);
        $subnetLong = ip2long($subnet);
        if ($ipLong === false || $subnetLong === false) {
            return false;
        }

        if ($bits === 0) {
            return true;
        }

        $mask = -1 << (32 - $bits);

        return ($ipLong & $mask) === ($subnetLong & $mask);
    }
}
