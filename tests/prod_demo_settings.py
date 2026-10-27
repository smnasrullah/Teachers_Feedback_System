"""Production settings with the demo shortcut forced on: the system check must refuse them."""

from config.settings.prod import *  # noqa: F403

DEMO_SKIP_SECOND_FACTOR = True
