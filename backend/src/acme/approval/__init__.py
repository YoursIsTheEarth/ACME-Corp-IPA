"""Approval (F14, F15): rules-engine floor, AI VP draft, Critic loop, tighten-only clamp.

    result = apply_policy(invoice, findings, revision_ctx)   # pure
    state = run_approval(state)                              # sets decision_draft, critique, decision
"""

from acme.approval.agent import run_approval
from acme.approval.policy import PolicyResult, apply_policy, stricter

__all__ = ["PolicyResult", "apply_policy", "run_approval", "stricter"]
