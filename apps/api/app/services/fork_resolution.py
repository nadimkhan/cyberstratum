"""Decide which fork's opcode table a scan should be analysed with.

The problem this solves
-----------------------

``cancun`` was the hard-coded answer for every scan. It is the right
answer for a good many chains and the wrong one for the rest: a chain
that predates Shanghai has no ``PUSH0``, zkSync is not an EVM, and the
majority of the chains a discovery feed finds are neither Ethereum
mainnet nor a Cancun L2.

Three facts decide it:

* A verified, deployed contract must be executable on its chain. The
  opcodes its runtime bytecode uses are therefore a lower bound on the
  chain's fork.
* The vendored opcode tables are ordered, and every opcode's first
  appearance is known, so the floor can be computed exactly
  (:mod:`evm_analysis.fork_inference`).
* A caller may still ask for a specific fork. That request is a claim
  about the chain, and it is checked against the bytecode rather than
  obeyed blindly: a request for an older fork than the code needs is a
  contradiction, and the contradiction is recorded.

The outcome is written to the scan (``fork``, ``fork_source``,
``fork_conflict``) so that the report can say how the fork was chosen,
and so that a scan analysed under an inferred fork can be excluded from
anything that depends on exact chain semantics.
"""

from __future__ import annotations

from dataclasses import dataclass

from evm_analysis.fork_inference import ForkRequirement, fork_index
from evm_analysis.opcodes import supported_forks

__all__ = [
    "ForkResolution",
    "SOURCE_FALLBACK",
    "SOURCE_INFERRED",
    "SOURCE_REQUESTED",
    "resolve_fork",
]

#: The caller named the fork and the code agrees with them.
SOURCE_REQUESTED = "requested"

#: The fork was derived from the bytecode.
SOURCE_INFERRED = "inferred"

#: Neither a usable request nor a usable inference was available.
SOURCE_FALLBACK = "fallback"


@dataclass(frozen=True, slots=True)
class ForkResolution:
    """The fork a scan will be analysed with, and why.

    Attributes:
        fork: The fork name to load.
        source: One of ``requested``, ``inferred`` or ``fallback``.
        conflict: True when the caller's request and the bytecode
            disagree, or when the code could not be placed at all.
        reason: A short human-readable explanation, for the report.
        requirement: The inference that produced the decision.
    """

    fork: str
    source: str
    conflict: bool
    reason: str
    requirement: ForkRequirement

    def as_dict(self) -> dict[str, object]:
        """A JSON-friendly view for the scan artifact."""
        payload = self.requirement.as_dict()
        payload.update(
            {
                "fork": self.fork,
                "source": self.source,
                "conflict": self.conflict,
                "reason": self.reason,
            }
        )
        return payload


def resolve_fork(requested: str | None, requirement: ForkRequirement) -> ForkResolution:
    """Choose the fork for a scan.

    Args:
        requested: The fork the caller asked for, or an empty string or
            ``None`` when they did not.
        requirement: The floor inferred from the runtime bytecode.

    Returns:
        A :class:`ForkResolution`. The rules are, in order:

        1. A request that is at least as new as the inferred floor is
           honoured: the caller knows the chain, the bytecode only
           bounds it.
        2. A request older than the inferred floor is *not* honoured --
           the older table would report a real opcode as invalid -- and
           the conflict is recorded.
        3. With no request, the inferred floor is used.
        4. A code that cannot be placed at all falls back to the newest
           supported fork, and the scan is marked as a conflict so that
           it cannot be read as a clean analysis.
    """
    newest = supported_forks()[-1]
    requested_fork = (requested or "").strip()
    requested_position = fork_index(requested_fork) if requested_fork else -1
    required_position = fork_index(requirement.required_fork)

    if not requirement.is_analysable:
        fork = requested_fork if requested_position >= 0 else newest
        return ForkResolution(
            fork=fork,
            source=SOURCE_FALLBACK,
            conflict=True,
            reason=(
                "the bytecode contains bytes that no supported fork defines, "
                "so it cannot be placed in the opcode table"
            ),
            requirement=requirement,
        )

    if requested_position >= 0:
        if requested_position >= required_position:
            return ForkResolution(
                fork=requested_fork,
                source=SOURCE_REQUESTED,
                conflict=False,
                reason="the requested fork is at least as new as the bytecode requires",
                requirement=requirement,
            )
        # The request is honoured. A caller who asks for an older fork is
        # usually asking a deliberate question -- "what does this contract
        # mean on a chain from before that opcode existed?" -- and the
        # older table answering "that opcode is invalid" is the answer
        # they wanted. What must not happen is the disagreement passing
        # unnoticed, so it is recorded on the scan and printed in the
        # report.
        return ForkResolution(
            fork=requested_fork,
            source=SOURCE_REQUESTED,
            conflict=True,
            reason=(
                f"the requested fork {requested_fork!r} predates the "
                f"{requirement.required_fork!r} the bytecode needs "
                f"({requirement.newest_opcode}); the contract cannot execute "
                "under the requested fork, and the opcodes it uses are "
                "reported as invalid in the analysis"
            ),
            requirement=requirement,
        )

    return ForkResolution(
        fork=requirement.required_fork,
        source=SOURCE_INFERRED,
        conflict=False,
        reason="the fork was inferred from the opcodes the bytecode uses",
        requirement=requirement,
    )
