"""Feature construction for the TF-IDF baseline.

The design doc (sections 6.2 and 6.4) asks for two things that are kept
strictly apart here:

* **Text features** -- opcode n-grams over the decoded instruction stream.
  Two independent vocabularies are fitted, one over the raw token stream
  and one over the normalised token stream.
* **Graph features** -- deterministic numeric signals taken from the
  control-flow graph (block counts, unresolved jumps, cycles, call and
  storage sites).

The two text views are fitted separately from the numeric view and are
hstacked only at transform time, so a signal can always be traced back to
the representation that produced it.

Vocabulary is fitted on the training corpus only. The builder refuses to
transform before it has been fitted, and the fitted vocabulary is persisted
inside the model artifact so inference reuses exactly the same terms.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np
from evm_analysis import build_cfg, disassemble, extract_features, load_fork
from scipy.sparse import csr_matrix, hstack
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.preprocessing import StandardScaler

from .dataset import Sample
from .tokenize import Normalization, build_ngrams, tokenize

__all__ = [
    "FeatureBuilder",
    "FeatureConfig",
    "GraphFeature",
    "analyse",
    "GRAPH_FEATURE_NAMES",
]


@dataclass(frozen=True)
class FeatureConfig:
    """Configuration of the feature pipeline.

    The defaults are the MVP settings: 1-to-3 character n-grams over the
    opcode token stream, as required by design doc section 6.2.
    """

    fork: str = "cancun"
    ngram_min: int = 1
    ngram_max: int = 3
    include_graph_features: bool = True
    normalization: Normalization = field(default_factory=Normalization)

    def as_dict(self) -> dict[str, Any]:
        return {
            "fork": self.fork,
            "ngram_min": self.ngram_min,
            "ngram_max": self.ngram_max,
            "include_graph_features": self.include_graph_features,
            "normalization": self.normalization.as_dict(),
        }


@dataclass(frozen=True)
class GraphFeature:
    """The deterministic numeric signals extracted from one contract."""

    values: dict[str, float]

    def as_vector(self, names: Sequence[str]) -> list[float]:
        return [float(self.values.get(name, 0.0)) for name in names]


#: The numeric features, in a fixed order.
GRAPH_FEATURE_NAMES: tuple[str, ...] = (
    "code_size",
    "instruction_count",
    "block_count",
    "reachable_block_count",
    "unreachable_byte_size",
    "edge_count",
    "branch_count",
    "unresolved_jump_count",
    "cycle_count",
    "call_count",
    "create_count",
    "storage_read_count",
    "storage_write_count",
    "call_then_storage_write_count",
    "stack_underflow_count",
    "max_stack_depth",
    "metadata_size",
    "unique_opcode_ratio",
)


def _graph_feature(features: Any) -> GraphFeature:
    histogram = features.opcode_histogram or {}
    instruction_count = features.instruction_count
    unique_ratio = len(histogram) / instruction_count if instruction_count else 0.0
    values = {
        "code_size": float(features.code_size),
        "instruction_count": float(features.instruction_count),
        "block_count": float(features.block_count),
        "reachable_block_count": float(features.reachable_block_count),
        "unreachable_byte_size": float(features.unreachable_byte_size),
        "edge_count": float(features.edge_count),
        "branch_count": float(features.branch_count),
        "unresolved_jump_count": float(features.unresolved_jump_count),
        "cycle_count": float(features.cycle_count),
        "call_count": float(len(features.call_offsets)),
        "create_count": float(len(features.create_offsets)),
        "storage_read_count": float(len(features.storage_read_offsets)),
        "storage_write_count": float(len(features.storage_write_offsets)),
        "call_then_storage_write_count": float(len(features.call_then_storage_write)),
        "stack_underflow_count": float(len(features.stack_underflow_offsets)),
        "max_stack_depth": float(features.max_stack_depth),
        "metadata_size": float(features.metadata_size),
        "unique_opcode_ratio": unique_ratio,
    }
    return GraphFeature(values=values)


@dataclass(frozen=True)
class _Analysis:
    """Everything derived from one contract's bytecode."""

    raw_document: str
    normalized_document: str
    graph: GraphFeature
    ngram_document: str


