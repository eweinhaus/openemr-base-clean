<?php

/**
 * Bootstrap for the Ask Co-Pilot custom module.
 *
 * Registers the menu subscriber only; domain logic lives in /src.
 *
 * @package   OpenEMR
 * @link      https://www.open-emr.org
 * @author    eweinhaus <eweinhaus@users.noreply.github.com>
 * @copyright Copyright (c) 2026 eweinhaus
 * @license   https://github.com/openemr/openemr/blob/master/LICENSE GNU General Public License 3
 */

use OpenEMR\ClinicalCopilot\Menu\AskCopilotMenuSubscriber;
use Symfony\Component\EventDispatcher\EventDispatcherInterface;

/**
 * @var EventDispatcherInterface $eventDispatcher
 * @var array                    $module
 * @global                       $eventDispatcher @see ModulesApplication::loadCustomModule
 * @global                       $module          @see ModulesApplication::loadCustomModule
 */

$eventDispatcher->addSubscriber(new AskCopilotMenuSubscriber());
