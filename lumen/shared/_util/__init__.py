"""Private pure utility helpers shared across lumen layers.

The leading underscore marks this subpackage as *not* a plugin provider — these
are stateless helpers (file I/O, language directives). Modes and plugins may
import them for utility only; they do not broker any dependency between
plugins. The rule "a mode depends only on Contracts" concerns *providers*, not
pure shared utilities.
"""