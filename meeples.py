"""The class-meeple artwork in `Meeples svg/`, and which piece plays which role.

The artwork is third-party: "RPG Meeples" by Xykit,
https://www.printables.com/model/212336-rpg-meeples -- personal use only,
commercial use through the author's merchant program. The credit is carried on
the generated reference pages by `assembly.CREDIT_LINE` and in their metadata;
keep it there, and keep it on anything else these files end up on.

Loading is done by `artload`, which separates the black outline (to cut) from
the green detail lines (to engrave) -- the convention the source files already
use. Keeping those apart matters: feeding the green paths into the silhouette
mask would punch them out as holes under the even-odd fill rule.

Drop more artwork into the folder and it becomes available by filename.
"""

import artload

SOURCE_DIR = "Meeples svg"

# The set is 16 D&D classes plus King and Queen. These six ship as the player
# characters; the rest are available by name for anyone who wants to swap.
HEROES = ["Fighter", "Mage", "Rogue", "Cleric", "Ranger", "Bard"]
# Cut on sheet C as named NPCs rather than generic monsters.
NPCS = ["King", "Queen", "Warlock"]


def available():
    return artload.names(SOURCE_DIR)


def load(name):
    """(cut, engrave, (w, h)) in mm, top-left of the outline at (0, 0)."""
    return artload.load(name, SOURCE_DIR)


def fitted(name, box_w, box_h):
    """Scaled to the largest size fitting inside box_w x box_h mm."""
    return artload.fitted(name, box_w, box_h, SOURCE_DIR)


def bottom_width(subpaths, depth):
    return artload.bottom_width(subpaths, depth)
