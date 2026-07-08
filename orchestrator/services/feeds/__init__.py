"""
feeds — Generic config-driven external data source adapters.

Add any external data source to a building by editing
  input/<building_id>/feeds.yaml
No Python changes required for new buildings or new sources.

Public surface:
    FeedSpec, FeedRecord, FeedAdapter (base.py)
    RestPollAdapter (rest_poll.py)
    CsvDropAdapter  (csv_drop.py)
    FeedRegistry    (registry.py)
"""

from orchestrator.services.feeds.base import FeedAdapter, FeedRecord, FeedSpec
from orchestrator.services.feeds.csv_drop import CsvDropAdapter
from orchestrator.services.feeds.registry import FeedRegistry
from orchestrator.services.feeds.rest_poll import RestPollAdapter

__all__ = [
    "FeedSpec",
    "FeedRecord",
    "FeedAdapter",
    "RestPollAdapter",
    "CsvDropAdapter",
    "FeedRegistry",
]
