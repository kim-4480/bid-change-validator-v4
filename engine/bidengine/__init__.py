"""AI integration package for Bid Change Validator.

The production boundary starts from backend-managed notice/proposal document blocks.
Low-level file parsing and storage stay in backend services; this package owns
semantic chunking, requirement extraction adapters, retrieval evidence contracts,
judgment adapters, and change/revalidation logic.
"""

from bidengine.pipeline.analysis_pipeline import (
    QualificationAnalysisInput,
    QualificationDocumentInput,
    analyze_qualification_documents,
)
from bidengine.pipeline.analysis_result import AnalysisDiagnostic, RequirementAnalysisResult
from bidengine.contracts import Evidence, Judgment, QualificationRequirement

__all__ = [
    "QualificationRequirement",
    "Evidence",
    "Judgment",
    "AnalysisDiagnostic",
    "RequirementAnalysisResult",
    "QualificationDocumentInput",
    "QualificationAnalysisInput",
    "analyze_qualification_documents",
]
