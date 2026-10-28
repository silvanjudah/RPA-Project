"""Portal registry: name -> adapter class."""

from __future__ import annotations

from .aggregate import AggregatePortal
from .arbeitnow import ArbeitnowPortal
from .base import BasePortal, BusinessError
from .hasjob import HasjobPortal
from .himalayas import HimalayasPortal
from .internshala import InternshalaPortal
from .jobicy import JobicyPortal
from .python_jobs import PythonJobsPortal
from .remoteok import RemoteOkPortal
from .shine import ShinePortal
from .weworkremotely import WeWorkRemotelyPortal
from .workingnomads import WorkingNomadsPortal
from .ycombinator import YCombinatorPortal

PORTALS: dict[str, type[BasePortal]] = {
    ArbeitnowPortal.name: ArbeitnowPortal,
    HasjobPortal.name: HasjobPortal,
    HimalayasPortal.name: HimalayasPortal,
    InternshalaPortal.name: InternshalaPortal,
    JobicyPortal.name: JobicyPortal,
    PythonJobsPortal.name: PythonJobsPortal,
    RemoteOkPortal.name: RemoteOkPortal,
    ShinePortal.name: ShinePortal,
    WeWorkRemotelyPortal.name: WeWorkRemotelyPortal,
    WorkingNomadsPortal.name: WorkingNomadsPortal,
    YCombinatorPortal.name: YCombinatorPortal,
    AggregatePortal.name: AggregatePortal,
}

__all__ = [
    "PORTALS",
    "AggregatePortal",
    "ArbeitnowPortal",
    "BasePortal",
    "BusinessError",
    "HasjobPortal",
    "HimalayasPortal",
    "InternshalaPortal",
    "JobicyPortal",
    "PythonJobsPortal",
    "RemoteOkPortal",
    "ShinePortal",
    "WeWorkRemotelyPortal",
    "WorkingNomadsPortal",
    "YCombinatorPortal",
    "create_portal",
]


def create_portal(
    name: str,
    settings: dict,
    http,
    logger=None,
    registry: dict | None = None,
) -> BasePortal:
    try:
        portal_cls = PORTALS[name]
    except KeyError as exc:
        available = ", ".join(sorted(PORTALS))
        raise BusinessError(f"Unknown portal '{name}'. Available: {available}") from exc
    if portal_cls is AggregatePortal:
        return AggregatePortal(settings, http, logger, registry)
    return portal_cls(settings, http, logger)
