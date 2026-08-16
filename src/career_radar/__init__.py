"""
Career Radar - Autonomous career intelligence and recruitment tracking system.
"""

from .acquisition import (
    AcquisitionResult,
    SourceAcquisitionExecutor,
    SourceAcquisitionSessionResult,
    execute_production_acquisition,
)
from .evaluator import (
    IntentValidator,
    MarketIntelligenceValidator,
    build_evaluation_packet,
    build_intent_packet,
    build_market_intelligence_packet,
)
from .models import (
    CANONICAL_MARKET_INTELLIGENCE_FIELDS,
    CANONICAL_TRACKS,
    MARKET_INTELLIGENCE_UNKNOWN,
    VALID_OPPORTUNITY_INTENTS,
    CandidateProfile,
    DimensionEvaluation,
    EntityResolutionDecision,
    EvaluationResult,
    MarketIntelligence,
    Opportunity,
    OpportunityIntentDecision,
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
    "CANONICAL_MARKET_INTELLIGENCE_FIELDS",
    "MARKET_INTELLIGENCE_UNKNOWN",
    "VALID_OPPORTUNITY_INTENTS",
    "AcquisitionResult",
    "SourceAcquisitionExecutor",
    "SourceAcquisitionSessionResult",
    "execute_production_acquisition",
    "CandidateProfile",
    "DimensionEvaluation",
    "EntityResolutionDecision",
    "EvaluationResult",
    "MarketIntelligence",
    "Opportunity",
    "OpportunityIntentDecision",
    "SourceObservation",
    "calculate_chronological_age",
    "build_evaluation_packet",
    "build_intent_packet",
    "build_market_intelligence_packet",
    "IntentValidator",
    "MarketIntelligenceValidator",
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

