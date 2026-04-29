"""
Base classes for Verdict reviewer agents.

Fine-tuning contract
--------------------
Agents are split into two categories that must never be conflated:

  FineTunableAgent  — should be fine-tuned on domain-specific legal data.
                      The model backing this agent is trained to specialise in its task.

  BaselineAgent     — must stay as the unmodified base model.
                      These agents act as adversarial quality gates against fine-tuned
                      workers. Fine-tuning them defeats the purpose: a fine-tuned model
                      reviewing its own fine-tuned peer shares the same biases and blind
                      spots and will not catch drift or hallucinations.

Current assignments
-------------------
  KiraWorker          → FineTunableAgent  (dataset: LEDGAR)
  KiraPanelReviewer   → FineTunableAgent  (same fine-tuned weights as KiraWorker, distinct prompts)
  HarveyReviewer      → FineTunableAgent  (dataset: CUAD — second priority)
  AdminMergeAgent     → BaselineAgent     (structural synthesis, not domain reasoning)
  KiraValidatorAgent  → BaselineAgent     (hallucination detection)

Future work
-----------
When a fine-tuned checkpoint is ready for an agent, set its `fine_tune_checkpoint`
class attribute. The provider factory can read this and route inference to the
fine-tuned endpoint instead of the base model — no prompt changes required.
"""

from __future__ import annotations

from abc import ABC


class FineTunableAgent(ABC):
    """Agent that should be fine-tuned on domain-specific data.

    Subclasses must declare:
      fine_tune_dataset  : the source dataset name (e.g. 'LEDGAR', 'CUAD')
      fine_tune_priority : 1 = highest; fine-tune this first
      fine_tune_checkpoint: path or HF repo of the fine-tuned weights once available
                            (None until training is complete)
    """

    fine_tune_dataset: str = ""
    fine_tune_priority: int = 99
    fine_tune_checkpoint: str | None = None

    @classmethod
    def is_fine_tuned(cls) -> bool:
        return cls.fine_tune_checkpoint is not None


class BaselineAgent(ABC):
    """Agent that must remain as the unmodified base model.

    These agents serve as quality gates against fine-tuned peers.
    Fine-tuning them is explicitly prohibited.

    Subclasses must declare:
      baseline_reason: one-line explanation of why this agent must stay baseline.
    """

    baseline_reason: str = ""

    @classmethod
    def must_stay_baseline(cls) -> bool:
        return True
