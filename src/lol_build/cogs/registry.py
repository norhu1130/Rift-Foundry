"""Champion Cog lifecycle and name/ID resolution."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

from lol_build.cogs.base import ChampionCog
from lol_build.cogs.manifest import CHAMPION_COG_BY_KEY, require_champion_cog_spec


class ChampionCogRegistry:
    """Manage Cog lifecycle and collision-safe champion alias resolution."""

    def __init__(self) -> None:
        """Create an empty registry.

        :return: None.
        """
        self._by_name: dict[str, ChampionCog] = {}
        self._canonical: dict[str, ChampionCog] = {}

    def add_cog(self, cog: ChampionCog, *, override: bool = False) -> None:
        """Register one Cog under all stable aliases.

        :param cog: Role-neutral champion extension to register.
        :param override: Replace an existing Cog with the same canonical name.
        :return: None.
        :raises ValueError: If a canonical name or alias collides.
        """
        existing = self._canonical.get(cog.qualified_name)
        if existing is not None and not override:
            raise ValueError(f"champion Cog already registered: {cog.qualified_name}")
        if existing is not None:
            self.remove_cog(existing.qualified_name)
        self._canonical[cog.qualified_name] = cog
        for alias in cog.aliases | {cog.qualified_name.casefold()}:
            owner = self._by_name.get(alias)
            if owner is not None and owner is not cog:
                raise ValueError(f"champion Cog alias collision: {alias}")
            self._by_name[alias] = cog

    def get_cog(self, name_or_id: str | int) -> ChampionCog | None:
        """Resolve a champion alias without raising.

        :param name_or_id: Champion name, Data Dragon ID, or numeric key.
        :return: Registered Cog, or ``None`` when unknown.
        """
        return self._by_name.get(str(name_or_id).casefold())

    def require_cog(self, name_or_id: str | int) -> ChampionCog:
        """Resolve a champion alias and require a match.

        :param name_or_id: Champion name, Data Dragon ID, or numeric key.
        :return: Registered champion Cog.
        :raises KeyError: If no Cog owns the alias.
        """
        cog = self.get_cog(name_or_id)
        if cog is None:
            raise KeyError(f"unknown champion: {name_or_id}")
        return cog

    def remove_cog(self, name_or_id: str | int) -> ChampionCog | None:
        """Remove a Cog and every alias that refers to it.

        :param name_or_id: Any registered alias or canonical Cog name.
        :return: Removed Cog, or ``None`` when not registered.
        """
        cog = self.get_cog(name_or_id)
        if cog is None and str(name_or_id) in self._canonical:
            cog = self._canonical[str(name_or_id)]
        if cog is None:
            return None
        self._canonical.pop(cog.qualified_name, None)
        self._by_name = {key: value for key, value in self._by_name.items() if value is not cog}
        return cog

    def walk_cogs(self) -> Iterator[ChampionCog]:
        """Iterate canonical Cogs in deterministic name order.

        :return: Iterator over each registered Cog exactly once.
        """
        yield from (self._canonical[key] for key in sorted(self._canonical))


def create_default_registry(root: Path) -> ChampionCogRegistry:
    """Load all locked champions and install specialized Cogs where available.

    :param root: Project root containing the locked champion snapshots.
    :return: Fully populated default registry.
    """
    catalog = json.loads(
        (root / "data/raw/16.17.1/en_US/champion.json").read_text(encoding="utf-8")
    )["data"]
    catalog_keys = set(catalog)
    manifest_keys = set(CHAMPION_COG_BY_KEY)
    if catalog_keys != manifest_keys:
        missing = sorted(catalog_keys - manifest_keys)
        stale = sorted(manifest_keys - catalog_keys)
        raise ValueError(
            f"champion Cog manifest does not match locked roster: missing={missing}, stale={stale}"
        )
    registry = ChampionCogRegistry()
    for document in catalog.values():
        detail_path = (
            root
            / "data/raw/16.17.1/communitydragon/champions"
            / f"{document['id'].casefold()}.bin.json"
        )
        detail_root = None
        detail_document = None
        if detail_path.exists():
            detail_document = json.loads(detail_path.read_text(encoding="utf-8"))
            expected_root = f"Characters/{document['id']}/CharacterRecords/Root".casefold()
            detail_root = next(
                (
                    value
                    for key, value in detail_document.items()
                    if key.casefold() == expected_root
                ),
                None,
            )
        cog_class = require_champion_cog_spec(document["id"]).load_class()
        cog = cog_class(document, detail_root, detail_document)
        registry.add_cog(cog)
    return registry
