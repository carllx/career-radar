"""
Career Radar - Autonomous career intelligence and recruitment tracking system.
"""

from .models import (
    CandidateProfile,
    DimensionEvaluation,
    EntityResolutionDecision,
    EvaluationResult,
    Opportunity,
    SourceObservation,
)
from .orchestrator import RadarOrchestrator, RadarRunOutcome
from .resolver import EntityResolutionApplier
from .retriever import CandidateRetriever
from .runner import IncrementalResolutionSession, run_radar_pipeline
from .sources import SourceLifecycleDecision, SourceRecord, SourceRegistry
from .store import OpportunityStore

__version__ = "0.1.0"

__all__ = [
    "CandidateProfile",
    "DimensionEvaluation",
    "EntityResolutionDecision",
    "EvaluationResult",
    "Opportunity",
    "SourceObservation",
    "RadarOrchestrator",
    "RadarRunOutcome",
    "EntityResolutionApplier",
    "CandidateRetriever",
    "IncrementalResolutionSession",
    "run_radar_pipeline",
    "SourceLifecycleDecision",
    "SourceRecord",
    "SourceRegistry",
    "OpportunityStore",
]
