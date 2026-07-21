<?php

/**
 * Injects the Ask Co-Pilot top-level menu item via MenuEvent::MENU_UPDATE.
 *
 * @package   OpenEMR
 * @link      https://www.open-emr.org
 * @author    eweinhaus <eweinhaus@users.noreply.github.com>
 * @copyright Copyright (c) 2026 eweinhaus
 * @license   https://github.com/openemr/openemr/blob/master/LICENSE GNU General Public License 3
 */

declare(strict_types=1);

namespace OpenEMR\ClinicalCopilot\Menu;

use OpenEMR\Menu\MenuEvent;
use stdClass;
use Symfony\Component\EventDispatcher\EventSubscriberInterface;

final class AskCopilotMenuSubscriber implements EventSubscriberInterface
{
    /**
     * @return array<string, string>
     */
    public static function getSubscribedEvents(): array
    {
        return [
            MenuEvent::MENU_UPDATE => 'onMenuUpdate',
        ];
    }

    public function onMenuUpdate(MenuEvent $event): MenuEvent
    {
        $menu = array_values($event->getMenu());
        $item = $this->buildMenuItem();

        $insertIndex = 0;
        foreach ($menu as $index => $existing) {
            if (($existing->menu_id ?? null) === 'msg0') {
                $insertIndex = $index + 1;
                break;
            }
        }

        array_splice($menu, $insertIndex, 0, [$item]);
        $event->setMenu($menu);

        return $event;
    }

    private function buildMenuItem(): stdClass
    {
        $item = new stdClass();
        $item->requirement = 0;
        $item->target = 'acp';
        $item->menu_id = 'acp0';
        $item->label = xlt('Ask Co-Pilot');
        $item->url = '/interface/ask_copilot/index.php';
        $item->children = [];
        $item->acl_req = ['patients', 'demo'];

        return $item;
    }
}
