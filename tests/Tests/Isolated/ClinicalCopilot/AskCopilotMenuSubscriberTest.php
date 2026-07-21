<?php

/**
 * Isolated unit tests for AskCopilotMenuSubscriber menu injection.
 *
 * @package   OpenEMR
 * @link      https://www.open-emr.org
 * @author    eweinhaus <eweinhaus@users.noreply.github.com>
 * @copyright Copyright (c) 2026 eweinhaus
 * @license   https://github.com/openemr/openemr/blob/master/LICENSE GNU General Public License 3
 */

declare(strict_types=1);

namespace OpenEMR\Tests\Isolated\ClinicalCopilot;

use OpenEMR\ClinicalCopilot\Menu\AskCopilotMenuSubscriber;
use OpenEMR\Menu\MenuEvent;
use PHPUnit\Framework\Attributes\DataProvider;
use PHPUnit\Framework\Attributes\Small;
use PHPUnit\Framework\TestCase;
use stdClass;

#[Small]
class AskCopilotMenuSubscriberTest extends TestCase
{
    /**
     * @codeCoverageIgnore PHPUnit lifecycle hook; bootstrap translation helpers only.
     */
    public static function setUpBeforeClass(): void
    {
        $helpers = realpath(__DIR__ . '/../../../../library/htmlspecialchars.inc.php');
        if ($helpers !== false && !function_exists('xlt')) {
            require_once $helpers;
        }
        $GLOBALS['disable_translation'] = true;
    }

    /**
     * @codeCoverageIgnore PHPUnit lifecycle hook.
     */
    public static function tearDownAfterClass(): void
    {
        unset($GLOBALS['disable_translation']);
    }

    /**
     * @param list<stdClass> $menu
     * @param list<string>   $expectedOrder menu_id sequence after injection
     */
    #[DataProvider('menuUpdateProvider')]
    public function testOnMenuUpdateInsertsAskCopilotItem(array $menu, array $expectedOrder): void
    {
        $event = new MenuEvent($menu);
        $subscriber = new AskCopilotMenuSubscriber();

        $result = $subscriber->onMenuUpdate($event);

        $this->assertSame($event, $result);

        $updated = $result->getMenu();
        $this->assertSame($expectedOrder, array_map(
            static fn (stdClass $item): string => (string) $item->menu_id,
            $updated
        ));

        $askIndex = array_search('acp0', $expectedOrder, true);
        $this->assertNotFalse($askIndex);
        $askItem = $updated[$askIndex];

        $this->assertSame(0, $askItem->requirement);
        $this->assertSame('acp', $askItem->target);
        $this->assertSame('acp0', $askItem->menu_id);
        $this->assertSame('Ask Co-Pilot', $askItem->label);
        $this->assertSame('/interface/ask_copilot/index.php', $askItem->url);
        $this->assertSame(['patients', 'demo'], $askItem->acl_req);
        $this->assertSame([], $askItem->children);
    }

    /**
     * @return array<string, array{list<stdClass>, list<string>}>
     *
     * @codeCoverageIgnore Data providers run before coverage instrumentation starts.
     */
    public static function menuUpdateProvider(): array
    {
        return [
            'inserts after Messages (msg0)' => [
                [
                    self::menuItem('cal0', 'Calendar'),
                    self::menuItem('msg0', 'Messages'),
                    self::menuItem('pat0', 'Patient'),
                ],
                ['cal0', 'msg0', 'acp0', 'pat0'],
            ],
            'prepends when Messages (msg0) is missing' => [
                [
                    self::menuItem('cal0', 'Calendar'),
                    self::menuItem('pat0', 'Patient'),
                ],
                ['acp0', 'cal0', 'pat0'],
            ],
            'prepends into empty menu' => [
                [],
                ['acp0'],
            ],
        ];
    }

    private static function menuItem(string $menuId, string $label): stdClass
    {
        $item = new stdClass();
        $item->menu_id = $menuId;
        $item->label = $label;
        $item->requirement = 0;
        $item->target = $menuId;
        $item->url = '/interface/example.php';
        $item->children = [];
        $item->acl_req = [];

        return $item;
    }
}
