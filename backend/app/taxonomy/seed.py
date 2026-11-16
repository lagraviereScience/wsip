"""Canonical taxonomy v1 and Steam mappings.

This file is the reviewed source of truth for the taxonomy. `python -m app.cli
sync-taxonomy` (run by the migrate service) upserts it into the database
idempotently. To change a mapping, edit it here and bump MAPPING_VERSION.
Earlier mapping versions are kept as `superseded` for provenance.

Hierarchy rule (spec §10): a provider tag maps to the most specific feature that
describes it. Parents are not filled in automatically, so scoring rolls a subtree
up with `max`, never `sum`, and evidence is never double counted.

Confidence expresses how faithfully the raw tag denotes the canonical feature:
0.95 near-synonym, 0.8 strong, 0.6 partial, 0.4 weak.
"""

from __future__ import annotations

from dataclasses import dataclass, field

TAXONOMY_VERSION = 1
MAPPING_VERSION = 1


@dataclass(frozen=True, slots=True)
class CategoryDef:
    slug: str
    name: str
    scoring_group: str
    sort_order: int
    description: str


@dataclass(frozen=True, slots=True)
class FeatureDef:
    slug: str
    name: str
    category: str
    parent: str | None = None
    synonyms: tuple[str, ...] = ()
    description: str | None = None


# Spec §16 weights apply per scoring_group. Genres and themes share one group.
CATEGORIES: tuple[CategoryDef, ...] = (
    CategoryDef("genre", "Genres", "genres_and_themes", 10, "What kind of game it is."),
    CategoryDef("theme", "Themes", "genres_and_themes", 20, "Setting, tone and subject matter."),
    CategoryDef(
        "mechanic", "Gameplay mechanics", "gameplay_mechanics", 30, "What the player actually does."
    ),
    CategoryDef("mode", "Game modes", "game_modes", 40, "Who the player plays with or against."),
    CategoryDef(
        "structure",
        "Game structure",
        "game_structure",
        50,
        "How the world and progression are organised.",
    ),
    CategoryDef(
        "pace",
        "Pace and complexity",
        "pace_and_complexity",
        60,
        "Tempo, difficulty and cognitive load.",
    ),
)


def _f(
    slug: str,
    name: str,
    category: str,
    parent: str | None = None,
    *synonyms: str,
    desc: str | None = None,
) -> FeatureDef:
    return FeatureDef(slug, name, category, parent, tuple(synonyms), desc)