def analyse(sample: Sample, config: FeatureConfig) -> _Analysis:
    """Disassemble a contract and derive its documents and graph features."""
    table = load_fork(config.fork)
    disassembly = disassemble(sample.bytecode, table)
    cfg = build_cfg(disassembly)
    features = extract_features(disassembly, cfg)

    stream = tokenize(disassembly.instructions, config.normalization)

    # The n-gram document uses the normalised stream, so that PUSH width
    # and constant masking are reflected in the n-gram vocabulary. The raw
    # single-token document is kept separately.
    normalized_ngrams = build_ngrams(stream.normalized_tokens, config.ngram_max)
    raw_ngrams = build_ngrams(stream.raw_tokens, config.ngram_max)

    return _Analysis(
        raw_document=" ".join(raw_ngrams),
        normalized_document=" ".join(normalized_ngrams),
        graph=_graph_feature(features),
        ngram_document=" ".join(normalized_ngrams),
    )


class FeatureBuilder:
    """Fit and apply the feature pipeline.

    Usage::

        builder = FeatureBuilder(config)
        X_train = builder.fit(train_samples)
        X_test = builder.transform(test_samples)

    The vectorizers are fitted on the training corpus only. ``transform``
    raises if the builder has not been fitted.
    """

    def __init__(self, config: FeatureConfig | None = None) -> None:
        self.config = config or FeatureConfig()
        self._raw_vectorizer: TfidfVectorizer | None = None
        self._normalized_vectorizer: TfidfVectorizer | None = None
        self._scaler: StandardScaler | None = None
        self._fitted = False

    # -- internals --------------------------------------------------------

    def _analyse_all(self, samples: Sequence[Sample]) -> list[_Analysis]:
        return [analyse(sample, self.config) for sample in samples]

    @staticmethod
    def _make_vectorizer(config: FeatureConfig) -> TfidfVectorizer:
        return TfidfVectorizer(
            lowercase=False,
            analyzer="word",
            # Not a credential: this is the regular expression that splits
            # the space-delimited opcode n-gram document into terms.
            token_pattern=r"[^ ]+",  # noqa: S106
            ngram_range=(config.ngram_min, config.ngram_max),
            norm="l2",
            smooth_idf=True,
            sublinear_tf=False,
            dtype=np.float64,
        )

    # -- public API --------------------------------------------------------

    @property
    def is_fitted(self) -> bool:
        return self._fitted

    def fit(self, samples: Sequence[Sample]) -> csr_matrix:
        """Fit the vectorizers and the scaler on the given samples."""
        analyses = self._analyse_all(samples)

        self._raw_vectorizer = self._make_vectorizer(self.config)
        self._normalized_vectorizer = self._make_vectorizer(self.config)
        self._raw_vectorizer.fit([a.raw_document for a in analyses])
        self._normalized_vectorizer.fit([a.normalized_document for a in analyses])

        if self.config.include_graph_features:
            matrix = np.array(
                [a.graph.as_vector(GRAPH_FEATURE_NAMES) for a in analyses],
                dtype=np.float64,
            )
            self._scaler = StandardScaler()
            self._scaler.fit(matrix)

        self._fitted = True
        return self.transform(samples)

    def transform(self, samples: Sequence[Sample]) -> csr_matrix:
        """Transform samples into the feature matrix."""
        if not self._fitted:
            raise RuntimeError("FeatureBuilder must be fitted before transform")
        assert self._raw_vectorizer is not None
        assert self._normalized_vectorizer is not None

        analyses = self._analyse_all(samples)
        raw = self._raw_vectorizer.transform([a.raw_document for a in analyses])
        normalized = self._normalized_vectorizer.transform(
            [a.normalized_document for a in analyses]
        )

        blocks = [raw, normalized]

        if self.config.include_graph_features and self._scaler is not None:
            matrix = np.array(
                [a.graph.as_vector(GRAPH_FEATURE_NAMES) for a in analyses],
                dtype=np.float64,
            )
            scaled = self._scaler.transform(matrix)
            blocks.append(csr_matrix(scaled))

        combined = hstack(blocks, format="csr")
        return combined

    # -- artifact support --------------------------------------------------

    def vocabulary_summary(self) -> dict[str, Any]:
        """A description of the fitted vocabularies for the manifest."""
        if not self._fitted:
            raise RuntimeError("FeatureBuilder must be fitted first")
        assert self._raw_vectorizer is not None
        assert self._normalized_vectorizer is not None
        return {
            "raw_vocabulary_size": len(self._raw_vectorizer.vocabulary_),
            "normalized_vocabulary_size": len(self._normalized_vectorizer.vocabulary_),
            "raw_terms": sorted(self._raw_vectorizer.vocabulary_),
            "normalized_terms": sorted(self._normalized_vectorizer.vocabulary_),
        }
