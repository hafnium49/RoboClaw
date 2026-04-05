"""Embodiment catalog — aggregates all registries into a unified lookup."""
from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from roboclaw.embodied.embodiment.base import EmbodimentSpec


class EmbodimentCategory(str, Enum):
    ARM = "arm"
    HAND = "hand"
    HUMANOID = "humanoid"
    MOBILE = "mobile"


def categories() -> list[EmbodimentCategory]:
    """Return all embodiment categories."""
    return list(EmbodimentCategory)


def models_for(category: EmbodimentCategory) -> list[EmbodimentSpec]:
    """Return all registered specs for a category."""
    if category == EmbodimentCategory.ARM:
        from roboclaw.embodied.embodiment.arm.registry import all_arm_specs
        return list(all_arm_specs().values())
    if category == EmbodimentCategory.HAND:
        from roboclaw.embodied.embodiment.hand.registry import all_hand_specs
        return list(all_hand_specs().values())
    return []


def get_spec(name: str) -> EmbodimentSpec:
    """Look up any embodiment spec by name, across all registries."""
    from roboclaw.embodied.embodiment.arm.registry import get_arm_spec_by_name
    from roboclaw.embodied.embodiment.hand.registry import get_hand_spec

    name = name.lower()
    try:
        return get_arm_spec_by_name(name)
    except ValueError:
        pass
    try:
        return get_hand_spec(name)
    except ValueError:
        raise ValueError(f"Unknown embodiment model: '{name}'")


def is_supported(category: EmbodimentCategory) -> bool:
    """Return True if the category has registered models."""
    return len(models_for(category)) > 0