FEATURES: tuple[FeatureDef, ...] = (
    # --- Genres ------------------------------------------------------------
    _f("action", "Action", "genre"),
    _f("shooter", "Shooter", "genre", "action"),
    _f("fps", "First-person shooter", "genre", "shooter", "FPS"),
    _f("third-person-shooter", "Third-person shooter", "genre", "shooter", "TPS"),
    _f("top-down-shooter", "Top-down / twin-stick shooter", "genre", "shooter"),
    _f("shmup", "Shoot 'em up / bullet hell", "genre", "shooter", "bullet hell"),
    _f("hero-shooter", "Hero shooter", "genre", "shooter"),
    _f("battle-royale", "Battle royale", "genre", "shooter"),
    _f("extraction-shooter", "Extraction shooter", "genre", "shooter"),
    _f("fighting", "Fighting", "genre", "action"),
    _f("beat-em-up", "Beat 'em up", "genre", "action"),
    _f("hack-and-slash", "Hack and slash", "genre", "action", "character action"),
    _f("platformer", "Platformer", "genre", "action"),
    _f("precision-platformer", "Precision platformer", "genre", "platformer"),
    _f("metroidvania", "Metroidvania", "genre", "platformer"),
    _f("rpg", "RPG", "genre", None, "role-playing game"),
    _f("action-rpg", "Action RPG", "genre", "rpg", "ARPG"),
    _f("souls-like", "Souls-like", "genre", "action-rpg"),
    _f("jrpg", "JRPG", "genre", "rpg"),
    _f("crpg", "CRPG / party-based RPG", "genre", "rpg"),
    _f("tactical-rpg", "Tactical RPG", "genre", "rpg", "SRPG"),
    _f("dungeon-crawler", "Dungeon crawler", "genre", "rpg"),
    _f("strategy", "Strategy", "genre"),
    _f("rts", "Real-time strategy", "genre", "strategy", "RTS"),
    _f("turn-based-strategy", "Turn-based strategy", "genre", "strategy", "TBS"),
    _f("grand-strategy", "Grand strategy", "genre", "strategy"),
    _f("4x", "4X", "genre", "strategy"),
    _f("tower-defense", "Tower defense", "genre", "strategy"),
    _f("auto-battler", "Auto battler", "genre", "strategy"),
    _f("wargame", "Wargame", "genre", "strategy"),
    _f("moba", "MOBA", "genre", "strategy"),
    _f("simulation", "Simulation", "genre"),
    _f("city-builder", "City builder", "genre", "simulation"),
    _f("colony-sim", "Colony sim", "genre", "simulation"),
    _f("management-sim", "Management sim", "genre", "simulation", "tycoon"),
    _f("life-sim", "Life sim", "genre", "simulation"),
    _f("farming-sim", "Farming sim", "genre", "life-sim"),
    _f("vehicle-sim", "Vehicle sim", "genre", "simulation", "driving sim", "flight sim"),
    _f("space-sim", "Space sim", "genre", "simulation"),
    _f("god-game", "God game", "genre", "simulation"),
    _f("adventure", "Adventure", "genre"),
    _f("action-adventure", "Action-adventure", "genre", "adventure"),
    _f("point-and-click", "Point and click", "genre", "adventure"),
    _f("visual-novel", "Visual novel", "genre", "adventure", "interactive fiction"),
    _f("walking-simulator", "Walking simulator", "genre", "adventure", "narrative exploration"),
    _f("immersive-sim", "Immersive sim", "genre", "adventure"),
    _f("puzzle", "Puzzle", "genre"),
    _f("horror", "Horror", "genre"),
    _f("survival-horror", "Survival horror", "genre", "horror"),
    _f("psychological-horror", "Psychological horror", "genre", "horror"),
    _f("survival", "Survival", "genre"),
    _f("survival-craft", "Open-world survival craft", "genre", "survival"),
    _f("roguelike", "Roguelike", "genre"),
    _f("roguelite", "Roguelite", "genre", "roguelike"),
    _f("action-roguelike", "Action roguelike", "genre", "roguelike"),
    _f("roguelike-deckbuilder", "Roguelike deckbuilder", "genre", "roguelike"),
    _f("traditional-roguelike", "Traditional roguelike", "genre", "roguelike"),
    _f("bullet-heaven", "Bullet heaven / survivors-like", "genre", "roguelike"),
    _f("card-board", "Card and board", "genre", None, "tabletop"),
    _f("card-game", "Card game", "genre", "card-board"),
    _f("board-game", "Board game", "genre", "card-board"),
    _f("racing", "Racing", "genre"),
    _f("sports", "Sports", "genre"),
    _f("rhythm", "Rhythm and music", "genre"),
    _f("party-game", "Party game", "genre"),
    _f("idle", "Idle / incremental", "genre", None, "clicker"),
    # --- Themes ------------------------------------------------------------
    _f("fantasy", "Fantasy", "theme"),
    _f("dark-fantasy", "Dark fantasy", "theme", "fantasy"),
    _f("sci-fi", "Science fiction", "theme", None, "sci-fi"),
    _f("cyberpunk", "Cyberpunk", "theme", "sci-fi"),
    _f("space", "Space", "theme", "sci-fi"),
    _f("post-apocalyptic", "Post-apocalyptic", "theme", "sci-fi"),
    _f("steampunk", "Steampunk", "theme", "sci-fi"),
    _f("historical", "Historical", "theme"),
    _f("medieval", "Medieval", "theme", "historical"),
    _f("military", "Military / war", "theme", None, "war"),
    _f("world-war", "World wars", "theme", "military"),
    _f("zombies", "Zombies", "theme"),
    _f("lovecraftian", "Lovecraftian", "theme"),
    _f("mystery", "Mystery / detective", "theme", None, "detective"),
    _f("crime", "Crime", "theme"),
    _f("comedy", "Comedy", "theme", None, "funny", "humor"),
    _f("cozy", "Cozy / wholesome", "theme", None, "wholesome", "cute"),
    _f("anime", "Anime", "theme"),
    _f("mythology", "Mythology", "theme"),
    _f("nature", "Nature and animals", "theme"),
    _f("dark", "Dark / mature tone", "theme"),
    _f("western", "Western", "theme"),
    _f("pirates", "Pirates and naval", "theme"),
    # --- Gameplay mechanics -------------------------------------------------
    _f("crafting", "Crafting", "mechanic"),
    _f("exploration", "Exploration", "mechanic"),
    _f("building", "Building", "mechanic"),
    _f("base-building", "Base building", "mechanic", "building"),
    _f("resource-management", "Resource management", "mechanic"),
    _f("combat", "Combat", "mechanic"),
    _f("turn-based-combat", "Turn-based combat", "mechanic", "combat"),
    _f("melee-combat", "Melee combat", "mechanic", "combat", "swordplay"),
    _f("vehicular-combat", "Vehicular combat", "mechanic", "combat"),
    _f("stealth", "Stealth", "mechanic"),
    _f("character-progression", "Character progression", "mechanic", None, "levelling"),
    _f("character-customization", "Character customisation", "mechanic", "character-progression"),
    _f("loot", "Loot", "mechanic", "character-progression"),
    _f("trading", "Trading and economy", "mechanic", None, "economy"),
    _f("automation", "Automation", "mechanic", None, "factory"),
    _f("farming", "Farming", "mechanic"),
    _f("deckbuilding", "Deckbuilding", "mechanic"),
    _f("physics", "Physics-based", "mechanic"),
    _f("puzzle-solving", "Puzzle solving", "mechanic"),
    _f("choices-matter", "Choices matter", "mechanic", None, "branching story"),
    _f("dialogue", "Dialogue-heavy", "mechanic"),
    _f("management", "Management", "mechanic"),
    _f("time-management", "Time management", "mechanic", "management"),
    _f("inventory-management", "Inventory management", "mechanic", "management"),
    _f("driving", "Driving and flying", "mechanic"),
    _f("platforming", "Platforming", "mechanic"),
    _f("programming", "Programming / hacking", "mechanic"),
    _f("creature-collection", "Creature collection", "mechanic"),
    _f("cooking", "Cooking", "mechanic"),
    _f("fishing-hunting", "Fishing and hunting", "mechanic"),
    _f("mining", "Mining", "mechanic"),
    _f("investigation", "Investigation", "mechanic"),
    _f("level-editor", "Level editor / modding", "mechanic", None, "moddable"),
    # --- Game modes -----------------------------------------------------------
    _f("singleplayer", "Singleplayer", "mode", None, "single-player"),
    _f("multiplayer", "Multiplayer", "mode", None, "multi-player"),
    _f("online-multiplayer", "Online multiplayer", "mode", "multiplayer"),
    _f("local-multiplayer", "Local multiplayer", "mode", "multiplayer", "split screen"),
    _f("co-op", "Co-op", "mode", "multiplayer", "cooperative"),
    _f("online-co-op", "Online co-op", "mode", "co-op"),
    _f("local-co-op", "Local co-op", "mode", "co-op"),
    _f("pvp", "PvP", "mode", "multiplayer", "player versus player"),
    _f("online-pvp", "Online PvP", "mode", "pvp"),
    _f("local-pvp", "Local PvP", "mode", "pvp"),
    _f("competitive", "Competitive", "mode", "pvp", "esports"),
    _f("mmo", "MMO", "mode", "online-multiplayer", "massively multiplayer"),
    _f("pve", "PvE", "mode", None, "player versus environment"),
    _f("asynchronous-multiplayer", "Asynchronous multiplayer", "mode", "multiplayer"),
    # --- Game structure ---------------------------------------------------
    _f("open-world", "Open world", "structure"),
    _f("linear", "Linear", "structure"),
    _f("nonlinear", "Nonlinear", "structure"),
    _f("sandbox", "Sandbox", "structure"),
    _f("procedural-generation", "Procedural generation", "structure"),
    _f("mission-based", "Mission-based", "structure"),
    _f("level-based", "Level-based", "structure"),
    _f("persistent-world", "Persistent world", "structure"),
    _f("narrative-driven", "Narrative-driven", "structure", None, "story rich"),
    _f("multiple-endings", "Multiple endings", "structure", "narrative-driven"),
    _f("episodic", "Episodic", "structure"),
    _f("short", "Short", "structure"),
    _f("replayable", "High replayability", "structure"),
    _f("permadeath", "Permadeath", "structure"),
    # --- Pace and complexity ----------------------------------------------
    _f("relaxed", "Relaxed", "pace", None, "relaxing", "chill"),
    _f("casual", "Casual", "pace"),
    _f("tactical", "Tactical", "pace"),
    _f("turn-based", "Turn-based", "pace"),
    _f("real-time", "Real-time", "pace"),
    _f("real-time-with-pause", "Real-time with pause", "pace", "real-time"),
    _f("fast-paced", "Fast-paced", "pace"),
    _f("hardcore", "Hardcore / difficult", "pace", None, "difficult", "unforgiving"),
    _f("complex-management", "Complex management", "pace"),
    _f("survival-oriented", "Survival-oriented", "pace"),
)


