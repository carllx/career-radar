"""
Career Radar - Autonomous career intelligence and recruitment tracking system.
"""

from .models import (
    CANONICAL_TRACKS,
    CandidateProfile,
    DimensionEvaluation,
    EntityResolutionDecision,
    EvaluationResult,
    Opportunity,
    SourceObservation,
    calculate_chronological_age,
)
from .orchestrator import RadarOrchestrator, RadarRunOutcome
from .resolver import EntityResolutionApplier
from .retriever import CandidateRetriever
from .runner import IncrementalResolutionSession, run_radar_pipeline
from .sources import MonitoringFact, SourceLifecycleDecision, SourceRecord, SourceRegistry
from .store import OpportunityStore

__version__ = "0.1.0"

__all__ = [
    "CANONICAL_TRACKS",
    "CandidateProfile",
    "DimensionEvaluation",
    "EntityResolutionDecision",
    "EvaluationResult",
    "Opportunity",
    "SourceObservation",
    "calculate_chronological_age",
    "RadarOrchestrator",
    "RadarRunOutcome",
    "EntityResolutionApplier",
    "CandidateRetriever",
    "IncrementalResolutionSession",
    "run_radar_pipeline",
    "MonitoringFact",
    "SourceLifecycleDecision",
    "SourceRecord",
    "SourceRegistry",
    "OpportunityStore",
]