@dataclass(frozen=True, slots=True)
class MappingDef:
    feature: str
    confidence: float


@dataclass(frozen=True, slots=True)
class ProviderMappings:
    provider: str
    tag_kind: str
    mappings: dict[str, tuple[MappingDef, ...]] = field(default_factory=dict)


def _m(*pairs: tuple[str, float]) -> tuple[MappingDef, ...]:
    return tuple(MappingDef(f, c) for f, c in pairs)


# Steam user tags (IStoreService/GetTagList names, English). Unlisted tags stay
# unmapped and are kept as raw provenance only.
STEAM_TAGS = ProviderMappings(
    "steam_store",
    "tag",
    {
        "Action": _m(("action", 0.9)),
        "Shooter": _m(("shooter", 0.95)),
        "FPS": _m(("fps", 0.95)),
        "Boomer Shooter": _m(("fps", 0.9), ("fast-paced", 0.6)),
        "Arena Shooter": _m(("fps", 0.7), ("competitive", 0.5)),
        "Third-Person Shooter": _m(("third-person-shooter", 0.95)),
        "Top-Down Shooter": _m(("top-down-shooter", 0.95)),
        "Twin Stick Shooter": _m(("top-down-shooter", 0.9)),
        "Shoot 'Em Up": _m(("shmup", 0.95)),
        "Bullet Hell": _m(("shmup", 0.9), ("hardcore", 0.4)),
        "Hero Shooter": _m(("hero-shooter", 0.95)),
        "Battle Royale": _m(("battle-royale", 0.95)),
        "Extraction Shooter": _m(("extraction-shooter", 0.95)),
        "Looter Shooter": _m(("shooter", 0.8), ("loot", 0.8)),
        "Fighting": _m(("fighting", 0.95)),
        "2D Fighter": _m(("fighting", 0.95)),
        "3D Fighter": _m(("fighting", 0.95)),
        "Martial Arts": _m(("fighting", 0.6)),
        "Beat 'em up": _m(("beat-em-up", 0.95)),
        "Hack and Slash": _m(("hack-and-slash", 0.95), ("melee-combat", 0.8)),
        "Character Action Game": _m(("hack-and-slash", 0.8)),
        "Spectacle fighter": _m(("hack-and-slash", 0.8)),
        "Musou": _m(("hack-and-slash", 0.8)),
        "Platformer": _m(("platformer", 0.95), ("platforming", 0.9)),
        "2D Platformer": _m(("platformer", 0.95), ("platforming", 0.9)),
        "3D Platformer": _m(("platformer", 0.95), ("platforming", 0.9)),
        "Puzzle Platformer": _m(("platformer", 0.8), ("puzzle-solving", 0.8)),
        "Precision Platformer": _m(("precision-platformer", 0.95), ("hardcore", 0.6)),
        "Metroidvania": _m(("metroidvania", 0.95), ("exploration", 0.6)),
        "RPG": _m(("rpg", 0.95), ("character-progression", 0.6)),
        "Action RPG": _m(("action-rpg", 0.95)),
        "Souls-like": _m(("souls-like", 0.95), ("hardcore", 0.8)),
        "JRPG": _m(("jrpg", 0.95)),
        "CRPG": _m(("crpg", 0.95)),
        "Party-Based RPG": _m(("crpg", 0.8)),
        "Tactical RPG": _m(("tactical-rpg", 0.95), ("tactical", 0.8)),
        "Strategy RPG": _m(("tactical-rpg", 0.8)),
        "Dungeon Crawler": _m(("dungeon-crawler", 0.95)),
        "MMORPG": _m(("rpg", 0.8), ("mmo", 0.95), ("persistent-world", 0.8)),
        "Strategy": _m(("strategy", 0.95)),
        "RTS": _m(("rts", 0.95), ("real-time", 0.8)),
        "Action RTS": _m(("rts", 0.8)),
        "Real Time Tactics": _m(("rts", 0.6), ("tactical", 0.8), ("real-time", 0.8)),
        "Turn-Based Strategy": _m(("turn-based-strategy", 0.95), ("turn-based", 0.9)),
        "Turn-Based Tactics": _m(
            ("turn-based-strategy", 0.7), ("tactical", 0.9), ("turn-based", 0.9)
        ),
        "Grand Strategy": _m(("grand-strategy", 0.95), ("complex-management", 0.7)),
        "4X": _m(("4x", 0.95), ("complex-management", 0.6)),
        "Tower Defense": _m(("tower-defense", 0.95)),
        "Auto Battler": _m(("auto-battler", 0.95)),
        "Wargame": _m(("wargame", 0.95)),
        "MOBA": _m(("moba", 0.95), ("competitive", 0.8)),
        "Simulation": _m(("simulation", 0.9)),
        "City Builder": _m(("city-builder", 0.95), ("building", 0.7)),
        "Colony Sim": _m(("colony-sim", 0.95), ("resource-management", 0.7)),
        "Management": _m(("management", 0.9), ("management-sim", 0.6)),
        "Life Sim": _m(("life-sim", 0.95)),
        "Farming Sim": _m(("farming-sim", 0.95), ("farming", 0.9)),
        "Driving": _m(("driving", 0.95)),
        "Automobile Sim": _m(("vehicle-sim", 0.9), ("driving", 0.9)),
        "Flight": _m(("vehicle-sim", 0.7), ("driving", 0.8)),
        "Space Sim": _m(("space-sim", 0.95), ("space", 0.8)),
        "God Game": _m(("god-game", 0.95)),
        "Job Simulator": _m(("simulation", 0.7)),
        "Adventure": _m(("adventure", 0.9)),
        "Action-Adventure": _m(("action-adventure", 0.95)),
        "Point & Click": _m(("point-and-click", 0.95)),
        "Visual Novel": _m(("visual-novel", 0.95), ("narrative-driven", 0.7)),
        "Interactive Fiction": _m(("visual-novel", 0.7), ("narrative-driven", 0.7)),
        "Choose Your Own Adventure": _m(("visual-novel", 0.6), ("choices-matter", 0.8)),
        "Walking Simulator": _m(("walking-simulator", 0.95), ("relaxed", 0.5)),
        "Immersive Sim": _m(("immersive-sim", 0.95)),
        "Puzzle": _m(("puzzle", 0.95), ("puzzle-solving", 0.9)),
        "Logic": _m(("puzzle", 0.6), ("puzzle-solving", 0.7)),
        "Sokoban": _m(("puzzle", 0.8)),
        "Match 3": _m(("puzzle", 0.8), ("casual", 0.6)),
        "Hidden Object": _m(("puzzle", 0.6), ("casual", 0.6)),
        "Escape Room": _m(("puzzle", 0.8)),
        "Horror": _m(("horror", 0.95)),
        "Survival Horror": _m(("survival-horror", 0.95)),
        "Psychological Horror": _m(("psychological-horror", 0.95)),
        "Survival": _m(("survival", 0.95), ("survival-oriented", 0.8)),
        "Open World Survival Craft": _m(
            ("survival-craft", 0.95), ("crafting", 0.8), ("open-world", 0.7)
        ),
        "Roguelike": _m(("roguelike", 0.9), ("procedural-generation", 0.6), ("permadeath", 0.6)),
        "Roguelite": _m(("roguelite", 0.95), ("procedural-generation", 0.6)),
        "Action Roguelike": _m(("action-roguelike", 0.95)),
        "Roguelike Deckbuilder": _m(("roguelike-deckbuilder", 0.95), ("deckbuilding", 0.9)),
        "Traditional Roguelike": _m(("traditional-roguelike", 0.95), ("turn-based", 0.7)),
        "Bullet Heaven": _m(("bullet-heaven", 0.95)),
        "Card Game": _m(("card-game", 0.95)),
        "Card Battler": _m(("card-game", 0.9)),
        "Trading Card Game": _m(("card-game", 0.9)),
        "Deckbuilding": _m(("deckbuilding", 0.95)),
        "Board Game": _m(("board-game", 0.95)),
        "Tabletop": _m(("card-board", 0.8)),
        "Chess": _m(("board-game", 0.9)),
        "Racing": _m(("racing", 0.95)),
        "Combat Racing": _m(("racing", 0.9), ("vehicular-combat", 0.8)),
        "Sports": _m(("sports", 0.95)),
        "Football (Soccer)": _m(("sports", 0.95)),
        "Basketball": _m(("sports", 0.95)),
        "Golf": _m(("sports", 0.95)),
        "Rhythm": _m(("rhythm", 0.95)),
        "Music": _m(("rhythm", 0.5)),
        "Party Game": _m(("party-game", 0.95)),
        "Party": _m(("party-game", 0.8)),
        "Idler": _m(("idle", 0.95)),
        "Incremental": _m(("idle", 0.8)),
        "Clicker": _m(("idle", 0.8)),
        # Themes
        "Fantasy": _m(("fantasy", 0.95)),
        "Dark Fantasy": _m(("dark-fantasy", 0.95)),
        "Magic": _m(("fantasy", 0.6)),
        "Sci-fi": _m(("sci-fi", 0.95)),
        "Futuristic": _m(("sci-fi", 0.7)),
        "Cyberpunk": _m(("cyberpunk", 0.95)),
        "Space": _m(("space", 0.95)),
        "Post-apocalyptic": _m(("post-apocalyptic", 0.95)),
        "Steampunk": _m(("steampunk", 0.95)),
        "Historical": _m(("historical", 0.95)),
        "Medieval": _m(("medieval", 0.95)),
        "Military": _m(("military", 0.95)),
        "War": _m(("military", 0.9)),
        "World War II": _m(("world-war", 0.95)),
        "World War I": _m(("world-war", 0.95)),
        "Zombies": _m(("zombies", 0.95)),
        "Lovecraftian": _m(("lovecraftian", 0.95)),
        "Mystery": _m(("mystery", 0.95)),
        "Detective": _m(("mystery", 0.9), ("investigation", 0.8)),
        "Crime": _m(("crime", 0.95)),
        "Comedy": _m(("comedy", 0.95)),
        "Funny": _m(("comedy", 0.8)),
        "Cozy": _m(("cozy", 0.95), ("relaxed", 0.7)),
        "Wholesome": _m(("cozy", 0.9)),
        "Cute": _m(("cozy", 0.6)),
        "Anime": _m(("anime", 0.95)),
        "Mythology": _m(("mythology", 0.95)),
        "Nature": _m(("nature", 0.9)),
        "Animals": _m(("nature", 0.8)),
        "Dark": _m(("dark", 0.9)),
        "Western": _m(("western", 0.95)),
        "Pirates": _m(("pirates", 0.95)),
        "Naval": _m(("pirates", 0.6)),
        # Mechanics
        "Crafting": _m(("crafting", 0.95)),
        "Exploration": _m(("exploration", 0.95)),
        "Building": _m(("building", 0.95)),
        "Base Building": _m(("base-building", 0.95)),
        "Resource Management": _m(("resource-management", 0.95)),
        "Combat": _m(("combat", 0.95)),
        "Turn-Based Combat": _m(("turn-based-combat", 0.95), ("turn-based", 0.8)),
        "Swordplay": _m(("melee-combat", 0.9)),
        "Vehicular Combat": _m(("vehicular-combat", 0.95)),
        "Stealth": _m(("stealth", 0.95)),
        "Character Customization": _m(("character-customization", 0.95)),
        "Loot": _m(("loot", 0.95)),
        "Trading": _m(("trading", 0.95)),
        "Economy": _m(("trading", 0.8), ("resource-management", 0.5)),
        "Capitalism": _m(("trading", 0.6)),
        "Automation": _m(("automation", 0.95)),
        "Farming": _m(("farming", 0.95)),
        "Agriculture": _m(("farming", 0.9)),
        "Physics": _m(("physics", 0.95)),
        "Choices Matter": _m(("choices-matter", 0.95)),
        "Dialogue Heavy": _m(("dialogue", 0.95)),
        "Conversation": _m(("dialogue", 0.8)),
        "Time Management": _m(("time-management", 0.95)),
        "Inventory Management": _m(("inventory-management", 0.95)),
        "Programming": _m(("programming", 0.95)),
        "Hacking": _m(("programming", 0.8)),
        "Coding": _m(("programming", 0.9)),
        "Creature Collector": _m(("creature-collection", 0.95)),
        "Cooking": _m(("cooking", 0.95)),
        "Fishing": _m(("fishing-hunting", 0.95)),
        "Hunting": _m(("fishing-hunting", 0.95)),
        "Mining": _m(("mining", 0.95)),
        "Investigation": _m(("investigation", 0.95)),
        "Level Editor": _m(("level-editor", 0.95)),
        "Moddable": _m(("level-editor", 0.7)),
        # Modes (Steam categories are the primary source; tags add evidence)
        "Singleplayer": _m(("singleplayer", 0.9)),
        "Multiplayer": _m(("multiplayer", 0.9)),
        "Massively Multiplayer": _m(("mmo", 0.95), ("persistent-world", 0.7)),
        "Co-op": _m(("co-op", 0.95)),
        "Online Co-Op": _m(("online-co-op", 0.95)),
        "Local Co-Op": _m(("local-co-op", 0.95)),
        "Co-op Campaign": _m(("co-op", 0.9)),
        "Local Multiplayer": _m(("local-multiplayer", 0.95)),
        "Split Screen": _m(("local-multiplayer", 0.9)),
        "4 Player Local": _m(("local-multiplayer", 0.9)),
        "PvP": _m(("pvp", 0.95)),
        "PvE": _m(("pve", 0.95)),
        "Competitive": _m(("competitive", 0.95)),
        "eSports": _m(("competitive", 0.9)),
        "Team-Based": _m(("multiplayer", 0.6)),
        "Asynchronous Multiplayer": _m(("asynchronous-multiplayer", 0.95)),
        # Structure
        "Open World": _m(("open-world", 0.95)),
        "Linear": _m(("linear", 0.95)),
        "Nonlinear": _m(("nonlinear", 0.95)),
        "Sandbox": _m(("sandbox", 0.95)),
        "Procedural Generation": _m(("procedural-generation", 0.95)),
        "Story Rich": _m(("narrative-driven", 0.9)),
        "Narrative": _m(("narrative-driven", 0.8)),
        "Multiple Endings": _m(("multiple-endings", 0.95)),
        "Episodic": _m(("episodic", 0.95)),
        "Short": _m(("short", 0.95)),
        "Replay Value": _m(("replayable", 0.9)),
        "Perma Death": _m(("permadeath", 0.95)),
        "Score Attack": _m(("level-based", 0.5)),
        "Time Attack": _m(("level-based", 0.5)),
        # Pace and complexity
        "Relaxing": _m(("relaxed", 0.95)),
        "Casual": _m(("casual", 0.95)),
        "Family Friendly": _m(("casual", 0.6)),
        "Tactical": _m(("tactical", 0.95)),
        "Turn-Based": _m(("turn-based", 0.95)),
        "Real-Time": _m(("real-time", 0.95)),
        "Real-Time with Pause": _m(("real-time-with-pause", 0.95)),
        "Fast-Paced": _m(("fast-paced", 0.95)),
        "Difficult": _m(("hardcore", 0.95)),
        "Unforgiving": _m(("hardcore", 0.9)),
    },
)

# Steam store categories (IStoreBrowseService/GetStoreCategories, player-support
# type). Declared by developers, so more reliable for game modes than user tags.
STEAM_CATEGORIES = ProviderMappings(
    "steam_store",
    "category",
    {
        "Single-player": _m(("singleplayer", 0.95)),
        "Multi-player": _m(("multiplayer", 0.95)),
        "MMO": _m(("mmo", 0.95), ("persistent-world", 0.6)),
        "PvP": _m(("pvp", 0.95)),
        "Online PvP": _m(("online-pvp", 0.95)),
        "LAN PvP": _m(("local-pvp", 0.8)),
        "Shared/Split Screen PvP": _m(("local-pvp", 0.95)),
        "Co-op": _m(("co-op", 0.95)),
        "Online Co-op": _m(("online-co-op", 0.95)),
        "LAN Co-op": _m(("local-co-op", 0.8)),
        "Shared/Split Screen Co-op": _m(("local-co-op", 0.95)),
        "Shared/Split Screen": _m(("local-multiplayer", 0.95)),
        "Cross-Platform Multiplayer": _m(("online-multiplayer", 0.7)),
    },
)

PROVIDER_MAPPINGS: tuple[ProviderMappings, ...] = (STEAM_TAGS, STEAM_CATEGORIES)
